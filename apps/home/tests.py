from django.test import TestCase

# Create your tests here.


# ─────────────────────────────────────────────────────────────────────
# QA 500 sweep (Phase 1, 2026-08-31) — reproduction tests.
#
# These tests are EXPECTED TO FAIL on the current tree. Each one asserts
# the behaviour the route or helper should have; the failure is the bug
# report. See qa_500_report.md at the repo root for the diagnosis.
#
# Every request-level test names an explicit HTTP_HOST from the lvh.me
# family. Under test, settings.py's DEBUG branches have already run at
# import, so SUBDOMAIN_DOMAIN is 'lvh.me' — the client default
# 'testserver' falls through SubdomainRoutingMiddleware's else-branch to
# subdomain=None, which would quietly test a different URLconf than the
# one a finding is about.
# ─────────────────────────────────────────────────────────────────────

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from apps.home.models import AlumniProfile, Membership, MembershipTier
from apps.home.services import renew_membership
from apps.user.models import UserProfile

User = get_user_model()

PUBLIC_HOST = "lvh.me"


def _make_user(email, **extra):
    """A user WITH a UserProfile — the state social login leaves behind.

    apps/user/adapter.py:111 is the only routine path that creates one:
        profile, created = UserProfile.objects.get_or_create(...)
    Nothing in UserManager does, so this has to be explicit here.
    """
    user = User.objects.create_user(email=email, **extra)
    UserProfile.objects.create(
        user=user, given_name="Test", family_name="Alumna"
    )
    return user


class CurrentForStatusTests(TestCase):
    """Finding 5 (Tier B) — current_for() ignores status.

    apps/home/models.py:1373-1381:

        class MembershipManager(models.Manager):
            def current_for(self, user):
                return self.filter(user=user).first()

    with Membership.Meta.ordering = ["-created_at"] (models.py:1500-1501).
    No status filter at all, so the newest row wins even when it is a
    PENDING renewal sitting behind a still-valid ACTIVE membership.

    apps/qr_manager/views.py:64-66 already works around this by querying
    status=ACTIVE directly; the other six call sites do not.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _make_user("member@example.com")
        cls.gold = MembershipTier.objects.create(
            name="Gold Life Member", fee=100000, tier_type="life",
            duration_months=0,
        )
        cls.student = MembershipTier.objects.create(
            name="Student Annual Membership", fee=500, tier_type="annual",
            duration_months=12,
        )
        # The real-world shape: a valid ACTIVE membership, and a renewal
        # request raised afterwards that nobody has confirmed yet.
        cls.active = Membership.objects.create(
            user=cls.user, tier=cls.gold, status=Membership.Status.ACTIVE,
            is_lifetime=True,
        )
        cls.pending = Membership.objects.create(
            user=cls.user, tier=cls.student,
            status=Membership.Status.PENDING,
        )

    def test_current_for_prefers_the_active_membership(self):
        """The member IS currently a Gold Life Member. Their unconfirmed
        renewal request must not displace that."""
        self.assertEqual(
            Membership.objects.current_for(self.user), self.active
        )

    def test_qr_manager_status_filtered_lookup_stays_correct(self):
        """Pins apps/qr_manager/views.py:64-66's workaround.

        Passes today. Here so that a fix to current_for() is not made by
        weakening the one call site that already gets this right.
        """
        found = (
            Membership.objects
            .filter(user=self.user, status=Membership.Status.ACTIVE)
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(found, self.active)


class RenewMembershipTierTests(TestCase):
    """Finding 5, consequence — renew_membership() renews the wrong tier.

    apps/home/services.py:114:

        current = Membership.objects.current_for(user)

    then services.py:117 renews at `current.tier`. With a pending
    downgrade/renewal newer than the ACTIVE row, a Gold Life Member who
    asks to renew is silently renewed as a Student Annual Member.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _make_user("renewer@example.com")
        cls.gold = MembershipTier.objects.create(
            name="Gold Life Member", fee=100000, tier_type="life",
            duration_months=0,
        )
        cls.student = MembershipTier.objects.create(
            name="Student Annual Membership", fee=500, tier_type="annual",
            duration_months=12,
        )
        Membership.objects.create(
            user=cls.user, tier=cls.gold, status=Membership.Status.ACTIVE,
            is_lifetime=True,
        )
        Membership.objects.create(
            user=cls.user, tier=cls.student,
            status=Membership.Status.PENDING,
        )

    def test_renewal_uses_the_active_tier(self):
        renewed = renew_membership(self.user)
        self.assertEqual(renewed.tier, self.gold)


class MissingUserProfileTests(TestCase):
    """Finding 6 — nothing guarantees a User has a UserProfile.

    UserProfile is created in exactly two places: apps/user/adapter.py:111
    (social login) and the import_legacy_memberships command
    (apps/home/management/commands/import_legacy_memberships.py:214).
    UserManager.create_user/create_superuser (apps/user/models.py:25-47)
    do NOT, so every account made by `manage.py createsuperuser` or in
    the Django admin lacks one.

    Several admin call sites already defend against this — e.g.
    apps/home/admin.py:80:

        return obj.user.profile.display_name if hasattr(obj.user, 'profile') else ''

    but the slug helpers and the view/PDF paths do not.
    """

    @classmethod
    def setUpTestData(cls):
        # Exactly what `manage.py createsuperuser` produces.
        cls.profileless = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )

    def test_created_superuser_has_no_profile(self):
        """Not a bug in itself — the precondition for the two below.
        Passes today; documents why they fail."""
        self.assertFalse(hasattr(self.profileless, "profile"))

    def test_alumni_profile_can_be_created_for_a_profileless_user(self):
        """apps/home/models.py:1089-1092:

            def get_alumni_profile_slug(instance):
                profile = instance.user.profile
                return slugify(...)

        AlumniProfile.slug is an AutoSlugField populated from that, so
        the read happens on save() with nothing guarding it. Creating an
        AlumniProfile for a hand-made User raises instead of saving —
        a 500 on the Django admin's add-AlumniProfile form.
        """
        profile = AlumniProfile.objects.create(user=self.profileless)
        self.assertIsNotNone(profile.pk)

    def test_profile_access_raises_object_does_not_exist(self):
        """Captures the exact exception type the call sites propagate.

        Passes today. Pins what the unguarded `user.profile` reads at
        apps/home/views.py:672 and :697, apps/staff/views.py:424 and
        :436, and apps/qr_manager/views.py:90 and :133 will raise.
        """
        with self.assertRaises(ObjectDoesNotExist):
            self.profileless.profile


