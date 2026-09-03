from django.test import SimpleTestCase

from apps.user.phone import (
    InvalidPhoneNumber,
    normalize_phone,
    try_normalize_phone,
)


class NormalizePhoneTests(SimpleTestCase):
    """0.2's shared normalize function.

    The property that matters is not "does it parse" but "does every
    spelling of one number collapse to one byte-identical string" — that is
    what makes a unique constraint and a phone-based login backend agree.
    """

    CANONICAL = "+254712345678"

    # Every way this one number reaches us: typed by a member, sent by
    # M-Pesa, pasted with separators, dialled internationally.
    SPELLINGS = [
        "+254712345678",
        "254712345678",
        "0712345678",
        "712345678",
        "+254 712 345 678",
        "0712-345-678",
        "  0712345678  ",
        "00254712345678",
        "(0712) 345 678",
    ]

    def test_every_spelling_collapses_to_one_string(self):
        results = {normalize_phone(s) for s in self.SPELLINGS}
        self.assertEqual(
            results,
            {self.CANONICAL},
            "spellings diverged — a unique constraint would not catch the duplicate",
        )

    def test_output_keeps_the_plus(self):
        # Storage is E.164 *with* the plus; only the Daraja call site strips it.
        self.assertTrue(normalize_phone("0712345678").startswith("+"))

    def test_is_idempotent(self):
        once = normalize_phone("0712345678")
        self.assertEqual(normalize_phone(once), once)

    def test_accepts_the_011_range(self):
        # Safaricom's newer 011x block — valid, and easy to miss with a
        # hand-rolled ^\+?254[17]\d{8}$ style regex.
        self.assertEqual(normalize_phone("0110123456"), "+254110123456")

    def test_accepts_a_phonenumber_object(self):
        # PhoneNumberField hands back a PhoneNumber, not a str; save() must
        # be able to re-normalize its own stored value without special-casing.
        import phonenumbers

        parsed = phonenumbers.parse("0712345678", "KE")
        self.assertEqual(normalize_phone(parsed), self.CANONICAL)


class RejectsInvalidInputTests(SimpleTestCase):
    REJECTED = {
        "empty": "",
        "whitespace only": "   ",
        "letters": "not a phone",
        "too short": "071234567",
        "too long": "07123456789",
        "unassigned prefix": "0812345678",
        "digits only, no country": "12345",
    }

    def test_invalid_input_raises(self):
        for label, value in self.REJECTED.items():
            with self.subTest(case=label):
                with self.assertRaises(InvalidPhoneNumber):
                    normalize_phone(value)

    def test_none_raises(self):
        with self.assertRaises(InvalidPhoneNumber):
            normalize_phone(None)

    def test_error_is_a_validation_error(self):
        # Model.full_clean() and ModelForm must surface this as a field
        # error without an adapter — that is why it subclasses ValidationError.
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            normalize_phone("nonsense")


class TryNormalizePhoneTests(SimpleTestCase):
    """The lookup-path wrapper the 0.4 auth backend will use."""

    def test_returns_canonical_for_valid_input(self):
        self.assertEqual(try_normalize_phone("0712345678"), "+254712345678")

    def test_returns_none_instead_of_raising(self):
        for value in ["", None, "not a phone", "0812345678"]:
            with self.subTest(value=value):
                self.assertIsNone(try_normalize_phone(value))

    def test_agrees_with_normalize_phone(self):
        # The two must never drift: same input, same output.
        self.assertEqual(
            try_normalize_phone("00254712345678"),
            normalize_phone("00254712345678"),
        )


# ─────────────────────────────────────────────────────────────────────
# QA 500 sweep (2026-09-01) -- the UserProfile invariant.
# Guards qa_500_report.md findings 4 and 5: apps/user/signals.py creates
# a UserProfile for every new User, on every creation path.
# ─────────────────────────────────────────────────────────────────────

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.user.models import UserProfile
from apps.user.signals import ensure_user_profile

User = get_user_model()


