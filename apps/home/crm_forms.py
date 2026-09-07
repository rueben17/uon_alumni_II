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

from apps.home.models import AlumniProfile, Faculty, Membership, MembershipTier, Payment
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


class NewMemberForm(TailwindStyledFormMixin, forms.Form):
    """Create a brand-new member from the console (a walk-in / phone / paper
    signup the Secretariat is entering by hand).

    Deliberately a plain Form, not a ModelForm: one submit spans three
    tables (User, UserProfile, AlumniProfile) plus a pending Membership,
    and it must go through the same service door
    (services.assign_membership_tier) as every other membership so the
    row is created consistently.

    IMPORTANT (DPA 2019): this bypasses the Google-OAuth onboarding path
    (apps/user/adapter.py), so consent is NOT collected here --
    UserProfile.sms_opt_in / email_opt_in stay False by default, which is
    correct (consent cannot be pre-granted). The account is created with
    an unusable password (create_user(password=None)); the member sets a
    password / links Google on first login. For an EXISTING person, don't
    use this -- open their record and edit the membership instead.
    """

    given_name = forms.CharField(max_length=255, label="First name")
    family_name = forms.CharField(max_length=255, label="Surname")
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False, help_text="e.g. 0712345678")
    student_reg_no = forms.CharField(max_length=50, required=False, label="Registration number")
    graduation_date = forms.DateField(required=False, widget=_DATE_WIDGET, input_formats=_DATE_INPUT_FORMATS)
    faculty = forms.ModelChoiceField(queryset=Faculty.objects.all().order_by("faculty_name"), required=False)
    tier = forms.ModelChoiceField(queryset=_active_tiers(), label="Membership tier")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_tailwind_styling()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "A user with this email already exists — open their record and edit "
                "the membership instead of creating a new one."
            )
        return email

    @transaction.atomic
    def save(self):
        """Returns (user, membership). The membership is PENDING; record a
        payment on the detail page to activate it."""
        from apps.home import services  # local import: services imports models at module load

        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            phone=self.cleaned_data.get("phone") or None,
        )
        # UserProfile is created by apps.user.signals.ensure_user_profile
        # (post_save on User) with blank names -- fetch and fill it rather
        # than creating a second one (the O2O would collide).
        profile = user.profile
        profile.given_name = self.cleaned_data["given_name"]
        profile.family_name = self.cleaned_data["family_name"]
        profile.save(update_fields=["given_name", "family_name"])

        AlumniProfile.objects.create(
            user=user,
            student_reg_no=self.cleaned_data.get("student_reg_no", ""),
            graduation_date=self.cleaned_data.get("graduation_date"),
            faculty=self.cleaned_data.get("faculty"),
        )

        membership = services.assign_membership_tier(user, self.cleaned_data["tier"])
        return user, membership
