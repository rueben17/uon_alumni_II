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


# ─────────────────────────────────────────────────────────────────────
# Coverage priority 6 -- QR badge GENERATION.
#
# Scan verification is already covered by the QA-500 sweep; this is the
# minting path: generate_qr, _qr_watermark_image, and the lost-badge
# levers. See docs/coverage-phase1-qrgen-step1-2026-09-02.md.
#
# The module-level temp MEDIA_ROOT above is reused -- these tests write
# real PNGs through ImageField.save(). Finding L means default_storage
# is FileSystemStorage, not Cloudinary, so there is no live-call risk
# and no mocking is needed for the writes.
#
# Model-level throughout, except the three that scan through the view
# to prove real invalidation -- those carry an lvh.me-family host.
# ─────────────────────────────────────────────────────────────────────

from io import BytesIO
from pathlib import Path
from unittest import mock as _mock

from django.core.files.uploadedfile import SimpleUploadedFile as _QrUpload

from apps.home.models import AlumniProfile, Banner

_DEV_ORIGINS = {
    "staff": "http://staff.lvh.me:8000",
    "alumni": "http://www.lvh.me:8000",
}
_PROD_ORIGINS = {
    "staff": "https://staff.uonalumni.or.ke",
    "alumni": "https://www.uonalumni.or.ke",
}


def _qr_png(colour="black", size=(24, 24)):
    """A genuinely decodable PNG.

    ResizedImageField and PIL both read the bytes back, so a hand-rolled
    blob fails here -- the same lesson the QR-badge PDF pass learned.
    """
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


def _qr_user(email):
    user = User.objects.create_user(email=email)
    _name_profile(user, "Badge", "Holder")
    return user


def _qr_employee(email="gen.staff@example.com"):
    user = _qr_user(email)
    unit = ServiceUnit.objects.create(name=f"Unit {user.pk}")
    return Employee.objects.create(
        user=user, staff_track=Employee.StaffTrack.SERVICE, service_unit=unit
    )


def _qr_alumni(email="gen.alumna@example.com"):
    return AlumniProfile.objects.create(user=_qr_user(email))


# ── generate_qr (8) ──────────────────────────────────────────────────


class GenerateQrTests(TestCase):
    """apps/qr_manager/models.py:224-301."""

    def test_a_holderless_code_generates_nothing(self):
        code = QRCode.objects.create(label="Visitor pass")
        self.assertIsNone(code.holder)

        self.assertIsNone(code.generate_qr())

    def test_a_badge_is_written_and_its_url_returned(self):
        employee = _qr_employee()
        code = QRCode.objects.create(employee=employee)

        url = code.generate_qr()

        employee.refresh_from_db()
        self.assertTrue(employee.qr_code_image)
        self.assertTrue(url)
        self.assertTrue(employee.qr_code_image.storage.exists(employee.qr_code_image.name))

    def test_the_filename_is_the_holder_uuid_not_the_slug(self):
        """models.py:298 -- slugs are mutable and would orphan printed
        badges; the UUID is stable."""
        employee = _qr_employee()
        code = QRCode.objects.create(employee=employee)

        code.generate_qr()

        employee.refresh_from_db()
        self.assertIn(str(employee.pk), employee.qr_code_image.name)
        self.assertTrue(employee.qr_code_image.name.endswith(".png"))

    @override_settings(QR_SCAN_ORIGINS=_PROD_ORIGINS)
    def test_the_encoded_origin_follows_the_holder_type(self):
        """FINDING N, current behaviour.

        scan_url reads settings.QR_SCAN_ORIGINS at CALL time, so
        whatever origin is configured when a badge is minted is baked
        into the printed artefact permanently. A staff badge must never
        read "www." and an alumni badge must never read "staff.".
        """
        staff_code = QRCode.objects.create(employee=_qr_employee())
        alumni_code = QRCode.objects.create(alumni_profile=_qr_alumni())

        self.assertTrue(staff_code.scan_url.startswith("https://staff.uonalumni.or.ke/qr/"))
        self.assertTrue(alumni_code.scan_url.startswith("https://www.uonalumni.or.ke/qr/"))

        # A holder-less code falls back to the alumni origin (models.py:218).
        bare = QRCode.objects.create(label="Event pass")
        self.assertTrue(bare.scan_url.startswith("https://www.uonalumni.or.ke/qr/"))

    @override_settings(QR_SCAN_ORIGINS=_DEV_ORIGINS)
    def test_a_badge_minted_in_dev_encodes_the_dev_origin(self):
        """FINDING N, the other half: nothing in generate_qr validates
        that the configured origin looks like production, so a badge
        minted with DEBUG settings carries lvh.me onto paper. Only the
        deploy-day regenerate step catches it, and that is a human
        process."""
        code = QRCode.objects.create(employee=_qr_employee())

        self.assertIn("lvh.me:8000", code.scan_url)
        self.assertIn(f"/qr/{code.id}/", code.scan_url)

    def test_the_encoded_url_carries_the_current_token(self):
        code = QRCode.objects.create(employee=_qr_employee())
        self.assertIn(f"?t={code.token}", code.scan_url)

    def test_an_existing_badge_is_not_regenerated_without_force(self):
        """models.py:248-249 -- the early return. The deploy-day
        regenerate depends entirely on someone passing force=True."""
        employee = _qr_employee()
        code = QRCode.objects.create(employee=employee)
        code.generate_qr()
        employee.refresh_from_db()
        first_name = employee.qr_code_image.name

        code.rotate_token()
        code.generate_qr()

        employee.refresh_from_db()
        self.assertEqual(employee.qr_code_image.name, first_name)

    def test_force_regenerates_after_a_token_rotation(self):
        employee = _qr_employee()
        code = QRCode.objects.create(employee=employee)
        code.generate_qr()
        old_token = code.token

        code.rotate_token()
        self.assertNotEqual(code.token, old_token)
        code.generate_qr(force=True)

        employee.refresh_from_db()
        self.assertTrue(employee.qr_code_image)
        self.assertIn(f"?t={code.token}", code.scan_url)

    def test_save_holder_false_leaves_the_holder_unsaved(self):
        employee = _qr_employee()
        code = QRCode.objects.create(employee=employee)

        code.generate_qr(save_holder=False)

        # In memory the field is set; the row is not updated.
        self.assertTrue(employee.qr_code_image)
        self.assertFalse(Employee.objects.get(pk=employee.pk).qr_code_image)