class EnsureUserProfileSignalTests(TestCase):
    """Every creation path yields a profile.

    These four paths are the reason this is a post_save receiver rather
    than a UserManager override: only the first goes through the
    manager, and the others are exactly how today's profile-less
    accounts were made.
    """

    def test_create_user_yields_a_profile(self):
        user = User.objects.create_user(email="via.manager@example.com")
        self.assertTrue(UserProfile.objects.filter(pk=user.pk).exists())

    def test_create_superuser_yields_a_profile(self):
        user = User.objects.create_superuser(
            email="via.superuser@example.com", password="x"
        )
        self.assertTrue(UserProfile.objects.filter(pk=user.pk).exists())

    def test_objects_create_yields_a_profile(self):
        """A UserManager override would miss this."""
        user = User.objects.create(email="via.objects.create@example.com")
        self.assertTrue(UserProfile.objects.filter(pk=user.pk).exists())

    def test_direct_save_yields_a_profile(self):
        """As would this -- the shape the admin's add form uses."""
        user = User(email="via.save@example.com")
        user.set_unusable_password()
        user.save()
        self.assertTrue(UserProfile.objects.filter(pk=user.pk).exists())

    def test_exactly_one_profile_per_user(self):
        user = User.objects.create_user(email="single@example.com")
        self.assertEqual(UserProfile.objects.filter(pk=user.pk).count(), 1)

    def test_resaving_a_user_does_not_create_a_second(self):
        """created=False on every later save, so the receiver returns
        early -- and UserProfile's pk IS the user's pk, so a second row
        could not exist anyway."""
        user = User.objects.create_user(email="resaved@example.com")
        user.is_active = False
        user.save()
        self.assertEqual(UserProfile.objects.filter(pk=user.pk).count(), 1)

    def test_receiver_is_idempotent_alongside_the_adapter(self):
        """apps/user/adapter.py:111 get_or_creates the profile in the
        same request; running the receiver again must not raise."""
        user = User.objects.create_user(email="adapter.race@example.com")
        ensure_user_profile(sender=User, instance=user, created=True)
        self.assertEqual(UserProfile.objects.filter(pk=user.pk).count(), 1)

    def test_raw_save_creates_nothing(self):
        """loaddata fires post_save before related tables are populated,
        so the receiver must stand down for raw saves."""
        user = User.objects.create_user(email="fixture.load@example.com")
        UserProfile.objects.filter(pk=user.pk).delete()
        ensure_user_profile(sender=User, instance=user, created=True, raw=True)
        self.assertFalse(UserProfile.objects.filter(pk=user.pk).exists())

    def test_no_identity_data_is_invented(self):
        """Names stay blank rather than being derived from the e-mail,
        and neither DPA-2019 consent flag is pre-granted."""
        user = User.objects.create_user(email="jane.doe@example.com")
        profile = user.profile
        self.assertEqual(profile.given_name, "")
        self.assertEqual(profile.family_name, "")
        self.assertNotIn("jane", profile.display_name.lower())
        self.assertFalse(profile.sms_opt_in)
        self.assertFalse(profile.email_opt_in)
        self.assertIsNone(profile.consent_given_at)
        self.assertEqual(profile.nationality, "Kenyan")


# ─────────────────────────────────────────────────────────────────────
# The backfill data migration (apps/user/migrations/0002).
# Exercises the migration's own function against the real model
# registry, rather than asserting on migration bookkeeping -- what
# matters is that the rows land, exactly once, and that nothing existing
# is disturbed.
# ─────────────────────────────────────────────────────────────────────

from importlib import import_module

from django.apps import apps as global_apps

_backfill_migration = import_module(
    "apps.user.migrations.0002_backfill_user_profiles"
)


def _make_profileless_user(email):
    """An account as it existed before apps/user/signals.py.

    The signal now creates a profile for every new User, so the legacy
    state has to be constructed by removing it again -- there is no
    longer any way to make one directly.
    """
    user = User.objects.create_user(email=email)
    UserProfile.objects.filter(pk=user.pk).delete()
    return user


