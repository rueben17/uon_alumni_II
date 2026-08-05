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
