import shutil
import tempfile
from datetime import datetime

from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.qr_manager.models import QRCode, ScanLog, Supervisor
from apps.qr_manager.utils import humanize_duration
from apps.staff.models import Employee, ServiceUnit

User = get_user_model()

# QR generation is supervisor-triggered only (no more auto-generation
# on Employee save -- see git history for the removed post_save
# signal). But QRCodeAdmin.save_model() still calls generate_qr()
# explicitly on every admin add/change, which writes a real badge PNG
# via ImageField.save() -- that hits disk directly, unaffected by the
# test DB's transaction rollback. Point MEDIA_ROOT at a throwaway temp
# dir for the whole module so test runs never leak files into the
# real media/ directory.
_test_media_root = tempfile.mkdtemp(prefix="qr_manager_test_media_")
_media_root_override = override_settings(MEDIA_ROOT=_test_media_root)


def setUpModule():
    _media_root_override.enable()


def tearDownModule():
    _media_root_override.disable()
    shutil.rmtree(_test_media_root, ignore_errors=True)


def _name_profile(user, given, family):
    """Fill the auto-created profile rather than naming the Employee.

    Employee no longer holds name data -- it moved to UserProfile per
    docs/rebuild-schema.md, and apps/staff/models.py:186 notes that call
    sites read through self.user.profile.* instead. These fixtures were
    never updated, so Employee(given_name=..., family_name=...) raised
    TypeError in setUpClass and took each class down with it.

    apps/user/signals.py creates the profile, so this fills it in.
    """
    profile = user.profile
    profile.given_name = given
    profile.family_name = family
    profile.save(update_fields=["given_name", "family_name"])
    return profile


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
            user=cls.lib_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.library,
        )
        _name_profile(cls.lib_emp_user, "Lib", "Employee")

        cls.fin_emp_user = User.objects.create_user(email="fin.emp@example.com")
        cls.fin_emp = Employee.objects.create(
            user=cls.fin_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )
        _name_profile(cls.fin_emp_user, "Fin", "Employee")

        # Staff, has the group permissions, but no Supervisor row.
        cls.no_unit_user = User.objects.create_user(
            email="no.unit@example.com", is_staff=True
        )
        _grant_qrcode_perms(cls.no_unit_user)

        cls.superuser = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )

        # QR generation is supervisor-triggered only -- create these
        # explicitly rather than relying on any auto-generation.
        cls.qr_lib = QRCode.objects.create(employee=cls.lib_emp)
        cls.qr_fin = QRCode.objects.create(employee=cls.fin_emp)
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

    def test_changelist_annotates_scan_and_unique_ip_counts(self):
        # 3 scans on qr_lib: 2 from one IP, 1 from another -> 2 unique.
        ScanLog.objects.create(
            qrcode=self.qr_lib, result=ScanLog.Result.VALID, ip_address="10.0.0.1"
        )
        ScanLog.objects.create(
            qrcode=self.qr_lib, result=ScanLog.Result.VALID, ip_address="10.0.0.1"
        )
        ScanLog.objects.create(
            qrcode=self.qr_lib, result=ScanLog.Result.VALID, ip_address="10.0.0.2"
        )

        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:qr_manager_qrcode_changelist"))
        object_list = list(resp.context["cl"].queryset)
        lib_result = next(o for o in object_list if o.pk == self.qr_lib.pk)
        self.assertEqual(lib_result.scan_count, 3)
        self.assertEqual(lib_result.unique_ip_count, 2)

        fin_result = next(o for o in object_list if o.pk == self.qr_fin.pk)
        self.assertEqual(fin_result.scan_count, 0)
        self.assertEqual(fin_result.unique_ip_count, 0)


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
            user=cls.fin_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )
        _name_profile(cls.fin_emp_user, "Fin", "Employee")
        cls.qr_fin = QRCode.objects.create(employee=cls.fin_emp)

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
            user=cls.lib_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.library,
        )
        _name_profile(cls.lib_emp_user, "Lib", "Employee3")
        cls.fin_emp_user = User.objects.create_user(email="fin.emp3@example.com")
        cls.fin_emp = Employee.objects.create(
            user=cls.fin_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )
        _name_profile(cls.fin_emp_user, "Fin", "Employee3")
        # QR generation is supervisor-triggered only -- create explicitly.
        QRCode.objects.create(employee=cls.lib_emp)
        QRCode.objects.create(employee=cls.fin_emp)

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
        # The name lives on UserProfile now, not Employee -- the point of
        # the assertion is unchanged: the blocked POST mutated nothing.
        self.assertEqual(self.lib_emp.user.profile.given_name, "Lib")

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
            user=cls.lib_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.library,
        )
        _name_profile(cls.lib_emp_user, "Lib", "Employee4")
        cls.fin_emp_user = User.objects.create_user(email="fin.emp4@example.com")
        cls.fin_emp = Employee.objects.create(
            user=cls.fin_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.finance,
        )
        _name_profile(cls.fin_emp_user, "Fin", "Employee4")

        cls.superuser = User.objects.create_superuser(
            email="admin4@example.com", password="x"
        )

        cls.lib_qr = QRCode.objects.create(employee=cls.lib_emp)
        cls.fin_qr = QRCode.objects.create(employee=cls.fin_emp)
        cls.lib_scan = ScanLog.objects.create(
            qrcode=cls.lib_qr, result=ScanLog.Result.VALID, ip_address="10.0.0.1"
        )
        cls.fin_scan = ScanLog.objects.create(
            qrcode=cls.fin_qr, result=ScanLog.Result.VALID, ip_address="10.0.0.5"
        )
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

    def test_badge_scan_count_annotation_correct_and_no_row_duplication(self):
        # 2 more scans on lib_qr: one repeats cls.lib_scan's IP
        # (10.0.0.1), one from a distinct IP -- 3 total scans for
        # lib_qr, 2 unique IPs.
        ScanLog.objects.create(
            qrcode=self.lib_qr, result=ScanLog.Result.VALID, ip_address="10.0.0.1"
        )
        ScanLog.objects.create(
            qrcode=self.lib_qr, result=ScanLog.Result.VALID, ip_address="10.0.0.9"
        )

        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:qr_manager_scanlog_changelist"))
        object_list = list(resp.context["cl"].queryset)

        # No self-join row multiplication: still exactly one row per
        # ScanLog, not one per (ScanLog x sibling-scan) pair.
        self.assertEqual(len(object_list), 5)

        lib_rows = [o for o in object_list if o.qrcode_id == self.lib_qr.pk]
        self.assertEqual(len(lib_rows), 3)
        for row in lib_rows:
            self.assertEqual(row.badge_scan_count, 3)
            self.assertEqual(row.badge_unique_ip_count, 2)

        fin_row = next(o for o in object_list if o.qrcode_id == self.fin_qr.pk)
        self.assertEqual(fin_row.badge_scan_count, 1)
        self.assertEqual(fin_row.badge_unique_ip_count, 1)

        unknown_row = next(o for o in object_list if o.qrcode_id is None)
        self.assertEqual(unknown_row.badge_scan_count, 0)
        self.assertEqual(unknown_row.badge_unique_ip_count, 0)


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