class BackfillUserProfilesMigrationTests(TestCase):
    """qa_500_report findings 4 and 5 -- the backlog, not the intake."""

    def _run(self):
        _backfill_migration.backfill(global_apps, None)

    def test_backfills_a_profile_less_account(self):
        user = _make_profileless_user("legacy@example.com")
        self.assertFalse(UserProfile.objects.filter(pk=user.pk).exists())

        self._run()

        self.assertTrue(UserProfile.objects.filter(pk=user.pk).exists())

    def test_backfilled_profile_invents_no_data(self):
        user = _make_profileless_user("legacy.blank@example.com")
        self._run()

        profile = UserProfile.objects.get(pk=user.pk)
        self.assertEqual(profile.given_name, "")
        self.assertEqual(profile.family_name, "")
        self.assertFalse(profile.sms_opt_in)
        self.assertFalse(profile.email_opt_in)
        self.assertIsNone(profile.consent_given_at)

    def test_running_twice_is_a_no_op(self):
        user = _make_profileless_user("legacy.twice@example.com")
        self._run()
        self._run()
        self.assertEqual(UserProfile.objects.filter(pk=user.pk).count(), 1)

    def test_inert_when_every_account_already_has_one(self):
        user = User.objects.create_user(email="already@example.com")
        profile = user.profile
        profile.given_name = "Already"
        profile.family_name = "Present"
        profile.save(update_fields=["given_name", "family_name"])

        self._run()

        profile.refresh_from_db()
        self.assertEqual(profile.given_name, "Already")
        self.assertEqual(profile.family_name, "Present")
        self.assertEqual(UserProfile.objects.filter(pk=user.pk).count(), 1)

    def test_existing_profiles_are_left_alone(self):
        """A mixed database: one legacy account, one intact."""
        legacy = _make_profileless_user("mixed.legacy@example.com")
        intact = User.objects.create_user(email="mixed.intact@example.com")
        profile = intact.profile
        profile.given_name = "Wanjiku"
        profile.family_name = "Kamau"
        profile.save(update_fields=["given_name", "family_name"])

        self._run()

        self.assertTrue(UserProfile.objects.filter(pk=legacy.pk).exists())
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "Wanjiku Kamau")

    def test_reverse_does_not_delete_anything(self):
        """unbackfill is a deliberate no-op -- a profile created by this
        migration may have been edited since, and reversing must not
        destroy real data."""
        user = _make_profileless_user("legacy.reverse@example.com")
        self._run()

        _backfill_migration.unbackfill(global_apps, None)

        self.assertTrue(UserProfile.objects.filter(pk=user.pk).exists())


# ─────────────────────────────────────────────────────────────────────
# Coverage priority 3 -- apps/user/adapter.py.
#
# Google OAuth is the only authentication method in this project, and
# the QA-500 sweep tested the gates rather than the door. These
# characterise what the adapter ACTUALLY does. See
# docs/coverage-phase1-adapter-step1-2026-09-01.md.
#
# No live OAuth: both adapters only ever see an already-constructed
# SocialLogin, built here from real allauth classes so is_existing /
# state / connect() semantics stay genuine.
#
# The domain constants are read into module globals at import
# (adapter.py:17-33), so override_settings cannot reach them -- they are
# patched on apps.user.adapter directly.
#
# ⌂ marks a test that needs an lvh.me-family host or an explicit urlconf.
# ─────────────────────────────────────────────────────────────────────

from datetime import date, timedelta
from unittest import mock

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, override_settings
from django.urls import NoReverseMatch, reverse, set_urlconf
from django.utils import timezone

from apps.staff.models import Employee, ServiceUnit
from apps.user import adapter as adapter_module
from apps.user.adapter import CustomAccountAdapter, CustomSocialAccountAdapter

GOOGLE_EXTRA = {
    "sub": "google-sub-0001",
    "email": "wanjiku.kamau@uonbi.ac.ke",
    "email_verified": True,
    "given_name": "Wanjiku",
    "family_name": "Kamau",
    "picture": "https://example.test/photo.jpg",
    "locale": "en",
}


