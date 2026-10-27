# apps/home/crm_forms.py
"""
Forms for the Secretariat Membership CRM (apps/home/crm_views.py).

These are the STAFF-facing counterparts to the member-facing forms in
apps/home/forms.py:

  - MembershipUpdateForm (member-facing) files a *request* -- a new
    pending Membership + Payment the Secretariat later confirms.
  - MembershipStaffForm (here) edits the Membership ROW directly -- tier,
    status, number, dates, issued items -- because a Secretariat officer
    correcting a record is not making a request, they are the authority.

All three reuse main.forms.TailwindStyledFormMixin so inputs match the
rest of the site (call self.apply_tailwind_styling() last in __init__).
"""
from django import forms
from django.db import transaction

from apps.home.forms import AlumniRegistrationForm
from apps.home.models import Membership, MembershipTier, Payment
from apps.user.models import User
from main.forms import TailwindStyledFormMixin

# Native date picker that also round-trips an existing value: DateInput
# needs format="%Y-%m-%d" to pre-fill <input type="date"> from a stored
# date, and input_formats to parse it back on submit.
_DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
_DATE_INPUT_FORMATS = ["%Y-%m-%d"]


def _active_tiers():
    return MembershipTier.objects.filter(is_active=True).order_by("order")


class MembershipStaffForm(TailwindStyledFormMixin, forms.ModelForm):
    """Direct edit of one Membership row by the Secretariat."""

    class Meta:
        model = Membership
        fields = [
            "tier", "status", "membership_number",
            "started_on", "expires_on", "is_lifetime",
            "subscription_amount", "payment_frequency",
            "card_issued", "certificate_issued", "lapel_badge_issued",
            "legacy_signed",
        ]
        widgets = {
            "started_on": _DATE_WIDGET,
            "expires_on": _DATE_WIDGET,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tier"].queryset = _active_tiers()
        self.fields["started_on"].input_formats = _DATE_INPUT_FORMATS
        self.fields["expires_on"].input_formats = _DATE_INPUT_FORMATS
        self.apply_tailwind_styling()


class RecordPaymentForm(TailwindStyledFormMixin, forms.Form):
    """Record a payment against a membership and (optionally) confirm it.

    Confirming calls Payment.mark_as_completed(), which routes through
    services.confirm_payment() -> Membership.activate()/
    record_installment_payment() -- the same single door the Membership
    Admin's "mark completed" action uses. Nothing here charges anything;
    it records a payment the Secretariat has already received.
    """

    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    payment_method = forms.ChoiceField(choices=Payment.PAYMENT_METHODS)
    reference = forms.CharField(
        required=False,
        help_text="M-Pesa receipt code or bank reference (stored on the payment).",
    )
    mark_completed = forms.BooleanField(
        required=False,
        initial=True,
        label="Mark completed now (activates the membership)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_tailwind_styling()


class NewMemberForm(AlumniRegistrationForm):
    """Create a brand-new member from the console (a walk-in / phone / paper
    signup the Secretariat is entering by hand).

    Subclasses the member-facing AlumniRegistrationForm directly (2026-10-27)
    rather than duplicating its ~25 fields -- a walk-in's record should be
    just as complete as someone who registered themselves, and reusing the
    same fields/validation/save() logic is what actually guarantees that,
    rather than two parallel forms quietly drifting apart.

    Two deliberate differences from the base form:
      - `primary_email` replaces the login identity AlumniRegistrationForm
        normally gets for free from an already-authenticated Google user
        (apps/user/adapter.py) -- there's no such user here, so the
        Secretariat supplies the email that becomes the new account's
        login. The inherited `email` field keeps its original meaning,
        "alternate email", exactly as on the member-facing form.
      - `privacy_consent` is REMOVED (DPA 2019): consent cannot be
        pre-granted on someone else's behalf, same reasoning the old
        version of this form already gave.

    Still a plain Form-like save() in spirit -- membership/payment
    creation stays in the view (MembershipCreateView.post), mirroring
    exactly where AlumniRegisterView.form_valid() does the same thing,
    so both entry points activate a membership through the identical
    sequence.
    """

    primary_email = forms.EmailField(
        label="Email",
        help_text="Their login email. A password-free account is created -- "
                   "they set a password or link Google on first login.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["privacy_consent"]
        # Login identity fields first, ahead of everything
        # AlumniProfileForm/AlumniRegistrationForm already ordered.
        self.order_fields(["primary_email", *[f for f in self.fields if f != "primary_email"]])
        self.apply_tailwind_styling()

    def clean_primary_email(self):
        email = self.cleaned_data["primary_email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "A user with this email already exists — open their record and edit "
                "the membership instead of creating a new one."
            )
        return email

    @transaction.atomic
    def save(self, commit=True):
        """Returns the saved AlumniProfile. Creates the User first (an
        unusable password -- they set one / link Google on first login,
        same as the old version of this form), then hands off to
        AlumniProfileForm.save() for everything else, exactly as
        AlumniRegisterView does once Google auth has already created
        the user for it."""
        user = User.objects.create_user(email=self.cleaned_data["primary_email"])
        self.instance.user = user
        return super().save(commit=commit)
