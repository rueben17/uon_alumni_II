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