class HumanizeDurationTests(SimpleTestCase):
    """apps/qr_manager/utils.py's humanize_duration() -- pure function,
    no DB needed. Naive datetimes throughout: the aware/naive handling
    (timezone.localtime() when aware) is a thin wrapper around the same
    calendar math these cases exercise, not separate logic worth
    re-testing per case."""

    def test_same_calendar_day(self):
        start = datetime(2026, 8, 14, 8, 0)
        end = datetime(2026, 8, 14, 20, 0)
        self.assertEqual(humanize_duration(start, end), "Today")

    def test_twenty_nine_days(self):
        start = datetime(2026, 7, 1)
        end = datetime(2026, 7, 30)
        self.assertEqual(humanize_duration(start, end), "29 days")

    def test_thirty_days_is_one_calendar_month_not_a_day_count(self):
        # April has 30 days -- Apr 1 + 30 days = May 1, exactly one
        # calendar month, proving the switch at the 30-day mark lands
        # on real calendar math rather than a day/30 approximation.
        start = datetime(2026, 4, 1)
        end = datetime(2026, 5, 1)
        self.assertEqual(humanize_duration(start, end), "1 month")

    def test_eleven_months(self):
        start = datetime(2025, 1, 15)
        end = datetime(2025, 12, 15)
        self.assertEqual(humanize_duration(start, end), "11 months")

    def test_exactly_twelve_months_is_one_year(self):
        start = datetime(2025, 1, 15)
        end = datetime(2026, 1, 15)
        self.assertEqual(humanize_duration(start, end), "1 year")

    def test_leap_day_signup_not_yet_recurred_reads_as_eleven_months(self):
        # Feb 29 2024 -> Feb 28 2025: the 29th doesn't exist in 2025, so
        # this is NOT yet a full calendar year -- calendar-aware math
        # must decrement to 11 months here, not round up to 12/"1 year".
        start = datetime(2024, 2, 29)
        end = datetime(2025, 2, 28)
        self.assertEqual(humanize_duration(start, end), "11 months")

    def test_future_dated_signup_returns_today_never_negative(self):
        start = datetime(2026, 8, 20)
        end = datetime(2026, 8, 14)
        self.assertEqual(humanize_duration(start, end), "Today")

    def test_singular_one_day(self):
        start = datetime(2026, 8, 13)
        end = datetime(2026, 8, 14)
        self.assertEqual(humanize_duration(start, end), "1 day")

    def test_singular_one_month(self):
        start = datetime(2026, 1, 15)
        end = datetime(2026, 2, 15)
        self.assertEqual(humanize_duration(start, end), "1 month")


