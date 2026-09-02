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
    # The post_save receiver in apps/user/signals.py already created the
    # profile, so fill in the names rather than creating a second row --
    # UserProfile's pk IS the user's pk, so a second create() collides.
    _name_profile(user, "Test", "Alumna")
    return user


def _name_profile(user, given, family):
    profile = user.profile
    profile.given_name = given
    profile.family_name = family
    profile.save(update_fields=["given_name", "family_name"])
    return profile


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

    def test_current_active_for_returns_the_active_membership(self):
        """The member IS a Gold Life Member. Their unconfirmed renewal
        request must not displace that."""
        self.assertEqual(
            Membership.objects.current_active_for(self.user), self.active
        )

    def test_current_for_still_returns_the_newest_row_of_any_status(self):
        """Pins the deliberate split: current_for keeps its old contract.

        The admin's Current Membership columns (apps/home/admin.py:95
        and :566) rely on this, because they render the status alongside
        the tier -- a pending request has to stay visible there.
        """
        self.assertEqual(Membership.objects.current_for(self.user), self.pending)

    def test_current_active_for_matches_the_qr_manager_query(self):
        """current_active_for must agree with the hand-rolled lookup at
        apps/qr_manager/views.py:64-66, which needed this behaviour
        before the manager offered it."""
        hand_rolled = (
            Membership.objects
            .filter(user=self.user, status=Membership.Status.ACTIVE)
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(hand_rolled, self.active)
        self.assertEqual(
            Membership.objects.current_active_for(self.user), hand_rolled
        )

    def test_current_active_for_is_none_when_nothing_is_active(self):
        """A first request awaiting confirmation holds nothing yet.
        Callers must handle None rather than assume a row."""
        newcomer = _make_user("newcomer@example.com")
        Membership.objects.create(
            user=newcomer, tier=self.student, status=Membership.Status.PENDING
        )
        self.assertIsNone(Membership.objects.current_active_for(newcomer))
        self.assertIsNotNone(Membership.objects.current_for(newcomer))


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


class UserProfileInvariantTests(TestCase):
    """Guards qa_500_report #5 -- every User has a UserProfile.

    Nothing used to guarantee it: UserProfile was created only by
    apps/user/adapter.py:111 (Google login) and the legacy-import
    command, while UserManager.create_user/create_superuser
    (apps/user/models.py:25-47) did not. Any account from
    createsuperuser, the shell or the admin's add form had none, and
    roughly twenty unguarded `user.profile.*` reads raised
    RelatedObjectDoesNotExist.

    apps/user/signals.py now creates one on every save of a new User.
    """

    @classmethod
    def setUpTestData(cls):
        # Exactly what `manage.py createsuperuser` produces.
        cls.superuser = User.objects.create_superuser(
            email="invariant.admin@example.com", password="x"
        )

    def test_created_superuser_has_a_profile(self):
        """Inverted -- this used to assert the profile was ABSENT."""
        self.assertTrue(hasattr(self.superuser, "profile"))

    def test_auto_created_profile_invents_no_data(self):
        """Names blank rather than derived from the e-mail, and neither
        DPA-2019 consent flag pre-granted."""
        profile = self.superuser.profile
        self.assertEqual(profile.given_name, "")
        self.assertEqual(profile.family_name, "")
        self.assertEqual(profile.display_name, "")
        self.assertFalse(profile.sms_opt_in)
        self.assertFalse(profile.email_opt_in)

    def test_alumni_profile_saves_for_a_blank_named_user(self):
        """Finding 5's reproduction, flipped.

        apps/home/models.py:1091 reads instance.user.profile inside an
        AutoSlugField populate_from, so this used to raise
        RelatedObjectDoesNotExist during save().
        """
        alumni = AlumniProfile.objects.create(user=self.superuser)
        self.assertIsNotNone(alumni.pk)

    def test_blank_named_profile_still_produces_a_usable_url(self):
        """The consequence the invariant alone does not fix.

        A blank name slugifies to "", and AlumniProfile.slug is
        blank=True/null=True, so django-autoslug would leave it None
        (autoslug/fields.py:267-273) -- and home:alumni_detail matches
        <slug:slug>, never None. get_alumni_profile_slug now falls back
        to the model name, mirroring what autoslug already does for
        Employee.slug.
        """
        alumni = AlumniProfile.objects.create(user=self.superuser)
        self.assertEqual(alumni.slug, "alumniprofile")
        self.assertIn(str(alumni.pk), alumni.get_absolute_url())

    def test_slug_upgrades_once_a_name_is_entered(self):
        """always_update=True on the field, so the placeholder is
        temporary rather than sticky."""
        alumni = AlumniProfile.objects.create(user=self.superuser)
        _name_profile(self.superuser, "Wanjiku", "Kamau")
        alumni.refresh_from_db()
        alumni.save()
        self.assertEqual(alumni.slug, "wanjiku-kamau")

    def test_two_blank_named_profiles_do_not_collide(self):
        """AlumniProfile.slug is unique=False, so the shared placeholder
        is legal; the UUID in the URL keeps them distinct."""
        other = User.objects.create_user(email="second.blank@example.com")
        first = AlumniProfile.objects.create(user=self.superuser)
        second = AlumniProfile.objects.create(user=other)
        self.assertEqual(first.slug, second.slug)
        self.assertNotEqual(first.get_absolute_url(), second.get_absolute_url())

    def test_a_deleted_profile_still_raises(self):
        """Pins the exception type for the window before the backfill
        migration runs -- a profile removed after the fact is still a
        reachable state."""
        UserProfile.objects.filter(pk=self.superuser.pk).delete()
        fresh = User.objects.get(pk=self.superuser.pk)
        with self.assertRaises(ObjectDoesNotExist):
            fresh.profile


class AlumniProfileDetailAccessTests(TestCase):
    """Guards qa_500_report #6 -- the profile page is members-only, and
    its sensitive fields are owner-or-admin.

    apps/home/views.py:515 was a bare DetailView with no gate, so an
    anonymous visitor holding a profile URL read the member's contact
    details and membership standing. Now LoginRequiredMixin.

    "Logged in" spans subdomains via SESSION_COOKIE_DOMAIN, so a staff
    or student account also reaches this apex view -- which is why
    alt_email and the payment-history panel are scoped to
    owner-or-admin rather than to any authenticated user.
    """

    @classmethod
    def setUpTestData(cls):
        from allauth.account.models import EmailAddress

        cls.owner = _make_user("owner@example.com")
        cls.alumni = AlumniProfile.objects.create(user=cls.owner)
        EmailAddress.objects.create(
            user=cls.owner, email="owner.alt@example.com", primary=False
        )
        cls.other_member = _make_user("other.member@example.com")
        cls.admin = User.objects.create_superuser(
            email="profile.admin@example.com", password="x"
        )
        _name_profile(cls.admin, "Profile", "Admin")

    def _url(self):
        return reverse(
            "home:alumni_detail",
            kwargs={"slug": self.alumni.slug, "pk": self.alumni.pk},
        )

    def test_anonymous_visitor_is_redirected_to_login(self):
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/", resp["Location"])

    def test_authenticated_non_owner_sees_the_directory_fields(self):
        self.client.force_login(self.other_member)
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_owner_or_admin"])
        self.assertContains(resp, self.owner.email)

    def test_authenticated_non_owner_gets_no_sensitive_fields(self):
        self.client.force_login(self.other_member)
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertIsNone(resp.context["alt_email"])
        self.assertNotContains(resp, "owner.alt@example.com")
        self.assertNotContains(resp, "Alt. Email")
        # alumni_detail.html:326 mentions "Payment History" inside an HTML
        # comment, which renders -- assert on the heading markup.
        self.assertNotContains(resp, ">Payment History</h2>")

    def test_owner_sees_the_sensitive_fields(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_owner_or_admin"])
        self.assertContains(resp, "owner.alt@example.com")
        self.assertContains(resp, ">Payment History</h2>")

    def test_admin_sees_the_sensitive_fields(self):
        """The Secretariat handles membership queries against this page."""
        self.client.force_login(self.admin)
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_owner_or_admin"])
        self.assertContains(resp, "owner.alt@example.com")
        self.assertContains(resp, ">Payment History</h2>")

    def test_sparse_profile_renders_for_an_authenticated_viewer(self):
        """No membership, no payments, no alternate e-mail -- the page
        must render rather than 500 on an absent related row."""
        sparse_user = _make_user("sparse@example.com")
        sparse = AlumniProfile.objects.create(user=sparse_user)
        self.client.force_login(self.other_member)
        resp = self.client.get(
            reverse(
                "home:alumni_detail",
                kwargs={"slug": sparse.slug, "pk": sparse.pk},
            ),
            HTTP_HOST=PUBLIC_HOST,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["current_membership"])
        self.assertIsNone(resp.context["pending_membership"])


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
        _name_profile(cls.superuser, "Matrix", "Super")

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


# ─────────────────────────────────────────────────────────────────────
# New coverage for the current_for fix (qa_500_report #2), sites 1 and 2.
# Both exercise the state the bug needs: a held ACTIVE membership with a
# NEWER unconfirmed PENDING renewal behind it.
# ─────────────────────────────────────────────────────────────────────

import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

# ReportLab and ImageField both write to disk, unaffected by the test
# database's transaction rollback -- same reasoning as the module-level
# override in apps/qr_manager/tests.py, scoped to the class that needs it.
_qa500_media_root = tempfile.mkdtemp(prefix="home_qa500_media_")

# A real, small PNG. ReportLab reads this back through PIL when drawing
# the badge, so it has to be a genuinely decodable image rather than a
# placeholder blob. RGB, not RGBA -- ReportLab takes an alpha-split path
# for RGBA that a minimal image trips over.
def _png_bytes():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (16, 16), "black").save(buf, format="PNG")
    return buf.getvalue()


def _pdf_text(body):
    """Return the decoded text operators from a ReportLab PDF.

    ReportLab writes content streams through /ASCII85Decode then
    /FlateDecode, so the drawn strings are not present as raw bytes --
    searching resp.content directly would pass or fail for the wrong
    reasons. Decoding is the only way to assert on what the badge
    actually says.
    """
    import base64
    import zlib

    out = []
    pos = 0
    while True:
        start = body.find(b"stream", pos)
        if start == -1:
            break
        # "endstream" contains "stream" -- skip those, or the stream
        # boundaries come out shifted and every decode fails silently.
        if body[start - 3:start] == b"end":
            pos = start + 6
            continue
        stop = body.find(b"endstream", start)
        if stop == -1:
            break
        data = body[start + 6:stop].strip()
        pos = stop + 9
        try:
            if data.endswith(b"~>"):
                data = base64.a85decode(data[:-2])
            out.append(zlib.decompress(data))
        except Exception:
            continue
    return b"".join(out)


class _ActivePlusPendingMixin:
    """Gold Life Member (ACTIVE) with a newer Student Annual renewal
    (PENDING) awaiting Secretariat confirmation."""

    @classmethod
    def setUpTestData(cls):
        cls.user = _make_user("badge.member@example.com")
        cls.alumni = AlumniProfile.objects.create(user=cls.user)
        cls.gold = MembershipTier.objects.create(
            name="Gold Life Member", fee=100000, tier_type="life",
            duration_months=0,
        )
        cls.student = MembershipTier.objects.create(
            name="Student Annual Membership", fee=500, tier_type="annual",
            duration_months=12,
        )
        cls.active = Membership.objects.create(
            user=cls.user, tier=cls.gold, status=Membership.Status.ACTIVE,
            is_lifetime=True,
        )
        cls.pending = Membership.objects.create(
            user=cls.user, tier=cls.student,
            status=Membership.Status.PENDING,
        )


class AlumniProfileMembershipDisplayTests(_ActivePlusPendingMixin, TestCase):
    """Site 1 -- apps/home/views.py:538, AlumniProfileDetailView.

    The standing badge must show what the member HOLDS, while the
    awaiting-confirmation panel shows the renewal in flight. Before the
    fix a single current_for() call fed both, so the badge announced the
    unconfirmed Student tier as the member's standing.

    The panel is owner-only (alumni_detail.html:171), hence force_login.
    """

    def _url(self):
        return reverse(
            "home:alumni_detail",
            kwargs={"slug": self.alumni.slug, "pk": self.alumni.pk},
        )

    def test_badge_shows_the_held_tier_and_panel_shows_the_pending_one(self):
        self.client.force_login(self.user)
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["current_membership"], self.active)
        self.assertEqual(resp.context["pending_membership"], self.pending)
        self.assertContains(
            resp, "Student Annual Membership &middot; Awaiting Confirmation"
        )

    def test_member_with_no_renewal_has_no_pending_row(self):
        """Pin -- the panel must not appear for a member holding only an
        active membership."""
        self.pending.delete()
        self.client.force_login(self.user)
        resp = self.client.get(self._url(), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.context["current_membership"], self.active)
        self.assertIsNone(resp.context["pending_membership"])
        self.assertNotContains(resp, "Awaiting Confirmation")


