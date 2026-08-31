from django.test import TestCase

# Create your tests here.


# ─────────────────────────────────────────────────────────────────────
# QA 500 sweep (Phase 1, 2026-08-31) — reproduction tests.
#
# These tests are EXPECTED TO FAIL on the current tree. Each one asserts
# the behaviour the route should have; the failure is the bug report.
# See qa_500_report.md at the repo root for the diagnosis of each.
#
# Every test names an explicit HTTP_HOST from the lvh.me family. Under
# test, settings.py's DEBUG branches have already run at import, so
# SUBDOMAIN_DOMAIN is 'lvh.me' — the test client's default 'testserver'
# host falls through SubdomainRoutingMiddleware's else-branch to
# subdomain=None and would silently exercise main.urls instead of the
# staff URLconf.
# ─────────────────────────────────────────────────────────────────────

from django.contrib.auth import get_user_model
from django.urls import NoReverseMatch, reverse

User = get_user_model()


from apps.staff.models import Employee, ServiceUnit
from apps.user.models import UserProfile

PUBLIC_HOST = "lvh.me"
STAFF_HOST = "staff.lvh.me"
# Matches SubdomainRoutingMiddleware's '.lvh.me' wildcard, so it is an
# allowed host, but is NOT a key in SUBDOMAIN_URLCONFS -- so it routes to
# main.urls while still containing the substring 'staff'.
STAFF_LOOKALIKE_HOST = "mystaff.lvh.me"


def _make_user(email, **extra):
    user = User.objects.create_user(email=email, **extra)
    UserProfile.objects.create(user=user, given_name="Test", family_name="Person")
    return user


class StaffNamespaceReverseTests(TestCase):
    """Pins for where the 'staff:' namespace is and is not reachable.

    The 2026-08-18 SEO audit replaced main/urls.py's
    include('apps.staff.urls') with a redirect (main/urls.py:82), so
    'staff:' is no longer registered under main.urls. That is
    deliberate -- cross-host links are meant to go through
    {% subdomain_url %} (apps/home/templatetags/subdomain_urls.py:28),
    which reverses against the target subdomain's own URLconf.

    All three pass today. They record where reversing works so the
    navbar finding below is unambiguous about its cause.
    """

    def test_staff_namespace_resolves_on_its_own_subdomain(self):
        self.assertEqual(
            reverse("staff:profile_update", urlconf="apps.staff.site_urls"),
            "/profile/edit/",
        )

    def test_staff_namespace_absent_from_public_urlconf(self):
        with self.assertRaises(NoReverseMatch):
            reverse("staff:profile_update", urlconf="main.urls")

    def test_staff_namespace_absent_from_students_urlconf(self):
        with self.assertRaises(NoReverseMatch):
            reverse("staff:profile_update", urlconf="apps.student.urls")


