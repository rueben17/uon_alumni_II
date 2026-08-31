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
    """Reproduction -- navbar.html's host guard is a substring test.

    templates/snippets/navbar.html:34 and :314 reverse the staff
    namespace WITHOUT the subdomain_url tag:

        <a href="{% url 'staff:profile_update' %}"

    Each sits inside this nesting (navbar.html:4, :17, :21, :29):

        {% with host=request.get_host %}
          {% if 'staff' in host %}
            {% if request.user.is_authenticated %}
              {% if request.user.employee %}

    On lvh.me the outer guard is False, so the public site is safe --
    confirmed by AuthHostMatrixSweepTests in apps/home/tests.py, which
    sweeps an employee across every public route without a 5xx. On
    staff.lvh.me the guard is True and 'staff:' resolves, so that host
    is fine too.

    The gap is that `'staff' in host` is a SUBSTRING test, not a
    subdomain test. ALLOWED_HOSTS admits the whole '.lvh.me' wildcard in
    dev and '.uonalumni.or.ke' in production (settings.py:77-81), while
    SUBDOMAIN_URLCONFS maps only the exact keys 'staff' and 'students'.
    Any other host containing 'staff' renders the block while
    SubdomainRoutingMiddleware routes the request to main.urls, where
    'staff:' does not exist.
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

    def test_staff_lookalike_host_does_not_500_for_an_employee(self):
        self.client.force_login(self.employee_user)
        resp = self.client.get("/", HTTP_HOST=STAFF_LOOKALIKE_HOST)
        self.assertLess(
            resp.status_code, 500,
            "navbar.html rendered its staff block on a host that routes "
            "to main.urls, where the 'staff:' namespace does not exist.",
        )

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


class StaffMisGatingDoesNotLeakTests(TestCase):
    """Authenticated NON-employee, session shared onto staff.lvh.me."""

    @classmethod
    def setUpTestData(cls):
        cls.alumnus = _make_user("alumna@example.com")

    def setUp(self):
        self.client.force_login(self.alumnus)

    def test_profile_edit_denies_a_non_employee(self):
        resp = self.client.get("/profile/edit/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 404)

    def test_profile_delete_denies_a_non_employee(self):
        resp = self.client.get("/profile/delete/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 404)

    def test_profile_delete_post_denies_a_non_employee(self):
        resp = self.client.post("/profile/delete/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 404)

    def test_employee_only_directory_still_403s_a_non_employee(self):
        """EmployeeRequiredMixin's documented behaviour, for contrast:
        authenticated-but-failing gets 403, not 404. This is the shape
        the four views above should have."""
        resp = self.client.get("/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get("/", HTTP_HOST=STAFF_HOST)
        self.assertEqual(resp.status_code, 302)