def _request(host="lvh.me", subdomain=None, user=None, path="/"):
    """A request shaped the way SubdomainRoutingMiddleware leaves one.

    .subdomain is set by hand because the middleware is not in play when
    an adapter method is called directly; session and message storage
    are attached because messages.error() needs request._messages.
    """
    request = RequestFactory().get(path, HTTP_HOST=host)
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    request._messages = FallbackStorage(request)
    request.subdomain = subdomain
    request.user = user if user is not None else AnonymousUser()
    return request


def _sociallogin(user, process="login", **overrides):
    extra = dict(GOOGLE_EXTRA)
    # User.google_sub is unique, so each identity needs its own sub --
    # sharing one across two fixtures raises IntegrityError.
    email = overrides.get("email") or getattr(user, "email", None) or GOOGLE_EXTRA["email"]
    extra["email"] = email
    extra["sub"] = f"google-sub-{email}"
    extra.update(overrides)
    account = SocialAccount(
        provider="google", uid=extra["sub"], extra_data=extra
    )
    sociallogin = SocialLogin(user=user, account=account)
    sociallogin.state = {"process": process}
    return sociallogin


def _sub_for(email):
    """Mirrors the per-identity sub _sociallogin() derives."""
    return f"google-sub-{email}"


def _saved_user(email="wanjiku.kamau@uonbi.ac.ke"):
    return User.objects.create_user(email=email)


def _employee_for(user, complete=False):
    employee = Employee.objects.create(user=user)
    if complete:
        unit = ServiceUnit.objects.create(name=f"Unit {user.pk}")
        employee.staff_id = "STF-0001"
        employee.staff_track = Employee.StaffTrack.SERVICE
        employee.service_unit = unit
        employee.save()
        profile = user.profile
        profile.date_of_birth = date(1990, 1, 1)
        profile.save(update_fields=["date_of_birth"])
    return employee


# ── pre_social_login: domain restriction (5) ─────────────────────────