class AlumniProfileDetailAccessTests(TestCase):
    """Finding 7 — AlumniProfileDetailView is ungated.

    apps/home/views.py:515:

        class AlumniProfileDetailView(DetailView):

    No LoginRequiredMixin, no owner check. get_context_data
    (views.py:537-541) attaches current_membership and the alumnus's
    non-primary EmailAddress, and the template carries payment history.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _make_user("alum@example.com")
        cls.alumni = AlumniProfile.objects.create(user=cls.user)

    def _url(self):
        return reverse(
            "home:alumni_detail",
            kwargs={"slug": self.alumni.slug, "pk": self.alumni.pk},
        )

    def test_anonymous_visitor_cannot_read_a_members_profile(self):
        """An anonymous GET should not return a member's profile page."""
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertNotEqual(
            resp.status_code, 200,
            "AlumniProfileDetailView served a member's profile, including "
            "membership standing and alternate e-mail, to an anonymous "
            "visitor.",
        )


# ─────────────────────────────────────────────────────────────────────
# Auth x host matrix sweep.
#
# Walks every argument-free route on each host under each auth state and
# flags anything that returns 5xx. Uses subTest so ONE run reports every
# broken cell rather than stopping at the first.
#
# Hosts come from the lvh.me family deliberately: SUBDOMAIN_DOMAIN is
# 'lvh.me' under test, so 'staff.lvh.me' is what actually routes to
# apps.staff.site_urls. Using the client default would test main.urls
# three times over and report a clean sweep that proved nothing.
# ─────────────────────────────────────────────────────────────────────

from apps.staff.models import Employee, ServiceUnit

STAFF_HOST = "staff.lvh.me"
STUDENTS_HOST = "students.lvh.me"

# (host, path) — argument-free routes only; parameterised ones are
# covered by the targeted tests above.
PUBLIC_PATHS = [
    "/",
    "/uon-alumni-history/",
    "/uon-alumni-executive-committee/",
    "/uon-alumni-gallery/",
    "/uon-alumni-membership-categories/",
    "/uon-alumni-donate/",
    "/uon-alumni-scholarship/",
    "/uon-alumni-in-memoriam/",
    "/uon-alumni-contact-us/",
    "/uon-alumni-claim-profile/",
    "/uon-alumni-news/",
    "/uon-alumni-walk/",
    "/uon-alumni-chapters/",
    "/uon-alumni-secretariat/",
    "/uon-alumni-partners/",
    "/uon-alumni-mission-vision/",
    "/uon-alumni-downloads/",
    "/uon-alumni-careers/",
    "/uon-alumni-membership-analytics/",
    "/sitemap.xml",
    "/robots.txt",
]

STAFF_PATHS = ["/robots.txt", "/", "/login/", "/dashboard/", "/profile/edit/"]

STUDENT_PATHS = [
    "/robots.txt", "/", "/register/", "/evaluate/", "/dashboard/",
]


class AuthHostMatrixSweepTests(TestCase):
    """No 5xx anywhere in the matrix."""

    @classmethod
    def setUpTestData(cls):
        cls.anonymous = None

        cls.plain = _make_user("matrix.plain@example.com")

        cls.employee_user = _make_user("matrix.employee@example.com")
        unit = ServiceUnit.objects.create(name="Matrix Unit")
        Employee.objects.create(
            user=cls.employee_user,
            staff_track=Employee.StaffTrack.SERVICE,
            service_unit=unit,
        )

        cls.superuser = User.objects.create_superuser(
            email="matrix.super@example.com", password="x"
        )
        UserProfile.objects.create(
            user=cls.superuser, given_name="Matrix", family_name="Super"
        )

    def _sweep(self, host, paths):
        states = [
            ("anonymous", None),
            ("authenticated-non-employee", self.plain),
            ("employee", self.employee_user),
            ("superuser", self.superuser),
        ]
        for label, user in states:
            for path in paths:
                with self.subTest(host=host, auth=label, path=path):
                    self.client.logout()
                    if user is not None:
                        self.client.force_login(user)
                    resp = self.client.get(path, HTTP_HOST=host)
                    self.assertLess(
                        resp.status_code, 500,
                        f"{label} GET {path} on {host} -> "
                        f"{resp.status_code}",
                    )

    def test_public_host_matrix(self):
        self._sweep(PUBLIC_HOST, PUBLIC_PATHS)

    def test_staff_host_matrix(self):
        self._sweep(STAFF_HOST, STAFF_PATHS)

    def test_students_host_matrix(self):
        self._sweep(STUDENTS_HOST, STUDENT_PATHS)
