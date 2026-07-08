import shutil
import tempfile

from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.qr_manager.models import QRCode, ScanLog, Supervisor
from apps.staff.models import Employee, ServiceUnit

User = get_user_model()

# Employee/QRCode creation in these tests triggers the post_save signal
# that writes a real badge PNG via ImageField.save() -- that hits disk
# directly, unaffected by the test DB's transaction rollback. Point
# MEDIA_ROOT at a throwaway temp dir for the whole module so test runs
# never leak files into the real media/ directory.
_test_media_root = tempfile.mkdtemp(prefix="qr_manager_test_media_")
_media_root_override = override_settings(MEDIA_ROOT=_test_media_root)


def setUpModule():
    _media_root_override.enable()


def tearDownModule():
    _media_root_override.disable()
    shutil.rmtree(_test_media_root, ignore_errors=True)


def _grant_qrcode_perms(user):
    """Simulate membership in the 'QR Supervisors' group described in
    apps/qr_manager/admin.py's setup docs: full CRUD on QRCode."""
    perms = Permission.objects.filter(
        content_type__app_label="qr_manager",
        content_type__model="qrcode",
        codename__in=["add_qrcode", "change_qrcode", "delete_qrcode", "view_qrcode"],
    )
    user.user_permissions.set(perms)


class QRCodeAdminScopingTests(TestCase):
    """A non-superuser supervisor must only see/manage QR codes for
    employees in a unit they supervise (Supervisor model). The
    supervisor need not be an Employee in that unit themselves --
    that's the whole point of the explicit Supervisor assignment."""

    @classmethod
    def setUpTestData(cls):
        cls.library = ServiceUnit.objects.create(name="Library")
        cls.finance = ServiceUnit.objects.create(name="Finance and Accounting")

        # Supervises the Library, but has no Employee record at all --
        # proves scoping doesn't depend on the supervisor's own unit.
        cls.lib_sup_user = User.objects.create_user(
            email="lib.sup@example.com", is_staff=True
        )
        Supervisor.objects.create(user=cls.lib_sup_user, service_unit=cls.library)
        _grant_qrcode_perms(cls.lib_sup_user)

        cls.lib_emp_user = User.objects.create_user(email="lib.emp@example.com")
        cls.lib_emp = Employee.objects.create(
            user=cls.lib_emp_user, given_name="Lib", family_name="Employee",
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.library,
        )

        cls.fin_emp_user = User.objects.create_user(email="fin.emp@example.com")
        cls.fin_emp = Employee.objects.create(
            user=cls.fin_emp_user, given_name="Fin", family_name="Employee",
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )

        # Staff, has the group permissions, but no Supervisor row.
        cls.no_unit_user = User.objects.create_user(
            email="no.unit@example.com", is_staff=True
        )
        _grant_qrcode_perms(cls.no_unit_user)

        cls.superuser = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )

        # A post_save signal on Employee (apps/qr_manager/signals.py)
        # auto-creates a QRCode for every employee, so fetch those
        # rather than creating duplicates.
        cls.qr_lib = QRCode.objects.get(employee=cls.lib_emp)
        cls.qr_fin = QRCode.objects.get(employee=cls.fin_emp)
        cls.qr_visitor = QRCode.objects.create(label="Guest")

    def test_supervisor_changelist_scoped_to_supervised_unit(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(reverse("admin:qr_manager_qrcode_changelist"))
        self.assertEqual(resp.status_code, 200)
        object_list = list(resp.context["cl"].queryset)
        self.assertIn(self.qr_lib, object_list)
        self.assertNotIn(self.qr_fin, object_list)
        self.assertNotIn(self.qr_visitor, object_list)

    def test_supervisor_can_view_supervised_unit_object(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(
            reverse("admin:qr_manager_qrcode_change", args=[self.qr_lib.pk])
        )
        self.assertEqual(resp.status_code, 200)

    def test_supervisor_denied_other_unit_object(self):
        # get_queryset already scopes lookups to the supervisor's
        # supervised unit, so Django admin's get_object() finds
        # nothing and redirects (302) rather than reaching
        # has_change_permission(obj) at all -- still fully
        # inaccessible, just via a different code path.
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(
            reverse("admin:qr_manager_qrcode_change", args=[self.qr_fin.pk])
        )
        self.assertEqual(resp.status_code, 302)

    def test_supervisor_denied_visitor_object(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(
            reverse("admin:qr_manager_qrcode_change", args=[self.qr_visitor.pk])
        )
        self.assertEqual(resp.status_code, 302)

    def test_add_form_employee_choices_scoped(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(reverse("admin:qr_manager_qrcode_add"))
        self.assertEqual(resp.status_code, 200)
        choices_qs = resp.context["adminform"].form.fields["employee"].queryset
        self.assertIn(self.lib_emp, choices_qs)
        self.assertNotIn(self.fin_emp, choices_qs)

    def test_tampered_post_rejected(self):
        """Even a POST crafted with another unit's employee id is
        rejected -- ModelChoiceField validates against the restricted
        queryset regardless of what the client sends."""
        self.client.force_login(self.lib_sup_user)
        resp = self.client.post(
            reverse("admin:qr_manager_qrcode_add"),
            data={
                "employee": str(self.fin_emp.pk),
                "label": "",
                "qr_type": QRCode.QRType.ID,
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)  # re-renders with a form error
        self.assertFalse(
            QRCode.objects.filter(employee=self.fin_emp)
            .exclude(pk=self.qr_fin.pk)
            .exists()
        )

    def test_supervisor_without_supervisor_row_sees_nothing_and_cannot_add(self):
        self.client.force_login(self.no_unit_user)
        resp = self.client.get(reverse("admin:qr_manager_qrcode_changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context["cl"].queryset), [])

        resp = self.client.get(reverse("admin:qr_manager_qrcode_add"))
        self.assertEqual(resp.status_code, 403)

    def test_superuser_sees_and_can_access_everything(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:qr_manager_qrcode_changelist"))
        object_list = list(resp.context["cl"].queryset)
        self.assertIn(self.qr_lib, object_list)
        self.assertIn(self.qr_fin, object_list)
        self.assertIn(self.qr_visitor, object_list)

        resp = self.client.get(
            reverse("admin:qr_manager_qrcode_change", args=[self.qr_fin.pk])
        )
        self.assertEqual(resp.status_code, 200)


class QRCodeAdminPermissionMethodTests(TestCase):
    """Calls has_*_permission directly (bypassing get_queryset) to
    confirm the object-level scoping is correct on its own, not just
    incidentally enforced by queryset filtering hiding the object."""

    @classmethod
    def setUpTestData(cls):
        cls.library = ServiceUnit.objects.create(name="Library")
        cls.finance = ServiceUnit.objects.create(name="Finance and Accounting")

        cls.lib_sup_user = User.objects.create_user(
            email="lib.sup2@example.com", is_staff=True
        )
        Supervisor.objects.create(user=cls.lib_sup_user, service_unit=cls.library)
        _grant_qrcode_perms(cls.lib_sup_user)

        cls.fin_emp_user = User.objects.create_user(email="fin.emp2@example.com")
        cls.fin_emp = Employee.objects.create(
            user=cls.fin_emp_user, given_name="Fin", family_name="Employee",
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )
        cls.qr_fin = QRCode.objects.get(employee=cls.fin_emp)

    def test_has_permission_methods_deny_other_unit_object_directly(self):
        admin_instance = admin_site._registry[QRCode]
        request = RequestFactory().get("/admin/qr_manager/qrcode/")
        request.user = self.lib_sup_user
        self.assertFalse(admin_instance.has_change_permission(request, self.qr_fin))
        self.assertFalse(admin_instance.has_view_permission(request, self.qr_fin))
        self.assertFalse(admin_instance.has_delete_permission(request, self.qr_fin))


class SupervisorAdminAccessTests(TestCase):
    """Supervisor is the access-control mechanism itself, so only
    superusers may manage it -- even a user with QRCode permissions
    (and even Django model permissions on Supervisor, if accidentally
    granted) must not be able to self-assign a unit."""

    @classmethod
    def setUpTestData(cls):
        cls.library = ServiceUnit.objects.create(name="Library")
        cls.staff_user = User.objects.create_user(
            email="staffer@example.com", is_staff=True
        )
        perms = Permission.objects.filter(
            content_type__app_label="qr_manager",
            content_type__model="supervisor",
        )
        cls.staff_user.user_permissions.set(perms)
        cls.superuser = User.objects.create_superuser(
            email="admin2@example.com", password="x"
        )

    def test_non_superuser_cannot_access_supervisor_admin(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("admin:qr_manager_supervisor_changelist"))
        self.assertEqual(resp.status_code, 403)

    def test_superuser_can_access_supervisor_admin(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:qr_manager_supervisor_changelist"))
        self.assertEqual(resp.status_code, 200)


class AnonymousAdminLoginPageTests(TestCase):
    """The admin login page itself renders each_context() -> get_app_list()
    -> has_module_permission() for every registered ModelAdmin, for an
    anonymous request.user -- before any login has happened. Regression
    test for a bug where ScanLogAdmin/SupervisorEmployeeAdmin's
    has_module_permission ran Supervisor.objects.filter(user=request.user)
    against an AnonymousUser, raising a TypeError and 500ing the login
    page for everyone, including superusers."""

    def test_main_admin_login_page_does_not_crash_for_anonymous_visitor(self):
        resp = self.client.get(reverse("admin:login"))
        self.assertEqual(resp.status_code, 200)

    @override_settings(ROOT_URLCONF="apps.staff.site_urls")
    def test_qr_admin_login_page_does_not_crash_for_anonymous_visitor(self):
        resp = self.client.get(
            reverse("qr_admin:login"), HTTP_HOST="staff.lvh.me"
        )
        self.assertEqual(resp.status_code, 200)


@override_settings(ROOT_URLCONF="apps.staff.site_urls")
class QRSupervisorSiteTests(TestCase):
    """The dedicated /qr-admin/ site (apps/qr_manager/qr_admin_site.py):
    login is gated on holding a Supervisor row, and it exposes only
    QRCode (scoped, full CRUD) and Employee (scoped, read-only).

    /qr-admin/ is mounted on the staff subdomain's urlconf
    (apps/staff/site_urls.py), not main.urls. override_settings makes
    reverse() resolve against it; HTTP_HOST="staff.lvh.me" on every
    client call makes main.middleware.SubdomainRoutingMiddleware pick
    the same urlconf for the actual request (it keys off the Host
    header, not settings.ROOT_URLCONF, once a subdomain matches)."""

    @classmethod
    def setUpTestData(cls):
        cls.library = ServiceUnit.objects.create(name="Library")
        cls.finance = ServiceUnit.objects.create(name="Finance and Accounting")

        cls.lib_sup_user = User.objects.create_user(
            email="lib.sup3@example.com", is_staff=True
        )
        Supervisor.objects.create(user=cls.lib_sup_user, service_unit=cls.library)
        _grant_qrcode_perms(cls.lib_sup_user)

        cls.lib_emp_user = User.objects.create_user(email="lib.emp3@example.com")
        cls.lib_emp = Employee.objects.create(
            user=cls.lib_emp_user, given_name="Lib", family_name="Employee3",
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.library,
        )
        cls.fin_emp_user = User.objects.create_user(email="fin.emp3@example.com")
        cls.fin_emp = Employee.objects.create(
            user=cls.fin_emp_user, given_name="Fin", family_name="Employee3",
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )

        # Staff, has the group permissions, but no Supervisor row --
        # must be denied entry to this site entirely.
        cls.plain_staff_user = User.objects.create_user(
            email="plain.staff@example.com", is_staff=True
        )
        _grant_qrcode_perms(cls.plain_staff_user)

        cls.superuser = User.objects.create_superuser(
            email="admin3@example.com", password="x"
        )

    STAFF_HOST = "staff.lvh.me"

    def test_staff_without_supervisor_row_denied_login(self):
        self.client.force_login(self.plain_staff_user)
        resp = self.client.get(reverse("qr_admin:index"), HTTP_HOST=self.STAFF_HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("qr_admin:login"), resp.url)

    def test_supervisor_can_log_in_and_see_own_unit_qrcodes(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(reverse("qr_admin:index"), HTTP_HOST=self.STAFF_HOST)
        self.assertNotIn("admin/login.html", [t.name for t in resp.templates])

        resp = self.client.get(
            reverse("qr_admin:qr_manager_qrcode_changelist"), HTTP_HOST=self.STAFF_HOST
        )
        self.assertEqual(resp.status_code, 200)
        object_list = list(resp.context["cl"].queryset)
        lib_qr = QRCode.objects.get(employee=self.lib_emp)
        fin_qr = QRCode.objects.get(employee=self.fin_emp)
        self.assertIn(lib_qr, object_list)
        self.assertNotIn(fin_qr, object_list)

    def test_supervisor_read_only_roster_scoped_to_own_unit(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(
            reverse("qr_admin:staff_employee_changelist"), HTTP_HOST=self.STAFF_HOST
        )
        self.assertEqual(resp.status_code, 200)
        object_list = list(resp.context["cl"].queryset)
        self.assertIn(self.lib_emp, object_list)
        self.assertNotIn(self.fin_emp, object_list)

        # Add is fully blocked.
        resp = self.client.get(
            reverse("qr_admin:staff_employee_add"), HTTP_HOST=self.STAFF_HOST
        )
        self.assertEqual(resp.status_code, 403)

        # The change URL renders read-only (Django's view-only mode --
        # GET succeeds since has_view_permission is True), but an
        # actual edit attempt is blocked since has_change_permission
        # is False.
        resp = self.client.get(
            reverse("qr_admin:staff_employee_change", args=[self.lib_emp.pk]),
            HTTP_HOST=self.STAFF_HOST,
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            reverse("qr_admin:staff_employee_change", args=[self.lib_emp.pk]),
            data={"given_name": "Changed"},
            HTTP_HOST=self.STAFF_HOST,
        )
        self.assertEqual(resp.status_code, 403)
        self.lib_emp.refresh_from_db()
        self.assertEqual(self.lib_emp.given_name, "Lib")

    def test_superuser_sees_everything_on_supervisor_site(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(
            reverse("qr_admin:staff_employee_changelist"), HTTP_HOST=self.STAFF_HOST
        )
        object_list = list(resp.context["cl"].queryset)
        self.assertIn(self.lib_emp, object_list)
        self.assertIn(self.fin_emp, object_list)


class ScanLogAdminScopingTests(TestCase):
    """Scan history is visible to a supervisor only for employees in
    a unit they supervise -- same scoping as QRCode, but gated on
    holding a Supervisor row rather than a Django model permission
    (see ScanLogAdmin._is_supervisor), so it works identically on the
    main admin and on the dedicated /qr-admin/ site with no extra
    permission grant needed."""

    @classmethod
    def setUpTestData(cls):
        cls.library = ServiceUnit.objects.create(name="Library")
        cls.finance = ServiceUnit.objects.create(name="Finance and Accounting")

        cls.lib_sup_user = User.objects.create_user(
            email="lib.sup4@example.com", is_staff=True
        )
        Supervisor.objects.create(user=cls.lib_sup_user, service_unit=cls.library)

        cls.plain_staff_user = User.objects.create_user(
            email="plain.staff4@example.com", is_staff=True
        )

        cls.lib_emp_user = User.objects.create_user(email="lib.emp4@example.com")
        cls.lib_emp = Employee.objects.create(
            user=cls.lib_emp_user, given_name="Lib", family_name="Employee4",
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.library,
        )
        cls.fin_emp_user = User.objects.create_user(email="fin.emp4@example.com")
        cls.fin_emp = Employee.objects.create(
            user=cls.fin_emp_user, given_name="Fin", family_name="Employee4",
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )

        cls.superuser = User.objects.create_superuser(
            email="admin4@example.com", password="x"
        )

        lib_qr = QRCode.objects.get(employee=cls.lib_emp)
        fin_qr = QRCode.objects.get(employee=cls.fin_emp)
        cls.lib_scan = ScanLog.objects.create(qrcode=lib_qr, result=ScanLog.Result.VALID)
        cls.fin_scan = ScanLog.objects.create(qrcode=fin_qr, result=ScanLog.Result.VALID)
        cls.unknown_scan = ScanLog.objects.create(qrcode=None, result=ScanLog.Result.UNKNOWN)

    def test_main_admin_scoped_to_supervised_unit(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(reverse("admin:qr_manager_scanlog_changelist"))
        self.assertEqual(resp.status_code, 200)
        object_list = list(resp.context["cl"].queryset)
        self.assertIn(self.lib_scan, object_list)
        self.assertNotIn(self.fin_scan, object_list)
        self.assertNotIn(self.unknown_scan, object_list)

    def test_main_admin_denied_without_supervisor_row(self):
        self.client.force_login(self.plain_staff_user)
        resp = self.client.get(reverse("admin:qr_manager_scanlog_changelist"))
        self.assertEqual(resp.status_code, 403)

    @override_settings(ROOT_URLCONF="apps.staff.site_urls")
    def test_qr_admin_site_scoped_to_supervised_unit(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(
            reverse("qr_admin:qr_manager_scanlog_changelist"),
            HTTP_HOST="staff.lvh.me",
        )
        self.assertEqual(resp.status_code, 200)
        object_list = list(resp.context["cl"].queryset)
        self.assertIn(self.lib_scan, object_list)
        self.assertNotIn(self.fin_scan, object_list)

    def test_superuser_sees_all_scans(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:qr_manager_scanlog_changelist"))
        object_list = list(resp.context["cl"].queryset)
        self.assertIn(self.lib_scan, object_list)
        self.assertIn(self.fin_scan, object_list)
        self.assertIn(self.unknown_scan, object_list)


@override_settings(ROOT_URLCONF="apps.staff.site_urls")
class QRAdminSiteBrandingTests(TestCase):
    """site_header/site_title/index_title on /qr-admin/ must name the
    actual logged-in supervisor's unit (not a generic label), and
    must tell a superuser plainly that they're viewing all units, not
    one in particular (see QRSupervisorAdminSite.each_context)."""

    @classmethod
    def setUpTestData(cls):
        cls.library = ServiceUnit.objects.create(name="Library")
        cls.finance = ServiceUnit.objects.create(name="Finance and Accounting")

        cls.lib_sup_user = User.objects.create_user(
            email="lib.sup5@example.com", is_staff=True
        )
        Supervisor.objects.create(user=cls.lib_sup_user, service_unit=cls.library)
        _grant_qrcode_perms(cls.lib_sup_user)

        cls.multi_sup_user = User.objects.create_user(
            email="multi.sup5@example.com", is_staff=True
        )
        Supervisor.objects.create(user=cls.multi_sup_user, service_unit=cls.library)
        Supervisor.objects.create(user=cls.multi_sup_user, service_unit=cls.finance)
        _grant_qrcode_perms(cls.multi_sup_user)

        cls.superuser = User.objects.create_superuser(
            email="admin5@example.com", password="x"
        )

    def test_supervisor_sees_own_unit_name_in_header(self):
        self.client.force_login(self.lib_sup_user)
        resp = self.client.get(reverse("qr_admin:index"), HTTP_HOST="staff.lvh.me")
        self.assertIn("Library", resp.context["site_header"])
        self.assertIn("Library", resp.context["site_title"])
        self.assertEqual(resp.context["index_title"], "Library")

    def test_supervisor_with_multiple_units_sees_both(self):
        self.client.force_login(self.multi_sup_user)
        resp = self.client.get(reverse("qr_admin:index"), HTTP_HOST="staff.lvh.me")
        self.assertIn("Library", resp.context["site_header"])
        self.assertIn("Finance and Accounting", resp.context["site_header"])

    def test_superuser_sees_all_units_label_not_a_specific_unit(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("qr_admin:index"), HTTP_HOST="staff.lvh.me")
        self.assertIn("All Units (Superuser)", resp.context["site_header"])
        self.assertNotIn("Library", resp.context["site_header"])
