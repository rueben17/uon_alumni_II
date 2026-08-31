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
# students URLconf.
# ─────────────────────────────────────────────────────────────────────

from django.conf import settings
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase
from django.urls import NoReverseMatch, reverse

from apps.student.views import StudentRegisterView


class StudentNamespaceReverseTests(SimpleTestCase):
    """Guards qa_500_report #8 -- the 'student:' namespace is registered.

    apps/student/urls.py:5 declares app_name = 'student', but that only
    registers a namespace when the module is include()d. Until
    2026-09-01 SUBDOMAIN_URLCONFS['students'] pointed straight at
    apps.student.urls, making it a ROOT urlconf, where a module-level
    app_name registers nothing -- so every 'student:' reverse raised
    NoReverseMatch.

    apps/student/site_urls.py now does the include, mirroring
    apps/staff/site_urls.py:13, and SUBDOMAIN_URLCONFS points there.
    """

    def test_student_namespace_resolves_via_the_subdomain_urlconf(self):
        """The shape apps/home/templatetags/subdomain_urls.py:28 uses --
        reverse against whatever SUBDOMAIN_URLCONFS maps the subdomain to."""
        urlconf = settings.SUBDOMAIN_URLCONFS["students"]
        self.assertEqual(urlconf, "apps.student.site_urls")
        self.assertEqual(
            reverse("student:register", urlconf=urlconf), "/register/"
        )

    def test_every_student_route_reverses_namespaced(self):
        urlconf = settings.SUBDOMAIN_URLCONFS["students"]
        for name, expected in [
            ("student:all_uon_students", "/"),
            ("student:register", "/register/"),
            ("student:evaluate_application_list", "/evaluate/"),
            ("student:applicant_dashboard", "/dashboard/"),
            ("student:analytics_export", "/dashboard/export/"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(reverse(name, urlconf=urlconf), expected)

    def test_bare_names_still_reverse_against_the_inner_module(self):
        """Pin -- four live call sites depend on this and must not break.

        apps/user/adapter.py:36 sets STUDENT_URLCONF = "apps.student.urls",
        the INNER module, and reverses a bare "register" against it at
        :333, :384 and :545; apps/home/views.py:1120 does the same. They
        survive namespacing precisely because the inner module is still
        reachable as a plain urlconf, where app_name registers nothing.
        """
        self.assertEqual(
            reverse("register", urlconf="apps.student.urls"), "/register/"
        )


class SubdomainUrlTagStudentTests(SimpleTestCase):
    """Guards qa_500_report #8 at its real call site -- the tag at
    apps/home/templatetags/subdomain_urls.py:28, which is what any
    cross-subdomain link to a students page goes through."""

    def test_tag_builds_a_students_subdomain_link(self):
        request = RequestFactory().get("/", HTTP_HOST="lvh.me")
        rendered = Template(
            "{% load subdomain_urls %}"
            "{% subdomain_url 'student:register' 'students' %}"
        ).render(Context({"request": request}))
        self.assertEqual(rendered, "http://students.lvh.me/register/")

    def test_tag_builds_a_dashboard_link(self):
        request = RequestFactory().get("/", HTTP_HOST="lvh.me")
        rendered = Template(
            "{% load subdomain_urls %}"
            "{% subdomain_url 'student:applicant_dashboard' 'students' %}"
        ).render(Context({"request": request}))
        self.assertEqual(rendered, "http://students.lvh.me/dashboard/")


class StudentRegistrationSuccessUrlTests(TestCase):
    """qa_500_report #8, the site that made namespacing risky.

    apps/student/views.py:95, StudentRegisterView.get_success_url(),
    reverses with no urlconf= -- so it resolves against request.urlconf,
    which the middleware sets to SUBDOMAIN_URLCONFS['students']. Once
    that became a namespaced include, the bare name would have raised
    NoReverseMatch on the registration success redirect: a live 500
    immediately after a student signs up.
    """

    def test_success_url_resolves_under_the_subdomain_urlconf(self):
        from django.urls import set_urlconf

        urlconf = settings.SUBDOMAIN_URLCONFS["students"]
        set_urlconf(urlconf)
        try:
            view = StudentRegisterView()
            view.request = RequestFactory().get(
                "/register/", HTTP_HOST="students.lvh.me"
            )
            view.request.session = {}
            self.assertEqual(view.get_success_url(), "/")
        finally:
            set_urlconf(None)


# ─────────────────────────────────────────────────────────────────────
# Target 6 — Postgres-specific / aggregate paths.
#
# The Phase 0 LIKE-case-sensitivity concern is DISCONFIRMED by reading:
# apps/home/views.py:1225-1226 already uses __iexact
#
#     email_ids |= set(User.objects.filter(email__iexact=email)...)
#
# which Django compiles to UPPER(...) LIKE UPPER(...) on Postgres, so it
# is case-insensitive on either backend. Phone lookups use an exact match
# against the canonical E.164 string apps/user/phone.py guarantees.
#
# What is left worth exercising is the aggregate reporting: the analytics
# and export views run Avg/Max/Count and PercentileCont (a Postgres-only
# ordered-set aggregate) over a queryset that can legitimately be empty
# before any applications exist.
# ─────────────────────────────────────────────────────────────────────

from django.contrib.auth import get_user_model as _get_user_model

_User = _get_user_model()

STUDENTS_HOST = "students.lvh.me"


class ScholarshipAnalyticsEmptyDatasetTests(TestCase):
    """No ScholarshipApplication rows yet — the state every fresh
    deployment is in, and the state the association is in between
    intake rounds."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _User.objects.create_superuser(
            email="analytics.admin@example.com", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_applicant_dashboard_renders_with_no_applications(self):
        resp = self.client.get("/dashboard/", HTTP_HOST=STUDENTS_HOST)
        self.assertLess(resp.status_code, 500)

    def test_analytics_export_builds_with_no_applications(self):
        resp = self.client.get("/dashboard/export/", HTTP_HOST=STUDENTS_HOST)
        self.assertLess(resp.status_code, 500)

    def test_evaluate_list_renders_with_no_applications(self):
        resp = self.client.get("/evaluate/", HTTP_HOST=STUDENTS_HOST)
        self.assertLess(resp.status_code, 500)