@override_settings(MEDIA_ROOT=_qa500_media_root)
class AlumniQrBadgePdfTierTests(_ActivePlusPendingMixin, TestCase):
    """Site 2 -- apps/home/views.py:683, the printed QR-badge PDF.

    The tier and validity are drawn onto a physical artefact
    (views.py:700 `tier_name = current_membership.tier.name`), so an
    unconfirmed renewal must never reach it.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_qa500_media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.alumni.qr_code_image.save(
            "badge.png", SimpleUploadedFile("badge.png", _png_bytes()),
            save=True,
        )
        self.client.force_login(self.user)

    def test_pdf_carries_the_held_tier_not_the_pending_one(self):
        url = reverse(
            "home:alumni_qr_download",
            kwargs={"slug": self.alumni.slug, "pk": self.alumni.pk},
        )
        resp = self.client.get(url, HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        drawn = _pdf_text(resp.content)
        self.assertIn(b"Gold Life Member", drawn)
        self.assertNotIn(b"Student Annual Membership", drawn)
        # The validity line comes off the same row (views.py:702-704).
        self.assertIn(b"Lifetime Membership", drawn)


# ─────────────────────────────────────────────────────────────────────
# Coverage phase 1 -- membership lifecycle end to end.
# assign -> activate -> supersede -> record instalment -> lapse.
#
# Characterisation tests: these assert what apps/home/services.py and
# the Membership model ACTUALLY do, not what they ought to. See
# docs/coverage-phase1-step1-2026-09-01.md.
#
# Service-level throughout, so no HTTP_HOST is needed. created_at is set
# explicitly wherever ordering is load-bearing -- Meta.ordering is
# ["-created_at"] and same-microsecond creation makes "newest"
# ambiguous.
# ─────────────────────────────────────────────────────────────────────

from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.utils import timezone

from apps.home import services
from apps.home.tasks import expire_lapsed_installment_plans


def _life_tier(name="Gold Life Member", fee=100000):
    return MembershipTier.objects.create(
        name=name, fee=fee, tier_type="life", duration_months=0,
    )


def _annual_tier(name="Full Annual Member", fee=2000, months=12):
    # duration_months must be non-zero: MembershipTier.is_lifetime() is
    # `tier_type == 'life' or duration_months == 0` (models.py:1005-1007),
    # so a 0-month annual tier would count as lifetime.
    return MembershipTier.objects.create(
        name=name, fee=fee, tier_type="annual", duration_months=months,
    )


class MembershipSupersessionInvariantTests(TestCase):
    """The one-ACTIVE-row invariant (services.py:29-50).

    apps/home/models.py's current_active_for() is correct only because
    the service layer supersedes any prior ACTIVE row before activating
    a new one. Until now nothing verified that.
    """

    def setUp(self):
        self.user = _make_user("lifecycle@example.com")
        self.gold = _life_tier()
        self.annual = _annual_tier()

    def _activated(self, tier):
        membership = services.assign_membership_tier(self.user, tier)
        return services.activate_membership(membership)

    def test_activating_supersedes_the_prior_active_row(self):
        first = self._activated(self.annual)
        second = services.assign_membership_tier(self.user, self.gold)
        services.activate_membership(second)

        first.refresh_from_db()
        self.assertEqual(first.status, Membership.Status.SUPERSEDED)

    def test_exactly_one_active_row_remains(self):
        """The invariant current_active_for() depends on."""
        self._activated(self.annual)
        services.activate_membership(
            services.assign_membership_tier(self.user, self.gold)
        )

        active = Membership.objects.filter(
            user=self.user, status=Membership.Status.ACTIVE
        )
        self.assertEqual(active.count(), 1)
        self.assertEqual(active.first().tier, self.gold)
        self.assertEqual(
            Membership.objects.current_active_for(self.user), active.first()
        )

    def test_membership_number_carries_forward(self):
        """services.py:42-43 copies the prior row's number onto the new
        one, so the number identifies the person, not the payment
        period."""
        first = self._activated(self.annual)
        original_number = first.membership_number
        self.assertTrue(original_number)

        second = services.activate_membership(
            services.assign_membership_tier(self.user, self.gold)
        )
        self.assertEqual(second.membership_number, original_number)

    def test_supersede_precedes_activate_so_the_constraint_holds(self):
        """Membership.Meta declares a partial unique constraint --
        unique_active_membership_number, on membership_number WHERE
        status='active'. Both rows share a number after the carry
        forward, so activating before superseding would violate it.
        Reaching this assertion at all proves the ordering."""
        first = self._activated(self.annual)
        second = services.activate_membership(
            services.assign_membership_tier(self.user, self.gold)
        )
        first.refresh_from_db()

        self.assertEqual(first.membership_number, second.membership_number)
        self.assertEqual(first.status, Membership.Status.SUPERSEDED)
        self.assertEqual(second.status, Membership.Status.ACTIVE)

    def test_first_ever_activation_supersedes_nothing(self):
        membership = services.assign_membership_tier(self.user, self.annual)
        returned = services.activate_membership(membership)

        self.assertEqual(returned.status, Membership.Status.ACTIVE)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 1)


class ActivateMembershipTests(TestCase):
    """services.activate_membership (services.py:53-76)."""

    def setUp(self):
        self.user = _make_user("activate@example.com")
        self.annual = _annual_tier()
        self.gold = _life_tier()

    def test_activation_stamps_status_and_dates_from_the_tier(self):
        on = timezone.now().date()
        membership = services.activate_membership(
            services.assign_membership_tier(self.user, self.annual),
            payment_date=on,
        )

        self.assertEqual(membership.status, Membership.Status.ACTIVE)
        self.assertEqual(membership.started_on, on)
        self.assertEqual(membership.expires_on, self.annual.get_expiry_date(on))
        self.assertFalse(membership.is_lifetime)
        self.assertTrue(membership.membership_number)

    def test_lifetime_tier_leaves_no_expiry(self):
        membership = services.activate_membership(
            services.assign_membership_tier(self.user, self.gold)
        )

        self.assertTrue(membership.is_lifetime)
        self.assertIsNone(membership.expires_on)
        self.assertTrue(membership.is_valid)

    def test_reactivating_an_active_row_skips_supersession(self):
        """Characterises the first_activation guard at services.py:72.

        A second call takes the False branch, so no supersession runs --
        the row cannot supersede itself. It does still re-run
        Membership.activate(), which recomputes expires_on from the new
        payment date while leaving started_on alone (models.py:1583-1586).
        """
        first_date = timezone.now().date() - timedelta(days=30)
        membership = services.activate_membership(
            services.assign_membership_tier(self.user, self.annual),
            payment_date=first_date,
        )
        original_expiry = membership.expires_on

        later = timezone.now().date()
        services.activate_membership(membership, payment_date=later)
        membership.refresh_from_db()

        # No self-supersession, and still exactly one row.
        self.assertEqual(membership.status, Membership.Status.ACTIVE)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 1)
        # started_on is only set when unset, so it survives.
        self.assertEqual(membership.started_on, first_date)
        # expires_on, however, is recomputed from the later date.
        self.assertEqual(membership.expires_on, self.annual.get_expiry_date(later))
        self.assertGreater(membership.expires_on, original_expiry)


class RecordInstallmentPaymentTests(TestCase):
    """services.record_installment_payment (services.py:79-93) and the
    model method it delegates to (models.py:1620-1638)."""

    def setUp(self):
        self.user = _make_user("instalments@example.com")
        self.tier = _annual_tier(name="Corporate Membership", fee=12000)

    def _plan(self):
        return services.assign_membership_tier(
            self.user, self.tier,
            payment_frequency=Membership.PaymentFrequency.MONTHLY,
        )

    def test_first_payment_activates_and_sets_the_next_due_date(self):
        paid_on = timezone.now().date()
        membership = services.record_installment_payment(
            self._plan(), Decimal("1000"), payment_date=paid_on
        )

        self.assertEqual(membership.status, Membership.Status.ACTIVE)
        self.assertEqual(membership.amount_paid, Decimal("1000"))
        self.assertEqual(membership.balance_due, Decimal("11000"))
        self.assertEqual(
            membership.next_installment_due, paid_on + timedelta(days=30)
        )

    def test_second_payment_accumulates_without_reactivating(self):
        plan = self._plan()
        first_date = timezone.now().date() - timedelta(days=10)
        services.record_installment_payment(plan, Decimal("1000"), payment_date=first_date)
        plan.refresh_from_db()
        started = plan.started_on

        services.record_installment_payment(plan, Decimal("2500"))
        plan.refresh_from_db()

        self.assertEqual(plan.amount_paid, Decimal("3500"))
        self.assertEqual(plan.status, Membership.Status.ACTIVE)
        # started_on unchanged -- activate() did not run a second time.
        self.assertEqual(plan.started_on, started)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 1)

    def test_next_due_date_advances_by_the_frequency_grace_days(self):
        plan = self._plan()
        first_date = timezone.now().date() - timedelta(days=10)
        services.record_installment_payment(plan, Decimal("1000"), payment_date=first_date)
        plan.refresh_from_db()
        self.assertEqual(plan.next_installment_due, first_date + timedelta(days=30))

        second_date = timezone.now().date()
        services.record_installment_payment(plan, Decimal("1000"), payment_date=second_date)
        plan.refresh_from_db()

        self.assertEqual(plan.next_installment_due, second_date + timedelta(days=30))
        self.assertEqual(
            Membership.INSTALLMENT_FREQUENCY_DAYS[Membership.PaymentFrequency.MONTHLY], 30
        )

    def test_clearing_the_balance_sets_no_further_due_date(self):
        """models.py:1635 only pushes the date while balance_due > 0."""
        membership = services.record_installment_payment(
            self._plan(), Decimal("12000")
        )

        self.assertEqual(membership.balance_due, Decimal("0"))
        self.assertIsNone(membership.next_installment_due)
        self.assertEqual(membership.status, Membership.Status.ACTIVE)


class RenewMembershipServiceTests(TestCase):
    """services.renew_membership (services.py:108-117)."""

    def setUp(self):
        self.user = _make_user("renewer2@example.com")
        self.annual = _annual_tier()

    def test_renewal_creates_a_pending_row_at_the_active_tier(self):
        services.activate_membership(
            services.assign_membership_tier(self.user, self.annual)
        )
        renewed = services.renew_membership(self.user)

        self.assertEqual(renewed.tier, self.annual)
        self.assertEqual(renewed.status, Membership.Status.PENDING)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 2)

    def test_renewal_without_an_active_membership_raises(self):
        """services.py:116 -- a first-time grant is assign_membership_tier."""
        with self.assertRaises(ValueError):
            services.renew_membership(self.user)


class UpgradeToLifetimeServiceTests(TestCase):
    """services.upgrade_to_lifetime (services.py:120-127)."""

    def setUp(self):
        self.user = _make_user("upgrader@example.com")

    def test_upgrade_to_a_life_tier_creates_a_pending_row(self):
        gold = _life_tier()
        upgraded = services.upgrade_to_lifetime(self.user, gold)

        self.assertEqual(upgraded.tier, gold)
        self.assertEqual(upgraded.status, Membership.Status.PENDING)

    def test_upgrade_to_a_non_life_tier_raises(self):
        annual = _annual_tier()
        with self.assertRaises(ValueError):
            services.upgrade_to_lifetime(self.user, annual)


class ExpireLapsedInstallmentPlansTests(TestCase):
    """apps/home/tasks.py:168 and the command it wraps.

    Tested as a direct callable, never through the django-q2 cluster --
    the task is an ordinary function and the broker adds nothing to
    verify here.
    """

    def setUp(self):
        self.today = timezone.now().date()
        self.tier = _annual_tier(name="Corporate Membership", fee=12000)

    def _plan(self, email, due_days_ago, frequency=Membership.PaymentFrequency.MONTHLY,
              status=Membership.Status.ACTIVE, paid="1000"):
        user = _make_user(email)
        membership = Membership.objects.create(
            user=user, tier=self.tier, status=status,
            payment_frequency=frequency, amount_paid=Decimal(paid),
        )
        if due_days_ago is not None:
            membership.next_installment_due = self.today - timedelta(days=due_days_ago)
            membership.save(update_fields=["next_installment_due"])
        return membership

    def test_an_overdue_installment_plan_is_expired(self):
        # 40 days past due, grace is 30 -> is_overdue True.
        plan = self._plan("overdue@example.com", due_days_ago=40)
        self.assertTrue(plan.is_overdue)

        expire_lapsed_installment_plans()

        plan.refresh_from_db()
        self.assertEqual(plan.status, Membership.Status.EXPIRED)

    def test_task_is_callable_directly_without_the_cluster(self):
        """The task wraps call_command; both entry points behave alike."""
        plan = self._plan("direct@example.com", due_days_ago=40)
        call_command("expire_lapsed_installment_plans", verbosity=0)
        plan.refresh_from_db()
        self.assertEqual(plan.status, Membership.Status.EXPIRED)

    def test_it_leaves_everything_else_alone(self):
        """The failure mode of a scheduled mutation job is collateral
        damage, so this is the assertion that matters most."""
        overdue = self._plan("sweep.overdue@example.com", due_days_ago=40)
        not_yet = self._plan("sweep.current@example.com", due_days_ago=5)
        lump_sum = self._plan(
            "sweep.once@example.com", due_days_ago=40,
            frequency=Membership.PaymentFrequency.ONCE,
        )
        pending = self._plan(
            "sweep.pending@example.com", due_days_ago=40,
            status=Membership.Status.PENDING,
        )
        already = self._plan(
            "sweep.expired@example.com", due_days_ago=40,
            status=Membership.Status.EXPIRED,
        )
        paid_off = self._plan(
            "sweep.paidoff@example.com", due_days_ago=40, paid="12000",
        )

        expire_lapsed_installment_plans()

        for membership, expected, label in [
            (overdue, Membership.Status.EXPIRED, "overdue plan"),
            (not_yet, Membership.Status.ACTIVE, "not yet past grace"),
            (lump_sum, Membership.Status.ACTIVE, "one-off payment"),
            (pending, Membership.Status.PENDING, "pending"),
            (already, Membership.Status.EXPIRED, "already expired"),
            (paid_off, Membership.Status.ACTIVE, "balance cleared"),
        ]:
            with self.subTest(case=label):
                membership.refresh_from_db()
                self.assertEqual(membership.status, expected)


class GenerateMembershipNumberTests(TestCase):
    """Characterises models.py:1565-1569.

        def generate_membership_number(self):
            year = timezone.now().year
            last = Membership.objects.filter(membership_number__endswith=f"/{year}").count()
            return f"UoNAA/{last + 1:06d}/{year}"

    A count(), not a sequence -- so what the next number is depends on
    how many numbered rows currently exist, not on how many have ever
    been issued. These tests record what that actually means across
    supersession, expiry and deletion.
    """

    def setUp(self):
        self.tier = _annual_tier()
        self.year = timezone.now().year

    def _activate_for(self, email):
        user = _make_user(email)
        return services.activate_membership(
            services.assign_membership_tier(user, self.tier)
        )

    def test_numbers_increment_across_members(self):
        first = self._activate_for("num.one@example.com")
        second = self._activate_for("num.two@example.com")

        self.assertEqual(first.membership_number, f"UoNAA/000001/{self.year}")
        self.assertEqual(second.membership_number, f"UoNAA/000002/{self.year}")

    def test_supersession_issues_no_new_number_but_skips_the_sequence(self):
        """Characterises a surprise: renewals make the numbering skip.

        The successor carries the superseded row's number forward, so no
        new number is *issued* -- but the count() at models.py:1567
        counts ROWS whose number ends "/{year}", not distinct numbers.
        After one renewal two rows share one number, so the count reads
        2 and the next member is issued 000003. 000002 is never used.

        Uniqueness -- the only thing the method's docstring promises
        ("unique per calendar year of activation") -- still holds, so
        this is recorded rather than treated as a defect. The practical
        effect is that numbers are not dense and inflate faster than the
        membership does: a member who renews annually consumes a number
        from the sequence every year without receiving a new one.
        """
        first = self._activate_for("num.super@example.com")
        original = first.membership_number
        self.assertEqual(original, f"UoNAA/000001/{self.year}")

        successor = services.activate_membership(
            services.assign_membership_tier(first.user, self.tier)
        )
        # No new number issued -- carried forward.
        self.assertEqual(successor.membership_number, original)
        self.assertEqual(
            Membership.objects.filter(
                membership_number=original
            ).count(), 2,
        )

        # ...but the next member skips 000002, because two rows now
        # carry 000001 and the count sees both.
        other = self._activate_for("num.after.super@example.com")
        self.assertEqual(other.membership_number, f"UoNAA/000003/{self.year}")

    def test_expiry_does_not_free_a_number(self):
        """An EXPIRED row still holds its number and is still counted."""
        first = self._activate_for("num.expire@example.com")
        first.status = Membership.Status.EXPIRED
        first.save(update_fields=["status"])

        nxt = self._activate_for("num.after.expire@example.com")
        self.assertEqual(nxt.membership_number, f"UoNAA/000002/{self.year}")

    def test_deleting_a_membership_frees_its_number_for_reuse(self):
        """The count()-derived sequence is not monotonic: deleting a
        numbered row lowers the count, so the next activation reissues
        the number the deleted row held.

        The partial unique constraint (unique_active_membership_number)
        does not prevent this -- it only guards numbers across rows that
        are currently ACTIVE, and the deleted row is gone.
        """
        first = self._activate_for("num.keep@example.com")
        second = self._activate_for("num.delete@example.com")
        reused_number = second.membership_number
        second.delete()

        third = self._activate_for("num.reuse@example.com")

        self.assertEqual(third.membership_number, reused_number)
        self.assertNotEqual(third.membership_number, first.membership_number)


# ─────────────────────────────────────────────────────────────────────
# Coverage priority 4 (re-scoped) -- the payment-confirmation path.
#
# apps/home/payments.py is a placeholder seam: there is no payment
# gateway in this project, so nothing external is mocked here. The money
# actually moves in PaymentAdmin.mark_completed (admin.py:686-738),
# which is what most of this block covers. See
# docs/coverage-phase1-payments-step1-2026-09-01.md.
#
# Admin actions are invoked DIRECTLY rather than through the admin HTTP
# flow -- the same approach the backfill-migration tests take.
# ─────────────────────────────────────────────────────────────────────

from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.home.admin import PaymentAdmin
from apps.home.models import Payment
from apps.home.payments import (
    GATEWAYS,
    ManualGateway,
    PaymentGateway,
    get_gateway,
    initiate_payment,
)


def _admin_request():
    """self.message_user() writes to the message store, so it must exist."""
    request = RequestFactory().post("/membership-admin/")
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _payment_admin():
    return PaymentAdmin(Payment, AdminSite())


def _alumni_for(email):
    user = _make_user(email)
    return AlumniProfile.objects.create(user=user), user


# ── payments.py: the placeholder seam (6) ────────────────────────────


class PaymentGatewaySeamTests(TestCase):
    """apps/home/payments.py in full.

    Every method routes to ManualGateway -- no credentials for any real
    provider exist (the module docstring says so, and settings carries
    none). These tests close the file and pin the dispatch seam that is
    the module's whole reason for existing.
    """

    def setUp(self):
        self.alumni, self.user = _alumni_for("payer@example.com")
        self.tier = _annual_tier()
        self.payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier,
            amount=Decimal("2000"), payment_method="mpesa",
        )

    def test_every_known_method_routes_to_the_manual_gateway(self):
        for method in ("mpesa", "credit_card", "bank_transfer"):
            with self.subTest(method=method):
                self.assertIsInstance(get_gateway(method), ManualGateway)

    def test_an_unknown_method_falls_back_to_the_manual_gateway(self):
        """GATEWAYS.get(payment_method, ManualGateway) -- the default arm."""
        self.assertIsInstance(get_gateway("bitcoin"), ManualGateway)
        self.assertIsInstance(get_gateway(""), ManualGateway)

    def test_manual_initiate_returns_the_payment_unchanged(self):
        result = ManualGateway().initiate(self.payment)

        self.assertIs(result, self.payment)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, "pending")

    def test_manual_verify_reports_the_current_status(self):
        self.assertEqual(ManualGateway().verify(self.payment), "pending")
        self.payment.payment_status = "completed"
        self.assertEqual(ManualGateway().verify(self.payment), "completed")

    def test_the_base_interface_refuses_to_be_used_directly(self):
        base = PaymentGateway()
        with self.assertRaises(NotImplementedError):
            base.initiate(self.payment)
        with self.assertRaises(NotImplementedError):
            base.verify(self.payment)

    def test_initiate_payment_dispatches_through_the_registry(self):
        """The seam a real gateway would plug into later: swapping a
        GATEWAYS entry must change what initiate_payment() calls."""
        sentinel = mock.Mock()
        sentinel.return_value.initiate.return_value = "dispatched"

        with mock.patch.dict(GATEWAYS, {"mpesa": sentinel}):
            result = initiate_payment(self.payment)

        self.assertEqual(result, "dispatched")
        sentinel.return_value.initiate.assert_called_once_with(self.payment)


# ── PaymentAdmin.mark_completed -- where the money moves (6) ─────────


class PaymentAdminMarkCompletedTests(TestCase):
    """apps/home/admin.py:686-738.

    The only code in the project that turns a confirmed payment into an
    active membership. Every activation routes through the service layer
    (:727, :736), so the one-ACTIVE-row invariant holds from here too.
    """

    def setUp(self):
        self.admin = _payment_admin()
        self.request = _admin_request()
        self.alumni, self.user = _alumni_for("confirmer@example.com")
        self.tier = _annual_tier(name="Corporate Membership", fee=12000)

    def _run(self, *payments):
        pks = [p.pk for p in payments]
        self.admin.mark_completed(self.request, Payment.objects.filter(pk__in=pks))

    def test_a_linked_payment_records_an_instalment(self):
        membership = services.assign_membership_tier(
            self.user, self.tier,
            payment_frequency=Membership.PaymentFrequency.MONTHLY,
        )
        payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier, membership=membership,
            amount=Decimal("3000"), payment_method="mpesa",
        )

        self._run(payment)

        membership.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, "completed")
        self.assertEqual(membership.status, Membership.Status.ACTIVE)
        self.assertEqual(membership.amount_paid, Decimal("3000"))

    def test_an_unlinked_payment_activates_the_newest_pending_row(self):
        older = services.assign_membership_tier(self.user, self.tier)
        newer = services.assign_membership_tier(self.user, self.tier)
        # Meta.ordering is ["-created_at"], and the admin picks the newest
        # PENDING row (admin.py:731) -- make the order unambiguous.
        Membership.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier,
            amount=Decimal("12000"), payment_method="bank_transfer",
        )

        self._run(payment)

        newer.refresh_from_db()
        older.refresh_from_db()
        self.assertEqual(newer.status, Membership.Status.ACTIVE)
        self.assertEqual(older.status, Membership.Status.PENDING)

    def test_an_unlinked_payment_with_no_pending_row_creates_one(self):
        """admin.py:733-734 -- created PENDING, then activated through
        the service layer, so the invariant is not bypassed."""
        payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier,
            amount=Decimal("12000"), payment_method="mpesa",
        )
        self.assertFalse(Membership.objects.filter(user=self.user).exists())

        self._run(payment)

        membership = Membership.objects.get(user=self.user)
        self.assertEqual(membership.status, Membership.Status.ACTIVE)
        self.assertEqual(membership.tier, self.tier)

    def test_a_payment_without_a_tier_is_skipped(self):
        """admin.py:720-722 -- marked completed, then `continue`. The
        payment is still confirmed; no membership is touched."""
        payment = Payment.objects.create(
            alumni=self.alumni, amount=Decimal("500"), payment_method="mpesa",
        )

        self._run(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, "completed")
        self.assertFalse(Membership.objects.filter(user=self.user).exists())

    def test_the_due_date_is_anchored_to_confirmation_not_submission(self):
        """admin.py:704-707, decided 2026-08-21: a request can sit pending
        for weeks, so anchoring the schedule to payment_date could make an
        instalment read as overdue the moment it activates."""
        membership = services.assign_membership_tier(
            self.user, self.tier,
            payment_frequency=Membership.PaymentFrequency.MONTHLY,
        )
        submitted = timezone.now() - timedelta(days=45)
        payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier, membership=membership,
            amount=Decimal("3000"), payment_method="mpesa",
            payment_date=submitted,
        )

        self._run(payment)

        membership.refresh_from_db()
        today = timezone.now().date()
        self.assertEqual(membership.next_installment_due, today + timedelta(days=30))
        self.assertNotEqual(
            membership.next_installment_due, submitted.date() + timedelta(days=30)
        )
        self.assertFalse(membership.is_overdue)

    def test_confirming_a_renewal_supersedes_the_prior_active_row(self):
        """The invariant end to end from the payment side."""
        gold = _life_tier()
        held = services.activate_membership(
            services.assign_membership_tier(self.user, gold)
        )
        renewal = services.assign_membership_tier(self.user, self.tier)
        payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier, membership=renewal,
            amount=Decimal("12000"), payment_method="mpesa",
        )

        self._run(payment)

        held.refresh_from_db()
        renewal.refresh_from_db()
        self.assertEqual(held.status, Membership.Status.SUPERSEDED)
        self.assertEqual(renewal.status, Membership.Status.ACTIVE)
        self.assertEqual(
            Membership.objects.filter(
                user=self.user, status=Membership.Status.ACTIVE
            ).count(), 1,
        )


# ── Payment.mark_as_* model methods (4) ──────────────────────────────


class PaymentStatusMethodTests(TestCase):
    """apps/home/models.py:1749-1785. These mutate the Payment row only."""

    def setUp(self):
        self.alumni, self.user = _alumni_for("statuses@example.com")
        self.tier = _annual_tier()

    def _payment(self, method="mpesa"):
        return Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier,
            amount=Decimal("2000"), payment_method=method,
        )

    def test_completion_routes_the_receipt_number_by_method(self):
        mpesa = self._payment("mpesa")
        mpesa.mark_as_completed(receipt_number="QGR7X8Y9Z0")
        mpesa.refresh_from_db()
        self.assertEqual(mpesa.payment_status, "completed")
        self.assertIsNotNone(mpesa.completion_date)
        self.assertEqual(mpesa.mpesa_receipt_number, "QGR7X8Y9Z0")
        # Both receipt fields are null=True (models.py:1701-1702), so the
        # one not used by this payment method stays None, not "".
        self.assertIsNone(mpesa.bank_reference)

        bank = self._payment("bank_transfer")
        bank.mark_as_completed(receipt_number="BNK-00042")
        bank.refresh_from_db()
        self.assertEqual(bank.bank_reference, "BNK-00042")
        self.assertIsNone(bank.mpesa_receipt_number)

    def test_failure_records_the_reason(self):
        payment = self._payment()
        payment.mark_as_failed(reason="Insufficient funds")
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, "failed")
        self.assertEqual(payment.notes, "Insufficient funds")

    def test_pending_verification_sets_the_status(self):
        payment = self._payment()
        payment.mark_as_pending_verification()
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, "pending_verification")

    def test_refund_records_the_reason(self):
        payment = self._payment()
        payment.mark_as_refunded(reason="Duplicate transfer")
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, "refunded")
        self.assertEqual(payment.notes, "Duplicate transfer")


# ── Candidate findings D and E (2) ───────────────────────────────────


class PaymentMembershipDivergenceTests(TestCase):
    """Reproductions for findings D and E. Both assert CURRENT
    behaviour; neither is fixed here."""

    def setUp(self):
        self.admin = _payment_admin()
        self.request = _admin_request()
        self.alumni, self.user = _alumni_for("divergence@example.com")
        self.tier = _annual_tier()

    def test_finding_d_marking_a_payment_completed_leaves_membership_pending(self):
        """FINDING D -- a live money bug, documented not fixed.

        Payment.mark_as_completed (models.py:1749-1759) touches the
        Payment row only; none of the mark_as_* methods references
        Membership. The service layer is called from exactly one place,
        the bulk action at admin.py:727/736, and PaymentAdmin has no
        save_model override while payment_status is an editable field in
        its fieldset (admin.py:664, readonly_fields at :656 lists only
        transaction_reference/created_at/updated_at).

        So a Secretariat member who opens a Payment in the change form
        and sets its status to "completed" -- or anyone calling this
        model method from the shell, or a future gateway callback --
        records the money as received while the membership stays
        PENDING. Only the bulk action does both.
        """
        membership = services.assign_membership_tier(self.user, self.tier)
        payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier, membership=membership,
            amount=Decimal("2000"), payment_method="mpesa",
        )

        payment.mark_as_completed(receipt_number="QGR000001")

        payment.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(payment.payment_status, "completed")
        # The defect: money in, membership not activated.
        self.assertEqual(membership.status, Membership.Status.PENDING)
        self.assertIsNone(Membership.objects.current_active_for(self.user))

    def test_finding_e_a_refund_does_not_reverse_an_activation(self):
        """FINDING E -- policy-dependent, documented not fixed.

        mark_as_refunded / mark_as_failed (models.py:1764-1785) do not
        touch the membership, so a payment refunded after the bulk
        action activated it leaves the member ACTIVE with no payment
        behind them. Whether that is wrong is an Association decision --
        honouring a membership through a refund dispute is defensible --
        but it is currently implicit rather than chosen.
        """
        membership = services.assign_membership_tier(self.user, self.tier)
        payment = Payment.objects.create(
            alumni=self.alumni, membership_tier=self.tier, membership=membership,
            amount=Decimal("2000"), payment_method="mpesa",
        )
        self.admin.mark_completed(
            self.request, Payment.objects.filter(pk=payment.pk)
        )
        membership.refresh_from_db()
        self.assertEqual(membership.status, Membership.Status.ACTIVE)

        payment.refresh_from_db()
        payment.mark_as_refunded(reason="Chargeback")

        payment.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(payment.payment_status, "refunded")
        # The membership survives the refund.
        self.assertEqual(membership.status, Membership.Status.ACTIVE)
        self.assertEqual(
            Membership.objects.current_active_for(self.user), membership
        )


# ─────────────────────────────────────────────────────────────────────
# Coverage priority 5 -- apps/home/forms.py.
#
# Before this block, not one clean_*/clean()/save()/__init__ in that
# module had ever executed in a test: the 34% baseline was almost
# entirely field declarations running at import. See
# docs/coverage-phase1-forms-step1-2026-09-01.md.
#
# All pure-data -- no form here takes a request or a user, so no
# HTTP_HOST is needed anywhere in this block. Forms are INSTANTIATED
# rather than inspected as classes, because querysets and `required`
# flags are set in __init__.
# ─────────────────────────────────────────────────────────────────────

from django.core.files.uploadedfile import SimpleUploadedFile as _Upload

from apps.home.forms import (
    AlumniDigitalIDApplicationForm,
    AlumniProfileForm,
    AlumniRegistrationForm,
    ContactForm,
    MembershipUpdateForm,
    ProfileClaimCodeForm,
    ProfileClaimSearchForm,
)
from apps.home.models import ContactMessage, Faculty, Qualification

_forms_media_root = tempfile.mkdtemp(prefix="home_forms_media_")


def _faculty_and_qualification(name="Agriculture"):
    faculty = Faculty.objects.create(faculty_name=name)
    qualification = Qualification.objects.create(
        faculty=faculty, level="bachelors", name=f"BSc {name}"
    )
    return faculty, qualification


def _profile_form_data(**overrides):
    """The minimum AlumniProfileForm accepts, UoN branch.

    Required-ness is decided in __init__ from its optional_fields
    allow-list (forms.py:121-145), so this mirrors what that leaves
    mandatory.
    """
    data = {
        "surname": "Kamau",
        "first_name": "Wanjiku",
        "date_of_birth": "1990-01-01",
        "id_passport_no": "12345678",
        "phone_mobile": "0712345678",
        "graduation_institution": "uon",
    }
    data.update(overrides)
    return data


# ── ContactForm (2) ──────────────────────────────────────────────────


class ContactFormTests(TestCase):
    """forms.py:13-28."""

    def test_valid_message_is_accepted_without_a_subject(self):
        form = ContactForm(data={
            "name": "Wanjiku Kamau",
            "email": "wanjiku@example.com",
            "message": "Please send me the AGM agenda.",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["subject"], "")

    def test_the_model_required_fields_are_enforced(self):
        form = ContactForm(data={"subject": "Only a subject"})
        self.assertFalse(form.is_valid())
        for field in ("name", "email", "message"):
            with self.subTest(field=field):
                self.assertIn(field, form.errors)


# ── AlumniProfileForm (13) ───────────────────────────────────────────


class AlumniProfileFormPhoneTests(TestCase):
    """clean_phone_mobile (forms.py:215-227) and clean_phone_alt (:229-236)."""

    def setUp(self):
        self.faculty, self.qualification = _faculty_and_qualification()

    def _form(self, instance=None, **overrides):
        data = _profile_form_data(
            faculty=self.faculty.pk, qualification=self.qualification.pk, **overrides
        )
        return AlumniProfileForm(data=data, instance=instance)

    def test_a_local_number_is_normalised_to_e164(self):
        form = self._form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_mobile"], "+254712345678")

    def test_an_invalid_number_is_rejected(self):
        form = self._form(phone_mobile="not-a-number")
        self.assertFalse(form.is_valid())
        self.assertIn("phone_mobile", form.errors)

    def test_a_number_owned_by_another_account_is_rejected(self):
        """The exclusion must still catch real duplicates -- asserted in
        the registration shape the view now produces, so the finding-F
        fix cannot have loosened it."""
        registrant = _make_user("registrant.dup@example.com")
        other = _make_user("other.owner@example.com")
        other.phone = "+254712345678"
        other.save(update_fields=["phone"])

        form = self._form(instance=AlumniProfile(user=registrant))

        self.assertFalse(form.is_valid())
        self.assertIn(
            "already registered to another account", str(form.errors["phone_mobile"])
        )

    def test_finding_f_registration_accepts_the_users_own_number(self):
        """Guards the finding-F fix.

        clean_phone_mobile self-excludes on self.instance.user_id:

            owner = User.objects.filter(phone=normalized)
            if self.instance.user_id:
                owner = owner.exclude(pk=self.instance.user_id)

        CreateView used to pass no instance at all, so user_id was None
        during validation -- the user was only attached afterwards, in
        form_valid -- and a registrant whose User.phone was already
        populated was told their OWN number belonged to somebody else.

        AlumniRegisterView.get_form_kwargs now supplies
        AlumniProfile(user=request.user), so the existing exclusion has
        something to exclude. clean_phone_mobile itself is unchanged.
        """
        registrant = _make_user("registrant@example.com")
        registrant.phone = "+254712345678"
        registrant.save(update_fields=["phone"])

        # The shape get_form_kwargs now produces: unsaved, but carrying
        # the registrant.
        instance = AlumniProfile(user=registrant)
        self.assertTrue(instance._state.adding)
        form = self._form(instance=instance)

        self.assertTrue(form.is_valid(), form.errors)

    def test_the_edit_path_accepts_the_users_own_number(self):
        """Contrast with finding F: a saved instance has user_id, so the
        self-exclusion works and editing does not trip over itself."""
        owner = _make_user("editor@example.com")
        owner.phone = "+254712345678"
        owner.save(update_fields=["phone"])
        alumni = AlumniProfile.objects.create(user=owner)

        form = self._form(instance=alumni)

        self.assertTrue(form.is_valid(), form.errors)

    def test_alternate_phone_is_optional(self):
        form = self._form(phone_alt="")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_alt"], "")

    def test_alternate_phone_is_normalised_when_given(self):
        form = self._form(phone_alt="0722000111")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_alt"], "+254722000111")

    def test_an_invalid_alternate_phone_is_rejected(self):
        form = self._form(phone_alt="12")
        self.assertFalse(form.is_valid())
        self.assertIn("phone_alt", form.errors)


class AlumniProfileFormIdentityTests(TestCase):
    """clean_id_passport_no (forms.py:238-245)."""

    def setUp(self):
        self.faculty, self.qualification = _faculty_and_qualification()

    def _form(self, **overrides):
        return AlumniProfileForm(data=_profile_form_data(
            faculty=self.faculty.pk, qualification=self.qualification.pk, **overrides
        ))

    def test_a_fresh_id_is_accepted(self):
        self.assertTrue(self._form().is_valid())

    def test_an_id_held_by_another_profile_is_rejected(self):
        holder = _make_user("id.holder@example.com")
        profile = holder.profile
        profile.national_id = "12345678"
        profile.save(update_fields=["national_id"])

        form = self._form(phone_mobile="0722333444")

        self.assertFalse(form.is_valid())
        self.assertIn("id_passport_no", form.errors)

    def test_surrounding_whitespace_does_not_defeat_the_check(self):
        """Finding G from Step 1 is RETRACTED -- it does not reproduce.

        I claimed the exact-match lookup would let the same ID through
        with incidental whitespace. It does not: forms.CharField strips
        by default (strip=True since Django 1.9), so " 12345678 " is
        already "12345678" by the time clean_id_passport_no runs. The
        duplicate is caught.
        """
        holder = _make_user("g.holder@example.com")
        profile = holder.profile
        profile.national_id = "12345678"
        profile.save(update_fields=["national_id"])

        form = self._form(id_passport_no=" 12345678 ", phone_mobile="0733444555")

        self.assertFalse(form.is_valid())
        self.assertIn("id_passport_no", form.errors)


class AlumniProfileFormInstitutionTests(TestCase):
    """clean() (forms.py:247-277) -- which unit is required depends on
    graduation_institution, so neither branch is required field-level."""

    def setUp(self):
        self.faculty, self.qualification = _faculty_and_qualification()

    def test_uon_requires_faculty_and_qualification(self):
        form = AlumniProfileForm(data=_profile_form_data())
        self.assertFalse(form.is_valid())
        self.assertIn("faculty", form.errors)
        self.assertIn("qualification", form.errors)

    def test_a_qualification_from_another_faculty_is_rejected(self):
        other_faculty, other_qualification = _faculty_and_qualification("Law")
        form = AlumniProfileForm(data=_profile_form_data(
            faculty=self.faculty.pk, qualification=other_qualification.pk
        ))

        self.assertFalse(form.is_valid())
        self.assertIn(
            "does not belong to the selected faculty", str(form.errors["qualification"])
        )

    def test_other_institution_requires_its_own_two_fields(self):
        form = AlumniProfileForm(data=_profile_form_data(
            graduation_institution="other"
        ))
        self.assertFalse(form.is_valid())
        self.assertIn("other_institution_name", form.errors)
        self.assertIn("other_institution_qualification", form.errors)

    def test_other_institution_nulls_the_uon_fields(self):
        form = AlumniProfileForm(data=_profile_form_data(
            graduation_institution="other",
            faculty=self.faculty.pk,
            qualification=self.qualification.pk,
            other_institution_name="Kenyatta University",
            other_institution_qualification="BSc Chemistry",
        ))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["faculty"])
        self.assertIsNone(form.cleaned_data["qualification"])


class AlumniProfileFormSaveTests(TestCase):
    """save() (forms.py:279-315) -- the only form touching three models."""

    def setUp(self):
        self.faculty, self.qualification = _faculty_and_qualification()
        self.user = _make_user("saver@example.com")

    def test_save_fans_out_to_profile_user_and_allauth(self):
        from allauth.account.models import EmailAddress

        alumni = AlumniProfile(user=self.user)
        form = AlumniProfileForm(instance=alumni, data=_profile_form_data(
            faculty=self.faculty.pk,
            qualification=self.qualification.pk,
            email="alt.address@example.com",
            receive_newsletter=True,
        ))
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        self.user.refresh_from_db()
        # Exactly one profile row: the signal made it, save() filled it.
        self.assertEqual(UserProfile.objects.filter(pk=self.user.pk).count(), 1)
        self.assertEqual(self.user.profile.given_name, "Wanjiku")
        self.assertEqual(self.user.profile.family_name, "Kamau")
        self.assertTrue(self.user.profile.email_opt_in)
        self.assertEqual(self.user.phone, "+254712345678")
        self.assertTrue(
            EmailAddress.objects.filter(
                user=self.user, email="alt.address@example.com", primary=False
            ).exists()
        )

    def test_init_prefills_from_an_existing_profile_on_the_edit_path(self):
        profile = self.user.profile
        profile.given_name = "Amina"
        profile.family_name = "Otieno"
        profile.city = "Kisumu"
        profile.save(update_fields=["given_name", "family_name", "city"])
        alumni = AlumniProfile.objects.create(user=self.user)

        form = AlumniProfileForm(instance=alumni)

        self.assertFalse(alumni._state.adding)
        self.assertEqual(form.fields["first_name"].initial, "Amina")
        self.assertEqual(form.fields["surname"].initial, "Otieno")
        self.assertEqual(form.fields["city"].initial, "Kisumu")


# ── AlumniRegistrationForm (5) ───────────────────────────────────────


class AlumniRegistrationFormTests(TestCase):
    """forms.py:318-396 -- the profile form plus the subscription fields."""

    def setUp(self):
        self.faculty, self.qualification = _faculty_and_qualification()
        self.affordable = _annual_tier(name="Full Annual Member", fee=2000)
        self.expensive = _life_tier(name="Platinum Life Membership", fee=500000)

    def _data(self, **overrides):
        data = _profile_form_data(
            faculty=self.faculty.pk,
            qualification=self.qualification.pk,
            membership_tier=self.affordable.pk,
            payment_method="mpesa",
            payment_frequency=Membership.PaymentFrequency.ONCE,
            privacy_consent=True,
        )
        data.update(overrides)
        return data

    def test_the_dpa_consent_gate_refuses_submission(self):
        """forms.py:360-369 -- required=True means the form itself
        refuses, not just the UI."""
        data = self._data()
        del data["privacy_consent"]
        form = AlumniRegistrationForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("privacy_consent", form.errors)

    def test_a_crafted_installment_amount_cannot_override_the_tier_fee(self):
        """forms.py:375-382 -- ONCE strips the value rather than trusting
        it to be blank, because the view does
        `cleaned_data.get("installment_amount") or tier.fee`."""
        form = AlumniRegistrationForm(data=self._data(installment_amount="1.00"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["installment_amount"])

    def test_a_recurring_frequency_requires_an_amount(self):
        form = AlumniRegistrationForm(data=self._data(
            payment_frequency=Membership.PaymentFrequency.MONTHLY
        ))

        self.assertFalse(form.is_valid())
        self.assertIn("installment_amount", form.errors)

    def test_mpesa_is_refused_above_the_fee_ceiling(self):
        """MembershipTier.allows_mpesa is fee-based: fee <= 100000."""
        self.assertFalse(self.expensive.allows_mpesa)
        form = AlumniRegistrationForm(data=self._data(
            membership_tier=self.expensive.pk, payment_method="mpesa"
        ))

        self.assertFalse(form.is_valid())
        self.assertIn("M-Pesa", form.errors["payment_method"][0])
        self.assertIn("Bank Transfer", form.errors["payment_method"][0])

    def test_bank_transfer_is_accepted_above_the_ceiling(self):
        form = AlumniRegistrationForm(data=self._data(
            membership_tier=self.expensive.pk,
            payment_method="bank_transfer",
        ))
        self.assertTrue(form.is_valid(), form.errors)

    def test_finding_k_lump_sum_registration_may_leave_the_amount_blank(self):
        """Guards the finding-K fix.

        AlumniProfileForm.__init__ rebuilds every field's required flag
        from an optional_fields allow-list that knows nothing about the
        subscription fields this subclass adds, so it was silently
        overriding installment_amount's required=False. A member
        registering with "Once" and leaving the amount blank -- exactly
        what the help text tells them to do -- was refused, blocking the
        lump-sum registration path at the form.

        AlumniRegistrationForm.__init__ now re-asserts it.
        """
        data = self._data()
        self.assertNotIn("installment_amount", data)

        form = AlumniRegistrationForm(data=data)

        self.assertTrue(form.is_valid(), form.errors)
        # clean() strips it for ONCE regardless, so the view still falls
        # back to tier.fee.
        self.assertIsNone(form.cleaned_data["installment_amount"])

    def test_the_other_subscription_fields_stay_required(self):
        """The fix re-asserts ONE field. The inherited loop is right about
        the rest, and they must not be loosened with it."""
        form = AlumniRegistrationForm()
        for name in ("membership_tier", "payment_method", "payment_frequency",
                     "privacy_consent"):
            with self.subTest(field=name):
                self.assertTrue(form.fields[name].required)
        self.assertFalse(form.fields["installment_amount"].required)
        # The sibling form declares the identical field and is untouched.
        self.assertFalse(MembershipUpdateForm().fields["installment_amount"].required)


# ── MembershipUpdateForm (5) ─────────────────────────────────────────


class MembershipUpdateFormTests(TestCase):
    """forms.py:399-455. Its clean() duplicates AlumniRegistrationForm's
    verbatim (finding I) -- both are exercised independently for that
    reason."""

    def setUp(self):
        self.affordable = _annual_tier(name="Full Annual Member", fee=2000)
        self.expensive = _life_tier(name="Platinum Life Membership", fee=500000)

    def _data(self, **overrides):
        data = {
            "membership_tier": self.affordable.pk,
            "payment_method": "mpesa",
            "payment_frequency": Membership.PaymentFrequency.ONCE,
        }
        data.update(overrides)
        return data

    def test_a_valid_renewal_is_accepted(self):
        form = MembershipUpdateForm(data=self._data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_once_strips_a_crafted_installment_amount(self):
        form = MembershipUpdateForm(data=self._data(installment_amount="0.01"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["installment_amount"])

    def test_a_recurring_frequency_requires_an_amount(self):
        form = MembershipUpdateForm(data=self._data(
            payment_frequency=Membership.PaymentFrequency.QUARTERLY
        ))
        self.assertFalse(form.is_valid())
        self.assertIn("installment_amount", form.errors)

    def test_mpesa_is_refused_above_the_fee_ceiling(self):
        form = MembershipUpdateForm(data=self._data(
            membership_tier=self.expensive.pk, payment_method="mpesa"
        ))
        self.assertFalse(form.is_valid())
        self.assertIn("payment_method", form.errors)

    def test_an_inactive_tier_cannot_be_submitted(self):
        """The queryset filters is_active=True (forms.py:408), and
        ModelChoiceField re-validates against it -- so a hand-built POST
        naming a retired tier is refused."""
        retired = _annual_tier(name="Retired Tier", fee=1000)
        retired.is_active = False
        retired.save(update_fields=["is_active"])

        form = MembershipUpdateForm(data=self._data(membership_tier=retired.pk))

        self.assertFalse(form.is_valid())
        self.assertIn("membership_tier", form.errors)


# ── ProfileClaimSearchForm (4) + ProfileClaimCodeForm (3) ────────────


class ProfileClaimSearchFormTests(TestCase):
    """forms.py:458-489."""

    def test_neither_field_is_rejected(self):
        form = ProfileClaimSearchForm(data={"email": "", "phone": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("Enter an email address, a phone number, or both", str(form.errors))

    def test_email_alone_is_enough(self):
        form = ProfileClaimSearchForm(data={"email": "wanjiku@example.com"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_phone_alone_is_enough_and_is_normalised(self):
        form = ProfileClaimSearchForm(data={"phone": "0712345678"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone"], "+254712345678")

    def test_an_invalid_phone_is_rejected(self):
        form = ProfileClaimSearchForm(data={"phone": "abc"})
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)


class ProfileClaimCodeFormTests(TestCase):
    """forms.py:492-509."""

    def test_a_six_digit_code_is_accepted(self):
        form = ProfileClaimCodeForm(data={"code": "483920"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_non_numeric_code_is_rejected(self):
        form = ProfileClaimCodeForm(data={"code": "48A920"})
        self.assertFalse(form.is_valid())
        self.assertIn("6-digit numeric code", str(form.errors["code"]))

    def test_a_short_code_is_rejected(self):
        form = ProfileClaimCodeForm(data={"code": "4839"})
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)


# ── AlumniDigitalIDApplicationForm (2) ───────────────────────────────


@override_settings(MEDIA_ROOT=_forms_media_root)
class AlumniDigitalIDApplicationFormTests(TestCase):
    """forms.py:512-530 -- one editable field, made required in __init__."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_forms_media_root, ignore_errors=True)
        super().tearDownClass()

    def test_the_photo_is_required(self):
        form = AlumniDigitalIDApplicationForm(data={}, files={})
        self.assertFalse(form.is_valid())
        self.assertIn("digital_id_photo", form.errors)

    def test_a_real_image_is_accepted(self):
        """A genuine PNG, not a placeholder blob -- ImageField reads it
        back through PIL, as the QR-badge pass found the hard way.

        FINDING J, noted: nothing here limits size or dimensions.
        """
        upload = _Upload("id.png", _png_bytes(), content_type="image/png")
        form = AlumniDigitalIDApplicationForm(data={}, files={"digital_id_photo": upload})

        self.assertTrue(form.is_valid(), form.errors)


class AlumniRegisterViewFormKwargsTests(TestCase):
    """views.py -- AlumniRegisterView.get_form_kwargs is where finding F
    is actually fixed. The form-level tests above assert the consequence;
    this asserts the cause."""

    def test_the_form_instance_carries_the_registrant(self):
        from django.test import RequestFactory

        from apps.home.views import AlumniRegisterView

        user = _make_user("form.kwargs@example.com")
        request = RequestFactory().get("/", HTTP_HOST=PUBLIC_HOST)
        request.user = user

        view = AlumniRegisterView()
        view.request = request
        view.object = None

        kwargs = view.get_form_kwargs()

        self.assertEqual(kwargs["instance"].user_id, user.pk)
        # Still unsaved, so AlumniProfileForm.__init__'s prefill branch
        # stays correctly skipped and get_initial keeps seeding the form.
        self.assertTrue(kwargs["instance"]._state.adding)