# ── _qr_watermark_image (4) ──────────────────────────────────────────


class QrWatermarkTests(TestCase):
    """apps/qr_manager/models.py:20-60."""

    def _banner(self, **fields):
        banner = Banner.objects.create()
        for name, colour in fields.items():
            getattr(banner, name).save(
                f"{name}.png", _QrUpload(f"{name}.png", _qr_png(colour)), save=True
            )
        return banner

    def test_an_admin_uploaded_watermark_is_used(self):
        from apps.qr_manager.models import _qr_watermark_image

        self._banner(staff_qr_watermark="red")

        image = _qr_watermark_image(is_alumni=False)

        self.assertIsNotNone(image)
        self.assertEqual(image.mode, "RGBA")

    def test_alumni_and_staff_select_different_fields(self):
        """models.py:29 -- two distinct institutional marks, not one
        generic logo."""
        from apps.qr_manager.models import _qr_watermark_image

        self._banner(staff_qr_watermark="red")

        # The staff field is set, so the staff branch finds a Banner image.
        self.assertIsNotNone(_qr_watermark_image(is_alumni=False))
        # The alumni field is unset on that same Banner, so the alumni
        # branch falls through to the static crest instead.
        alumni_image = _qr_watermark_image(is_alumni=True)
        self.assertIsNotNone(alumni_image)

    def test_it_falls_back_to_the_static_crest(self):
        from apps.qr_manager.models import _qr_watermark_image

        self.assertFalse(Banner.objects.exists())

        self.assertIsNotNone(_qr_watermark_image(is_alumni=False))
        self.assertIsNotNone(_qr_watermark_image(is_alumni=True))

    def test_it_returns_none_when_neither_source_exists(self):
        """models.py:60 -- the real branch, not a mock. BASE_DIR is read
        at call time, so pointing it at an empty directory removes the
        static fallback."""
        from apps.qr_manager.models import _qr_watermark_image

        self.assertFalse(Banner.objects.exists())
        empty = tempfile.mkdtemp(prefix="qr_no_static_")
        self.addCleanup(shutil.rmtree, empty, True)

        with override_settings(BASE_DIR=Path(empty)):
            self.assertIsNone(_qr_watermark_image(is_alumni=False))
            self.assertIsNone(_qr_watermark_image(is_alumni=True))

    def test_a_badge_is_still_generated_with_no_watermark_at_all(self):
        """models.py:60 returns None when neither a Banner nor the static
        file exists, and generate_qr then simply skips the paste -- a
        silent, unwatermarked badge rather than an error."""
        employee = _qr_employee()
        code = QRCode.objects.create(employee=employee)

        with _mock.patch(
            "apps.qr_manager.models._qr_watermark_image", return_value=None
        ) as patched:
            url = code.generate_qr()

        patched.assert_called_once()
        employee.refresh_from_db()
        self.assertTrue(url)
        self.assertTrue(employee.qr_code_image)


# ── rotate_token / revoke / delete (5) ───────────────────────────────