class PreSocialLoginDomainRestrictionTests(TestCase):
    """adapter.py:417-434. Staff and students are restricted to
    institutional domains; the apex admits any Google account, because
    most alumni lose their @uonbi.ac.ke address at graduation.

    The restriction is DISABLED in this environment -- .env sets
    RESTRICT_GOOGLE_LOGIN_DOMAINS=False, exactly as settings.py:532-534
    documents for development -- so these tests force it on. Without
    that they would pass while asserting nothing.
    """

    def setUp(self):
        self.adapter = CustomSocialAccountAdapter()
        patcher = mock.patch.object(
            adapter_module, "RESTRICT_GOOGLE_LOGIN_DOMAINS", True
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_institutional_domain_is_admitted_on_staff(self):  # ⌂
        user = _saved_user()
        _employee_for(user)
        request = _request(host="staff.lvh.me", subdomain="staff")
        self.adapter.pre_social_login(request, _sociallogin(user))

    def test_foreign_domain_is_rejected_on_staff(self):  # ⌂
        user = _saved_user("someone@gmail.com")
        request = _request(host="staff.lvh.me", subdomain="staff")

        with self.assertRaises(ImmediateHttpResponse) as caught:
            self.adapter.pre_social_login(
                request, _sociallogin(user, email="someone@gmail.com")
            )
        self.assertIn(reverse("account_login"), caught.exception.response["Location"])

    def test_students_domain_rule_is_distinct_from_staff(self):  # ⌂
        student = _saved_user("learner@students.uonbi.ac.ke")
        request = _request(host="students.lvh.me", subdomain="students")
        # Admitted.
        self.adapter.pre_social_login(
            request, _sociallogin(student, email="learner@students.uonbi.ac.ke")
        )

        # A plain staff address is NOT a student address.
        staffer = _saved_user("lecturer@uonbi.ac.ke")
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(
                _request(host="students.lvh.me", subdomain="students"),
                _sociallogin(staffer, email="lecturer@uonbi.ac.ke"),
            )

    def test_any_domain_is_admitted_on_the_public_site(self):  # ⌂
        """Deliberate: the apex is a public alumni association."""
        alumna = _saved_user("retired.alumna@gmail.com")
        request = _request(host="lvh.me", subdomain=None)
        self.adapter.pre_social_login(
            request, _sociallogin(alumna, email="retired.alumna@gmail.com")
        )

    def test_restriction_can_be_switched_off(self):  # ⌂
        """RESTRICT_GOOGLE_LOGIN_DOMAINS is a module global, so it is
        patched here rather than via override_settings."""
        user = _saved_user("someone@gmail.com")
        _employee_for(user)
        request = _request(host="staff.lvh.me", subdomain="staff")

        with mock.patch.object(
            adapter_module, "RESTRICT_GOOGLE_LOGIN_DOMAINS", False
        ):
            self.adapter.pre_social_login(
                request, _sociallogin(user, email="someone@gmail.com")
            )


# ── pre_social_login: staff login/signup gate (3) ────────────────────


class PreSocialLoginStaffGateTests(TestCase):
    """adapter.py:436-451. On staff, login requires an existing Employee
    and signup requires the absence of one."""

    def setUp(self):
        self.adapter = CustomSocialAccountAdapter()
        self.request = _request(host="staff.lvh.me", subdomain="staff")

    def test_login_without_an_employee_record_is_sent_to_signup(self):  # ⌂
        user = _saved_user()
        with self.assertRaises(ImmediateHttpResponse) as caught:
            self.adapter.pre_social_login(self.request, _sociallogin(user, process="login"))
        self.assertIn(reverse("account_signup"), caught.exception.response["Location"])

    def test_signup_with_an_existing_employee_is_sent_to_login(self):  # ⌂
        user = _saved_user()
        _employee_for(user)
        with self.assertRaises(ImmediateHttpResponse) as caught:
            self.adapter.pre_social_login(self.request, _sociallogin(user, process="signup"))
        self.assertIn(reverse("account_login"), caught.exception.response["Location"])

    def test_login_with_an_employee_record_proceeds(self):  # ⌂
        user = _saved_user()
        _employee_for(user)
        self.adapter.pre_social_login(self.request, _sociallogin(user, process="login"))


# ── pre_social_login: record creation (4) ────────────────────────────


class PreSocialLoginRecordCreationTests(TestCase):
    """adapter.py:459-491."""

    def setUp(self):
        self.adapter = CustomSocialAccountAdapter()

    def test_existing_staff_login_ensures_profile_and_employee(self):  # ⌂
        user = _saved_user()
        _employee_for(user)
        request = _request(host="staff.lvh.me", subdomain="staff")

        self.adapter.pre_social_login(request, _sociallogin(user))

        user.refresh_from_db()
        self.assertEqual(user.profile.given_name, "Wanjiku")
        self.assertEqual(user.profile.family_name, "Kamau")
        self.assertTrue(Employee.objects.filter(user=user).exists())

    def test_existing_apex_login_creates_no_employee(self):  # ⌂
        user = _saved_user("alumna@gmail.com")
        request = _request(host="lvh.me", subdomain=None)

        self.adapter.pre_social_login(
            request, _sociallogin(user, email="alumna@gmail.com")
        )

        self.assertFalse(Employee.objects.filter(user=user).exists())
        user.refresh_from_db()
        self.assertEqual(user.profile.given_name, "Wanjiku")

    def test_google_account_fields_are_synced_on_an_existing_login(self):
        """adapter.py:129-146 records the 2026-08-07 bug this fixes: these
        three fields used to be set only for brand-new signups, so an
        existing account's stayed permanently blank."""
        user = _saved_user("alumna@gmail.com")
        self.assertEqual(user.auth_provider, User.AuthProvider.EMAIL)

        self.adapter.pre_social_login(
            _request(subdomain=None),
            _sociallogin(user, email="alumna@gmail.com"),
        )

        user.refresh_from_db()
        self.assertEqual(user.google_sub, _sub_for("alumna@gmail.com"))
        self.assertTrue(user.email_verified)
        self.assertEqual(user.auth_provider, User.AuthProvider.GOOGLE)

    def test_a_verified_claim_connects_instead_of_creating_a_duplicate(self):
        """adapter.py:43-80 -- the "find my profile" OTP flow."""
        from apps.home.models import ProfileClaimVerification

        claimed = _saved_user("legacy.member@gmail.com")
        claim = ProfileClaimVerification.objects.create(
            user=claimed,
            status=ProfileClaimVerification.Status.VERIFIED,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        request = _request(subdomain=None)
        request.session["claim_verification_id"] = str(claim.pk)
        request.session["claim_verified_expires"] = (
            timezone.now() + timedelta(minutes=10)
        ).isoformat()
        request.session.save()

        before = User.objects.count()
        # An unsaved user is what allauth hands over for a new identity.
        self.adapter.pre_social_login(
            request, _sociallogin(User(email="legacy.member@gmail.com"))
        )

        self.assertEqual(User.objects.count(), before)
        claim.refresh_from_db()
        self.assertEqual(claim.status, ProfileClaimVerification.Status.CONSUMED)


# ── save_user (3) ────────────────────────────────────────────────────


class SaveUserTests(TestCase):
    """adapter.py:494-518 -- brand-new accounts only."""

    def setUp(self):
        self.adapter = CustomSocialAccountAdapter()

    def test_new_signup_populates_user_and_profile_from_google(self):
        request = _request(subdomain=None)
        sociallogin = _sociallogin(User(email=GOOGLE_EXTRA["email"]))

        user = self.adapter.save_user(request, sociallogin)

        self.assertEqual(user.google_sub, _sub_for(GOOGLE_EXTRA["email"]))
        self.assertEqual(user.auth_provider, User.AuthProvider.GOOGLE)
        self.assertEqual(user.profile.given_name, "Wanjiku")
        self.assertEqual(user.profile.google_photo_url, GOOGLE_EXTRA["picture"])

    def test_employee_is_created_only_on_the_staff_subdomain(self):  # ⌂
        staff_user = self.adapter.save_user(
            _request(host="staff.lvh.me", subdomain="staff"),
            _sociallogin(User(email="new.staff@uonbi.ac.ke")),
        )
        apex_user = self.adapter.save_user(
            _request(subdomain=None),
            _sociallogin(User(email="new.alumna@gmail.com")),
        )

        self.assertTrue(Employee.objects.filter(user=staff_user).exists())
        self.assertFalse(Employee.objects.filter(user=apex_user).exists())

    def test_adapter_and_signal_yield_exactly_one_profile(self):
        """The interaction the UserProfile invariant created.

        apps/user/signals.py creates a blank-named profile the moment the
        User is saved; _ensure_profile's getattr guard (adapter.py:100)
        then finds it, skips creation, and falls through to the
        extra_data block at :117-123 which fills the names. One row, and
        the Google names still land.
        """
        user = self.adapter.save_user(
            _request(subdomain=None), _sociallogin(User(email=GOOGLE_EXTRA["email"]))
        )

        self.assertEqual(UserProfile.objects.filter(pk=user.pk).count(), 1)
        self.assertEqual(user.profile.given_name, "Wanjiku")
        self.assertEqual(user.profile.family_name, "Kamau")


# ── CustomAccountAdapter.get_login_redirect_url (6) ──────────────────


class LoginRedirectResolutionTests(TestCase):
    """adapter.py:289-346."""

    def setUp(self):
        self.adapter = CustomAccountAdapter()

    def test_superuser_goes_straight_to_admin_without_an_employee_stub(self):
        """adapter.py:299-305 -- gating superusers on Employee
        completeness used to auto-create an empty stub on every login."""
        superuser = User.objects.create_superuser(
            email="root@example.com", password="x"
        )
        request = _request(subdomain=None, user=superuser)

        self.assertEqual(
            self.adapter.get_login_redirect_url(request), reverse("admin:index")
        )
        self.assertFalse(Employee.objects.filter(user=superuser).exists())

    def test_admin_staff_with_incomplete_employee_gets_an_absolute_staff_url(self):  # ⌂
        staffer = _saved_user("admin.staff@uonbi.ac.ke")
        staffer.is_staff = True
        staffer.save(update_fields=["is_staff"])
        request = _request(host="lvh.me", subdomain=None, user=staffer)

        url = self.adapter.get_login_redirect_url(request)

        self.assertTrue(url.startswith("http://staff.lvh.me/"))
        self.assertIn("complete-profile", url)

    def test_admin_staff_without_alumni_profile_on_the_staff_host(self):  # ⌂
        """Guards the finding-B fix.

        adapter.py:220 used to reverse "home:uon_alumni_register" with no
        urlconf=, while the branch immediately above it built an absolute
        staff URL precisely because the host may differ. Under the staff
        subdomain's urlconf (apps.staff.site_urls) the `home` namespace
        does not exist, so it raised NoReverseMatch -- a 500 on login for
        an is_staff non-superuser who had finished onboarding but had no
        AlumniProfile. It is now pinned to main.urls.

        The redirect is an ABSOLUTE apex URL, not a bare path: this
        function runs for any is_staff login regardless of host, so a
        path would be requested from whichever host the browser is on
        and 404 against the staff urlconf. _apex_url() mirrors what
        _staff_subdomain_url() does for the branch above.
        """
        staffer = _saved_user("complete.staff@uonbi.ac.ke")
        staffer.is_staff = True
        staffer.save(update_fields=["is_staff"])
        _employee_for(staffer, complete=True)
        self.assertFalse(hasattr(staffer, "alumni_profile"))

        request = _request(host="staff.lvh.me", subdomain="staff", user=staffer)
        set_urlconf("apps.staff.site_urls")
        try:
            url = self.adapter.get_login_redirect_url(request)
        finally:
            set_urlconf(None)

        self.assertEqual(
            url,
            "http://lvh.me"
            + reverse("home:uon_alumni_register", urlconf="main.urls"),
        )

    def test_plain_user_on_staff_is_routed_by_completeness(self):  # ⌂
        user = _saved_user()
        employee = _employee_for(user)
        request = _request(host="staff.lvh.me", subdomain="staff", user=user)

        incomplete = self.adapter.get_login_redirect_url(request)
        self.assertIn(str(employee.id), incomplete)
        self.assertIn("complete-profile", incomplete)

        unit = ServiceUnit.objects.create(name="Registry")
        employee.staff_id = "STF-9"
        employee.staff_track = Employee.StaffTrack.SERVICE
        employee.service_unit = unit
        employee.save()
        profile = user.profile
        profile.date_of_birth = date(1990, 1, 1)
        profile.save(update_fields=["date_of_birth"])

        user.refresh_from_db()
        request = _request(host="staff.lvh.me", subdomain="staff", user=user)
        self.assertEqual(
            self.adapter.get_login_redirect_url(request),
            Employee.objects.get(pk=employee.pk).get_absolute_url(),
        )

    def test_plain_user_on_the_apex_without_an_alumni_profile(self):  # ⌂
        user = _saved_user("alumna@gmail.com")
        request = _request(host="lvh.me", subdomain=None, user=user)

        self.assertEqual(
            self.adapter.get_login_redirect_url(request),
            reverse("home:uon_alumni_register"),
        )

    def test_students_routing_and_post_login_next(self):  # ⌂
        from apps.student.models import Student

        user = _saved_user("learner@students.uonbi.ac.ke")
        request = _request(host="students.lvh.me", subdomain="students", user=user)

        # No Student record yet -- the bare name pinned to the inner
        # module (adapter.py:36 STUDENT_URLCONF).
        self.assertEqual(
            self.adapter.get_login_redirect_url(request),
            reverse("register", urlconf=adapter_module.STUDENT_URLCONF),
        )

        Student.objects.create(user=user, registration_no="REG/001/2026")
        user.refresh_from_db()
        request = _request(host="students.lvh.me", subdomain="students", user=user)
        request.session["post_login_next"] = "https://students.lvh.me/dashboard/"
        request.session.save()

        # https, not http: post_login_next is filtered through
        # is_safe_url(), which sets require_https=not settings.DEBUG
        # (adapter.py:285), so an http next-URL is refused in production.
        self.assertEqual(
            self.adapter.get_login_redirect_url(request),
            "https://students.lvh.me/dashboard/",
        )
        self.assertNotIn("post_login_next", request.session)

    def test_an_unsafe_post_login_next_is_ignored(self):  # ⌂
        """A stashed URL pointing off-site must not be honoured."""
        from apps.student.models import Student

        user = _saved_user("safe.learner@students.uonbi.ac.ke")
        Student.objects.create(user=user, registration_no="REG/002/2026")
        request = _request(host="students.lvh.me", subdomain="students", user=user)
        request.session["post_login_next"] = "https://evil.example.com/"
        request.session.save()

        self.assertNotEqual(
            self.adapter.get_login_redirect_url(request),
            "https://evil.example.com/",
        )


# ── get_signup_redirect_url (2) ──────────────────────────────────────


class SignupRedirectResolutionTests(TestCase):
    """adapter.py:348-386 -- form-based signups only."""

    def setUp(self):
        self.adapter = CustomAccountAdapter()

    def test_staff_signup_always_goes_to_complete_profile(self):  # ⌂
        user = _saved_user()
        request = _request(host="staff.lvh.me", subdomain="staff", user=user)

        url = self.adapter.get_signup_redirect_url(request)

        self.assertIn("complete-profile", url)
        self.assertTrue(Employee.objects.filter(user=user).exists())

    def test_students_signup_always_goes_to_register(self):  # ⌂
        user = _saved_user("learner@students.uonbi.ac.ke")
        request = _request(host="students.lvh.me", subdomain="students", user=user)

        self.assertEqual(
            self.adapter.get_signup_redirect_url(request),
            reverse("register", urlconf=adapter_module.STUDENT_URLCONF),
        )


# ── is_safe_url / logout / get_connect_redirect_url (3) ──────────────


class SafeUrlAndLogoutTests(TestCase):
    """adapter.py:270-287 and :388-398."""

    def setUp(self):
        self.adapter = CustomAccountAdapter()

    def test_own_hosts_are_safe_and_foreign_hosts_are_not(self):
        """require_https=not settings.DEBUG (adapter.py:285), and the test
        runner forces DEBUG False -- so plain http is refused even for our
        own hosts. That is the production contract."""
        for url in [
            "https://lvh.me/",
            "https://staff.lvh.me/profile/edit/",
            "https://students.lvh.me/dashboard/",
        ]:
            with self.subTest(url=url):
                self.assertTrue(self.adapter.is_safe_url(url))

        self.assertFalse(self.adapter.is_safe_url("https://evil.example.com/"))
        # http is refused outside DEBUG, own host or not.
        self.assertFalse(self.adapter.is_safe_url("http://staff.lvh.me/"))

    @override_settings(DEBUG=True)
    def test_dev_hosts_carry_the_runserver_port(self):
        """adapter.py:281-283 -- url_has_allowed_host_and_scheme does
        exact host matching, so the :8000 variants are enumerated. Both
        that branch and require_https read settings.DEBUG at call time."""
        self.assertTrue(self.adapter.is_safe_url("http://staff.lvh.me:8000/"))

    def test_logout_always_lands_on_the_apex_with_the_port_preserved(self):  # ⌂
        request = _request(host="staff.lvh.me:8000", subdomain="staff")
        self.assertEqual(
            self.adapter.get_logout_redirect_url(request), "http://lvh.me:8000/"
        )


class ConnectRedirectTests(TestCase):
    """adapter.py:523-546 -- get_connect_redirect_url.

    Step 1 recorded a candidate finding here, that the method fell off
    its end and returned None on the apex. That was WRONG: its real last
    line delegates to the base class,

        return super().get_connect_redirect_url(request, socialaccount)

    so the apex correctly yields allauth's connections page. The finding
    is retracted and this test pins the actual behaviour.
    """

    def test_connecting_on_the_apex_falls_back_to_the_connections_page(self):  # ⌂
        user = _saved_user("alumna@gmail.com")
        account = SocialAccount.objects.create(
            user=user, provider="google", uid="google-sub-connect", extra_data={}
        )
        request = _request(host="lvh.me", subdomain=None, user=user)

        result = CustomSocialAccountAdapter().get_connect_redirect_url(request, account)

        self.assertEqual(result, reverse("socialaccount_connections"))
