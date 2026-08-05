"""
Phone-number canonicalization — the single source of truth.

`todo.md` 0.2: "One shared normalize function — both model save() and the
auth backend call it, so registration and login produce byte-identical
strings." Uniqueness on the profile's phone column, and later M-Pesa
reconciliation, are only as reliable as that guarantee — so nothing else in
the project may re-implement this logic, only import it.

Storage format is E.164 *with* the leading '+' (+254712345678). Boundaries
that need a different shape transform at the call site, never at storage:
Daraja, for example, wants 254712345678, which is `str(phone).lstrip("+")`.
"""

from __future__ import annotations

import phonenumbers
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Kenya. Bare national input ("0712345678", "712345678") is interpreted
# against this region; input that already carries a country code is
# unaffected by it.
DEFAULT_REGION = "KE"


class InvalidPhoneNumber(ValidationError):
    """Raised when input cannot be resolved to a valid phone number.

    Subclasses Django's ValidationError so that model.full_clean() and form
    validation surface it as an ordinary field error, with no adapter layer.
    """


def normalize_phone(raw, region: str = DEFAULT_REGION) -> str:
    """Any accepted input -> canonical E.164, e.g. "+254712345678".

    Accepts the forms people and providers actually send:

        "+254712345678"      already canonical
        "254712345678"       M-Pesa / Daraja callbacks (no plus)
        "0712345678"         how Kenyans write their own number
        "712345678"          national number, leading zero dropped
        "+254 712 345 678"   separators of any kind
        "00254712345678"     international dialling prefix

    Raises InvalidPhoneNumber for anything else. Validity is checked with
    is_valid_number(), not is_possible_number(), because this value is
    load-bearing for OTP delivery and payment matching — "plausibly shaped"
    is not good enough when a wrong number means an SMS charge and a member
    who cannot log in.
    """
    if raw is None:
        raise InvalidPhoneNumber(_("Enter a phone number."))

    if isinstance(raw, phonenumbers.PhoneNumber):
        # Already parsed — PhoneNumberField hands back a PhoneNumber, so
        # save() re-normalizing its own stored value lands here. Do NOT
        # round-trip it through str(): the base phonenumbers.PhoneNumber
        # stringifies to the debug form "Country Code: 254 National Number:
        # ...", and the field's subclass stringifies according to the
        # PHONENUMBER_DEFAULT_FORMAT setting — so str() would make the
        # stored format depend on a setting someone could change later.
        parsed = raw
    else:
        text = str(raw).strip()
        if not text:
            raise InvalidPhoneNumber(_("Enter a phone number."))

        # "00" is the international dialling prefix in Kenya and people type
        # it. phonenumbers does NOT treat it as "+" when a region is supplied
        # — it reads "00254712345678" as a national number and produces the
        # nonsense "+2540254712345678". Convert before parsing rather than
        # letting the validity check reject it, so the number survives.
        if text.startswith("00"):
            text = "+" + text[2:]

        try:
            parsed = phonenumbers.parse(text, region)
        except phonenumbers.NumberParseException as exc:
            raise InvalidPhoneNumber(
                _("Enter a valid phone number, for example 0712345678.")
            ) from exc

    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumber(
            _("Enter a valid phone number, for example 0712345678.")
        )

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def try_normalize_phone(raw, region: str = DEFAULT_REGION) -> str | None:
    """Lenient wrapper: canonical E.164, or None if `raw` is not valid.

    For lookup paths — chiefly the 0.4 auth backend, where a malformed
    submission means "no user matches this", not "raise at the user". It
    exists so that callers never hand-roll a try/except around
    normalize_phone() and slowly drift away from it.
    """
    try:
        return normalize_phone(raw, region=region)
    except InvalidPhoneNumber:
        return None