class LostBadgeLeverTests(TestCase):
    """models.py:189-200 and :304-312.

    The two lost-badge levers do NOT behave alike, and that asymmetry is
    finding M.
    """

    def setUp(self):
        self.employee = _qr_employee("lever@example.com")
        self.code = QRCode.objects.create(employee=self.employee)

    def _scan(self, token):
        return self.client.get(
            _reverse("qr:verify", kwargs={"qr_id": self.code.pk}),
            {"t": token},
            HTTP_HOST=STAFF_HOST,
        )

    def test_rotate_token_invalidates_every_printed_copy(self):
        """The lever that actually works: verify_scan compares the
        supplied token with secrets.compare_digest, so an old printed
        badge fails."""
        old_token = self.code.token
        self.assertEqual(self._scan(old_token).status_code, 200)

        self.code.rotate_token()

        self.assertEqual(self._scan(old_token).status_code, 403)
        self.assertEqual(self._scan(self.code.token).status_code, 200)

    def test_rotate_token_does_not_regenerate_the_stored_badge(self):
        """FINDING M, second half. The docstring says "Regenerate +
        reprint afterwards" -- a manual step with nothing enforcing it,
        so the stored image keeps encoding the old token until someone
        acts."""
        self.code.generate_qr()
        old_token = self.code.token

        self.code.rotate_token()

        self.employee.refresh_from_db()
        # The image file is untouched by the rotation...
        self.assertTrue(self.employee.qr_code_image)
        # ...while scan_url has already moved on to the new token.
        self.assertIn(f"?t={self.code.token}", self.code.scan_url)
        self.assertNotEqual(self.code.token, old_token)

    def test_finding_m_revoke_does_not_block_a_scan(self):
        """FINDING M, asserted as CURRENT behaviour.

        revoke() flips is_active, and QRCode.status duly reports
        REVOKED -- but verify_scan never consults is_valid or is_active
        (its docstring says validity enforcement is "deferred by
        design"). So a revoked badge still renders a normal
        verification card; only the ScanLog line changes.
        """
        self.code.revoke()
        self.code.refresh_from_db()
        self.assertFalse(self.code.is_active)
        self.assertEqual(self.code.status, "REVOKED")

        response = self._scan(self.code.token)

        # Still a rendered card, not a refusal.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ScanLog.objects.filter(qrcode=self.code).latest("scanned_at").result,
            "REVOKED",
        )

    def test_delete_clears_the_holders_badge_image(self):
        """models.py:304-312 -- otherwise the profile page keeps showing
        a badge that no longer exists and scans UNKNOWN."""
        self.code.generate_qr()
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.qr_code_image)

        self.code.delete()

        self.employee.refresh_from_db()
        self.assertFalse(self.employee.qr_code_image)
        self.assertFalse(QRCode.objects.filter(pk=self.code.pk).exists())

    def test_deleting_a_holderless_code_does_not_raise(self):
        bare = QRCode.objects.create(label="Guest")
        bare.delete()
        self.assertFalse(QRCode.objects.filter(pk=bare.pk).exists())


# ── Supervisor (1, with subTests) ────────────────────────────────────


class SupervisorUnitTests(TestCase):
    """models.py:392-422."""

    def setUp(self):
        self.user = _qr_user("supervisor@example.com")
        self.unit = ServiceUnit.objects.create(name="Registry")

    def test_unit_selection_validation_and_query_building(self):
        from django.core.exceptions import ValidationError

        role = Supervisor.objects.create(user=self.user, service_unit=self.unit)

        with self.subTest("unit picks the one that is set"):
            self.assertEqual(role.unit, self.unit)

        with self.subTest("clean accepts exactly one"):
            role.clean()

        with self.subTest("clean rejects none"):
            with self.assertRaises(ValidationError):
                Supervisor(user=self.user).clean()

        with self.subTest("__str__ names the unit"):
            self.assertIn("Registry", str(role))

        with self.subTest("unit_q_for matches the supervised unit"):
            employee = _qr_employee("sup.emp@example.com")
            employee.service_unit = self.unit
            employee.save(update_fields=["service_unit"])
            q = Supervisor.unit_q_for(self.user)
            self.assertIn(employee, Employee.objects.filter(q))

        with self.subTest("unit_q_for prefixes for QRCode querysets"):
            code = QRCode.objects.create(employee=employee)
            q = Supervisor.unit_q_for(self.user, prefix="employee__")
            self.assertIn(code, QRCode.objects.filter(q))

        with self.subTest("unit_q_for handles a department supervisor"):
            from apps.home.models import Department, Faculty

            dept_user = _qr_user("dept.sup@example.com")
            faculty = Faculty.objects.create(faculty_name="Engineering")
            department = Department.objects.create(name="Civil", faculty=faculty)
            Supervisor.objects.create(user=dept_user, department=department)
            dept_emp = _qr_employee("dept.emp@example.com")
            dept_emp.staff_track = Employee.StaffTrack.TEACHING
            dept_emp.service_unit = None
            dept_emp.department = department
            dept_emp.save()
            self.assertIn(
                dept_emp, Employee.objects.filter(Supervisor.unit_q_for(dept_user))
            )

        with self.subTest("unit_q_for handles a research-unit supervisor"):
            from apps.staff.models import ResearchUnit

            res_user = _qr_user("res.sup@example.com")
            research = ResearchUnit.objects.create(name="Climate Lab")
            Supervisor.objects.create(user=res_user, research_unit=research)
            res_emp = _qr_employee("res.emp@example.com")
            res_emp.staff_track = Employee.StaffTrack.RESEARCH
            res_emp.service_unit = None
            res_emp.research_unit = research
            res_emp.save()
            self.assertIn(
                res_emp, Employee.objects.filter(Supervisor.unit_q_for(res_user))
            )

        with self.subTest("a non-supervisor matches nothing"):
            outsider = _qr_user("outsider@example.com")
            self.assertIs(Supervisor.unit_q_for(outsider), False)