# ─────────────────────────────────────────────────────────────────────
# QA 500 sweep (Phase 1, 2026-08-31) — reproduction tests appended below.
# Expected to FAIL on the current tree; see qa_500_report.md at the repo
# root. Explicit lvh.me-family HTTP_HOST on every request, because
# SUBDOMAIN_DOMAIN is 'lvh.me' under test.
# ─────────────────────────────────────────────────────────────────────

from django.urls import reverse as _reverse

from apps.user.models import UserProfile as _UserProfile

PUBLIC_HOST = "lvh.me"
STAFF_HOST = "staff.lvh.me"


class VerifyScanMissingProfileTests(TestCase):
    """Finding 6 at its worst call site — a PUBLIC, ANONYMOUS 500.

    apps/qr_manager/views.py:133, inside _staff_verification_context():

        "display_name": employee.user.profile.display_name,

    and the alumni twin at views.py:90:

        "display_name": alumni_profile.user.profile.display_name,

    Both are plain Python dict construction, not template rendering, so
    the RelatedObjectDoesNotExist propagates as a 500. (In a template it
    would be swallowed — ObjectDoesNotExist sets
    silent_variable_failure = True — which is exactly why this one bites
    here and not on the pages that read the same attribute in markup.)

    Reachable whenever a UserProfile is removed after the holder record
    was created: an admin deleting the profile row, or any cascade that
    takes it. The badge stays in someone's wallet and keeps resolving.
    """

    @classmethod
    def setUpTestData(cls):
        cls.unit = ServiceUnit.objects.create(name="Registry")
        cls.user = User.objects.create_user(email="badge.holder@example.com")
        # Fill the auto-created profile (apps/user/signals.py) rather
        # than making a second one -- UserProfile's pk is the user's pk.
        _profile = cls.user.profile
        _profile.given_name = "Badge"
        _profile.family_name = "Holder"
        _profile.save(update_fields=["given_name", "family_name"])
        cls.employee = Employee.objects.create(
            user=cls.user,
            staff_track=Employee.StaffTrack.SERVICE,
            service_unit=cls.unit,
        )
        cls.qr = QRCode.objects.create(employee=cls.employee)

    def test_scan_survives_a_holder_whose_profile_row_is_gone(self):
        """Finding 4's reproduction, flipped.

        The badge was minted while the profile existed and is removed
        afterwards; the printed QR code is unchanged and still scans.
        It must refuse honestly rather than 500.
        """
        _UserProfile.objects.filter(user=self.user).delete()

        url = _reverse("qr:verify", kwargs={"qr_id": self.qr.pk})
        resp = self.client.get(
            url, {"t": self.qr.token}, HTTP_HOST=STAFF_HOST
        )
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "could not be verified", status_code=404)
        self.assertNotContains(
            resp, self.user.email, status_code=404,
            msg_prefix="an anonymous scan must never show an e-mail address",
        )

    def test_scan_works_while_the_profile_exists(self):
        """Passes today — pins the happy path the fix must preserve."""
        url = _reverse("qr:verify", kwargs={"qr_id": self.qr.pk})
        resp = self.client.get(
            url, {"t": self.qr.token}, HTTP_HOST=STAFF_HOST
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Robots-Tag"], "noindex")


class ScanHolderNameFallbackTests(TestCase):
    """Guards qa_500_report #4 -- display_name -> label -> honest refusal.

    Covers both scan sites: apps/qr_manager/views.py:118 (alumni) and
    :161 (staff), each now routed through _holder_name().

    The blank-named case is the state the UserProfile invariant actually
    produces (apps/user/signals.py auto-creates a profile with empty
    names), so it matters at least as much as the deleted-profile case.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.home.models import AlumniProfile

        cls.unit = ServiceUnit.objects.create(name="Fallback Unit")

        # Staff holder whose auto-created profile has never been filled in.
        cls.blank_user = User.objects.create_user(email="blank.staff@example.com")
        cls.blank_employee = Employee.objects.create(
            user=cls.blank_user,
            staff_track=Employee.StaffTrack.SERVICE,
            service_unit=cls.unit,
        )
        cls.blank_qr = QRCode.objects.create(employee=cls.blank_employee)

        # Same, but the QR carries a label identifying the holder.
        cls.labelled_user = User.objects.create_user(email="labelled@example.com")
        cls.labelled_employee = Employee.objects.create(
            user=cls.labelled_user,
            staff_track=Employee.StaffTrack.SERVICE,
            service_unit=cls.unit,
        )
        cls.labelled_qr = QRCode.objects.create(
            employee=cls.labelled_employee, label="Contractor - Achieng Otieno"
        )

        # Alumni holder, blank-named, to cover the other site.
        cls.alum_user = User.objects.create_user(email="blank.alum@example.com")
        cls.alumni = AlumniProfile.objects.create(user=cls.alum_user)
        cls.alum_qr = QRCode.objects.create(alumni_profile=cls.alumni)

    def _scan(self, qr, host):
        return self.client.get(
            _reverse("qr:verify", kwargs={"qr_id": qr.pk}),
            {"t": qr.token},
            HTTP_HOST=host,
        )

    def test_blank_named_staff_holder_is_refused(self):
        resp = self._scan(self.blank_qr, STAFF_HOST)
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "could not be verified", status_code=404)
        self.assertNotContains(resp, self.blank_user.email, status_code=404)

    def test_blank_named_alumni_holder_is_refused(self):
        """The alumni site, views.py:118 -- mounted on the apex, since an
        alumni badge encodes QR_SCAN_ORIGINS['alumni']."""
        resp = self._scan(self.alum_qr, PUBLIC_HOST)
        self.assertEqual(resp.status_code, 404)
        self.assertNotContains(resp, self.alum_user.email, status_code=404)

    def test_label_names_the_holder_when_the_profile_cannot(self):
        """Second rung: QRCode.label exists to identify a holder the
        profile does not (apps/qr_manager/models.py:115-117)."""
        resp = self._scan(self.labelled_qr, STAFF_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Contractor - Achieng Otieno")
        self.assertNotContains(resp, self.labelled_user.email)

    def test_named_holder_still_renders_the_card(self):
        """Pin -- the happy path must not regress to a refusal."""
        profile = self.blank_user.profile
        profile.given_name = "Wanjiku"
        profile.family_name = "Kamau"
        profile.save(update_fields=["given_name", "family_name"])

        resp = self._scan(self.blank_qr, STAFF_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Wanjiku Kamau")
        self.assertEqual(resp["X-Robots-Tag"], "noindex")
