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

from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase
from django.urls import NoReverseMatch, reverse


class StudentNamespaceReverseTests(SimpleTestCase):
    """Finding 2 — the 'student:' namespace does not exist.

    apps.student.urls is mounted as the ROOT URLconf for students.lvh.me
    (settings.SUBDOMAIN_URLCONFS), not via include(). A root URLconf's
    module-level `app_name` does NOT register a namespace — only
    include() does that. So apps/student/urls.py:5's

        app_name = 'student'

    is inert, and every namespaced reverse against it raises.

    Contrast apps.staff.urls, which IS reached through include()
    (apps/staff/site_urls.py:13) and therefore does register 'staff:'.
    """

    def test_student_namespace_reverses_under_its_own_urlconf(self):
        # This is the exact call shape apps/home/templatetags/
        # subdomain_urls.py:28 makes:
        #     path = reverse(view_name, urlconf=urlconf, ...)
        # with urlconf resolved from SUBDOMAIN_URLCONFS['students'].
        self.assertEqual(
            reverse("student:register", urlconf="apps.student.urls"),
            "/register/",
        )

    def test_bare_name_reverses_but_namespaced_one_does_not(self):
        """Pin -- isolates the namespace registration as the only fault.

        The bare name resolves, proving the URLconf is loaded and the
        pattern is present. Passes today; both halves must keep holding
        after a fix, with the second one inverted.
        """
        self.assertEqual(
            reverse("register", urlconf="apps.student.urls"), "/register/"
        )
        with self.assertRaises(NoReverseMatch):
            reverse("student:register", urlconf="apps.student.urls")


class SubdomainUrlTagStudentTests(SimpleTestCase):
    """Finding 2, at its real call site: the {% subdomain_url %} tag.

    apps/home/templatetags/subdomain_urls.py:28 reverses against the
    subdomain's URLconf, so any template building a cross-subdomain link
    to a students page raises NoReverseMatch — a 500 on whichever host
    rendered it, not on students.lvh.me.
    """

    def test_tag_builds_a_students_subdomain_link(self):
        request = RequestFactory().get("/", HTTP_HOST="lvh.me")
        rendered = Template(
            "{% load subdomain_urls %}"
            "{% subdomain_url 'student:register' 'students' %}"
        ).render(Context({"request": request}))
        self.assertEqual(rendered, "http://students.lvh.me/register/")


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