class NavbarStaffHostGuardTests(TestCase):
    """Guards qa_500_report #7 -- navbar staff links are host-independent.

    templates/snippets/navbar.html:34 and :314 used to reverse the staff
    namespace bare:

        <a href="{% url 'staff:profile_update' %}"

    inside a guard that is a SUBSTRING test (navbar.html:17, :301):

        {% if 'staff' in host %}

    ALLOWED_HOSTS admits the whole '.lvh.me' wildcard in development and
    '.uonalumni.or.ke' in production (settings.py:77-81), while
    SUBDOMAIN_URLCONFS maps only the exact keys 'staff' and 'students'
    (settings.py:423-428). So a host merely CONTAINING 'staff' rendered
    the block while SubdomainRoutingMiddleware routed the request to
    main.urls, where the 'staff:' namespace does not exist -- a
    NoReverseMatch, i.e. a 500.

    Both links now use {% subdomain_url ... 'staff' %}, which reverses
    against apps.staff.site_urls whatever host rendered the page -- the
    same tag the file already loads at :2 and uses at :218 and :439.
    The substring guard is left as it is: it no longer has a 500 behind
    it, and tightening it would change what renders on the two sibling
    'staff' not in host blocks at :231 and :452 too.
    """

    @classmethod
    def setUpTestData(cls):
        cls.employee_user = _make_user("navbar.employee@example.com")
        unit = ServiceUnit.objects.create(name="Navbar Unit")
        Employee.objects.create(
            user=cls.employee_user,
            staff_track=Employee.StaffTrack.SERVICE,
            service_unit=unit,
        )

    def test_staff_lookalike_host_renders_an_absolute_staff_link(self):
        """The reproduction, flipped: this host routes to main.urls, so a
        bare 'staff:' reverse would raise. It must now render, and the
        link must point at the staff subdomain rather than this host."""
        self.client.force_login(self.employee_user)
        resp = self.client.get("/", HTTP_HOST=STAFF_LOOKALIKE_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "http://staff.lvh.me/profile/edit/")

    def test_public_host_is_unaffected_for_an_employee(self):
        """Pin -- the outer guard does its job on the real public host."""
        self.client.force_login(self.employee_user)
        resp = self.client.get("/", HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 200)

    def test_staff_host_is_unaffected_for_an_employee(self):
        """Pin -- on the staff subdomain the reverse genuinely resolves."""
        self.client.force_login(self.employee_user)
        resp = self.client.get("/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 200)


# ─────────────────────────────────────────────────────────────────────
# Target 1 (the staff mis-gating cluster) — DISCONFIRMED as a 500 source.
#
# The Phase 0 hypothesis was that these views resolve request.user.employee
# and therefore 500 for an authenticated non-employee whose session
# crossed over from the public host (SESSION_COOKIE_DOMAIN spans all
# subdomains). Reading the bodies shows every one of them fails CLOSED
# with a 404 instead:
#
#   apps/staff/views.py:258  CompleteProfileView.get_queryset
#       return Employee.objects.filter(user=self.request.user)
#       -> empty queryset -> UpdateView.get_object() raises Http404
#
#   apps/staff/views.py:281  ProfileUpdateView.get_object
#       return get_object_or_404(Employee, user=self.request.user)
#
#   apps/staff/views.py:303  ProfileDeleteView.get
#   apps/staff/views.py:307  ProfileDeleteView.post
#       employee = get_object_or_404(Employee, user=request.user)
#
#   apps/staff/views.py:407  download_staff_qr_code
#       employee = get_object_or_404(Employee, slug=staff_slug, id=pk)
#       then an explicit owner-or-admin check returning 404.
#
# So the gating is wrong in KIND (404 where the employee_required pair
# gives 403, and LoginRequiredMixin where EmployeeRequiredMixin belongs)
# but it does not leak and does not 500. These tests PASS today and are
# here to pin that, so a later re-gating cannot quietly turn a 404 into
# a 500 or a 200.
# ─────────────────────────────────────────────────────────────────────


class StaffEmployeeGatingTests(TestCase):
    """Guards qa_500_report target 1 -- staff views gate on employee record.

    SESSION_COOKIE_DOMAIN spans every subdomain, so an alumnus logged in
    on the public host carries that session onto staff.lvh.me and passes
    a bare LoginRequiredMixin. These three views previously carried one,
    and fell back on get_object_or_404 to fail closed -- safe, but a 404
    that says "no such page" where the truth is "you are not staff".

    They now use EmployeeRequiredMixin, the same gate EmployeeListView
    and EmployeeDetailView already use: anonymous -> 302 to login,
    authenticated non-employee -> 403.

    download_staff_qr_code is deliberately NOT included. apps/staff/
    views.py:409-418 documents that it must serve admins who are not
    employees ("admins need to fetch any employee's badge, not just
    their own"), so employee-gating it would remove a capability the
    owner-or-admin check below it grants on purpose.
    """

    @classmethod
    def setUpTestData(cls):
        cls.alumnus = _make_user("alumna@example.com")

    def setUp(self):
        self.client.force_login(self.alumnus)

    def test_profile_edit_forbids_a_non_employee(self):
        resp = self.client.get("/profile/edit/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 403)

    def test_profile_delete_forbids_a_non_employee(self):
        resp = self.client.get("/profile/delete/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 403)

    def test_profile_delete_post_forbids_a_non_employee(self):
        resp = self.client.post("/profile/delete/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 403)

    def test_complete_profile_forbids_a_non_employee(self):
        import uuid as _uuid
        resp = self.client.get(
            f"/complete-profile/{_uuid.uuid4()}/", HTTP_HOST=STAFF_HOST
        )
        self.assertEqual(resp.status_code, 403)

    def test_employee_only_directory_forbids_a_non_employee(self):
        resp = self.client.get("/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get("/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 302)

    def test_qr_download_still_reachable_by_a_non_employee_admin(self):
        """Pin -- the deliberate exception. An admin with no Employee
        record must still reach the badge route rather than be blocked
        by a gate; 404 here is the owner-or-admin check finding no such
        employee, which is the intended existence-hiding response."""
        admin = User.objects.create_superuser(
            email="badge.admin@example.com", password="x"
        )
        UserProfile.objects.create(
            user=admin, given_name="Badge", family_name="Admin"
        )
        self.client.force_login(admin)
        import uuid as _uuid
        resp = self.client.get(
            f"/someone/{_uuid.uuid4()}/download-qr/", HTTP_HOST=STAFF_HOST
        )
        self.assertEqual(resp.status_code, 404)
