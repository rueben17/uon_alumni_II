from decimal import Decimal

from django import forms

from apps.home.models import (
    AlumniProfile, ContactMessage, Membership, MembershipTier, Payment, Qualification,
)
from apps.user.models import Gender, Honorific, User, UserProfile
from apps.user.phone import InvalidPhoneNumber, normalize_phone
from main.forms import TailwindStyledFormMixin, YearAsDateField


class ContactForm(TailwindStyledFormMixin, forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].required = False
        self.fields["name"].help_text = "Your full name."
        self.fields["email"].help_text = "We'll reply to this address."
        self.fields["subject"].help_text = "Optional -- helps us route your message faster."
        self.fields["message"].help_text = "Tell us what's on your mind."
        self.apply_tailwind_styling()


class AlumniProfileForm(TailwindStyledFormMixin, forms.ModelForm):
    """
    Personal fields (title/name/DOB/national ID/contact) live on
    UserProfile now, and phone is the primary login handle on User, not
    the profile (docs/rebuild-schema.md) -- same split as
    apps/staff/forms.py's CompleteProfileForm. __init__/save() fan the
    extra fields out to the right model instead of a single
    ModelForm.Meta.fields list.
    """

    graduation_year = YearAsDateField(required=False, label="Year of Graduation")

    honorific = forms.ChoiceField(choices=Honorific.choices, required=False)
    surname = forms.CharField(max_length=255, label="Surname")
    first_name = forms.CharField(max_length=255)
    middle_name = forms.CharField(max_length=255, required=False)
    maiden_name = forms.CharField(max_length=100, required=False)
    gender = forms.ChoiceField(choices=Gender.choices, required=False)
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    id_passport_no = forms.CharField(max_length=50, label="National ID / Passport No.")
    nationality = forms.CharField(max_length=100, required=False, initial="Kenyan")
    postal_address = forms.CharField(max_length=200, required=False)
    postal_code = forms.CharField(max_length=20, required=False)
    city = forms.CharField(max_length=100, required=False)
    phone_mobile = forms.CharField(max_length=20, label="Mobile Phone")
    phone_alt = forms.CharField(max_length=20, required=False, label="Alternate Phone")
    email = forms.EmailField(required=False, label="Alternate Email")
    receive_newsletter = forms.BooleanField(required=False, initial=False, label="Receive newsletter")
    receive_sms_alerts = forms.BooleanField(required=False, initial=False, label="Receive SMS alerts")

    class Meta:
        model = AlumniProfile
        fields = [
            "current_employer",
            "employment_position",
            "graduation_institution",
            "faculty",
            "qualification",
            "graduation_year",
            "name_at_graduation",
            "other_institution_name",
            "other_institution_qualification",
            "student_reg_no",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Seed the profile/user fields from existing data on the edit path
        # (a brand-new AlumniProfile has no data to prefill). NOTE:
        # AlumniProfile.id is a UUIDField(default=uuid.uuid4), so a
        # freshly-instantiated, unsaved instance already has a non-null
        # pk -- `self.instance.pk` is NOT a valid "does this exist in the
        # DB" check here, unlike an auto-increment pk. `_state.adding` is
        # the check that actually means that.
        if self.instance and not self.instance._state.adding:
            profile = getattr(self.instance.user, "profile", None)
            if profile is not None:
                self.fields["honorific"].initial = profile.honorific
                self.fields["surname"].initial = profile.family_name
                self.fields["first_name"].initial = profile.given_name
                self.fields["middle_name"].initial = profile.middle_name
                self.fields["maiden_name"].initial = profile.maiden_name
                self.fields["gender"].initial = profile.gender
                self.fields["date_of_birth"].initial = profile.date_of_birth
                self.fields["id_passport_no"].initial = profile.national_id
                self.fields["nationality"].initial = profile.nationality
                self.fields["postal_address"].initial = profile.postal_address
                self.fields["postal_code"].initial = profile.postal_code
                self.fields["city"].initial = profile.city
                self.fields["phone_alt"].initial = profile.alt_phone
                self.fields["receive_newsletter"].initial = profile.email_opt_in
                self.fields["receive_sms_alerts"].initial = profile.sms_opt_in
            self.fields["phone_mobile"].initial = self.instance.user.phone
            self.fields["email"].initial = self.instance.user.email

        # The auto-generated ModelChoiceField queryset has no
        # select_related, so rendering the <option> list calls
        # Qualification.__str__ -> self.faculty.faculty_name once per
        # row -- an N+1 query per qualification (273 of them) that's
        # cheap on local SQLite but slow enough over a real network
        # connection (Neon) to blow past the request timeout.
        self.fields["qualification"].queryset = Qualification.objects.select_related("faculty")

        # Which unit is required depends on graduation_institution; clean()
        # enforces that, so neither branch's fields are required at the
        # field level (see apps/staff/forms.py's CompleteProfileForm for
        # the same pattern with staff_track).
        optional_fields = [
            "honorific",
            "middle_name",
            "maiden_name",
            "gender",
            "nationality",
            "postal_address",
            "postal_code",
            "city",
            "phone_alt",
            "email",
            "current_employer",
            "employment_position",
            "faculty",
            "qualification",
            "graduation_year",
            "name_at_graduation",
            "other_institution_name",
            "other_institution_qualification",
            "student_reg_no",
            "receive_newsletter",
            "receive_sms_alerts",
        ]
        for field_name in self.fields:
            self.fields[field_name].required = field_name not in optional_fields

        placeholders = {
            "surname": "Your surname",
            "first_name": "Your first name",
            "middle_name": "Middle name (optional)",
            "maiden_name": "Maiden name (optional)",
            "id_passport_no": "National ID or passport number",
            "nationality": "e.g. Kenyan",
            "postal_address": "Postal address (optional)",
            "postal_code": "Postal code (optional)",
            "city": "City (optional)",
            "phone_mobile": "e.g. 0712345678",
            "phone_alt": "Alternate phone (optional)",
            "email": "Alternate email (optional)",
            "current_employer": "Current place of employment (optional)",
            "employment_position": "Your position (optional)",
            "name_at_graduation": "Only if different from your current name",
            "other_institution_name": "Name of the institution",
            "other_institution_qualification": "Qualification and year",
            "student_reg_no": "Your student registration number (optional)",
        }
        for name, field in self.fields.items():
            if name in placeholders:
                field.widget.attrs["placeholder"] = placeholders[name]

        # help_texts is checked against self.fields, so membership_tier/
        # payment_method (declared only on the AlumniRegistrationForm
        # subclass) apply automatically there and are harmlessly absent
        # on the base AlumniProfileForm.
        help_texts = {
            "honorific": "How you'd like to be addressed (optional).",
            "surname": "Your family name, as it should appear on your membership record.",
            "first_name": "Your given name(s).",
            "middle_name": "Optional.",
            "maiden_name": "If applicable, and different from your surname above.",
            "gender": "Optional.",
            "date_of_birth": "Used to verify your identity and for demographic records.",
            "id_passport_no": "Used to verify your identity -- must be unique to your account.",
            "nationality": "Defaults to Kenyan.",
            "postal_address": "Optional -- used for correspondence.",
            "postal_code": "Optional -- used for correspondence.",
            "city": "Optional -- used for correspondence.",
            "phone_mobile": "Your primary contact number and login ID -- must be unique to your account.",
            "phone_alt": "An alternate number we can reach you on, if different.",
            "email": "An alternate address, separate from your Google login email.",
            "receive_newsletter": "Get the Association's newsletter by email. You can change this anytime.",
            "receive_sms_alerts": "Get event reminders and announcements by SMS. You can change this anytime.",
            "current_employer": "Optional -- helps the Association understand its alumni network.",
            "employment_position": "Optional -- helps the Association understand its alumni network.",
            "graduation_institution": "Where you obtained your qualification.",
            "graduation_year": "The year you completed your first degree -- this is what establishes your alumnus status, even if you've graduated again since.",
            "name_at_graduation": "Only if different from your current name.",
            "student_reg_no": "Your University of Nairobi student registration number, if you have one.",
            "membership_tier": "The category you're applying for. See Categories & Benefits for what each tier includes.",
            "payment_method": "How you plan to pay your membership fee.",
        }
        for name, field in self.fields.items():
            if name in help_texts:
                field.help_text = help_texts[name]

        # Conditional-requirement messages win over the generic ones above.
        self.fields["faculty"].help_text = "Required for University of Nairobi alumni."
        self.fields["qualification"].help_text = "Required for University of Nairobi alumni."
        self.fields["other_institution_name"].help_text = "Required if you selected 'Other Institution'."
        self.fields["other_institution_qualification"].help_text = "Required if you selected 'Other Institution'."

        self.apply_tailwind_styling()

    def clean_phone_mobile(self):
        raw = self.cleaned_data.get("phone_mobile")
        try:
            normalized = normalize_phone(raw)
        except InvalidPhoneNumber as exc:
            raise forms.ValidationError(exc.messages[0])

        owner = User.objects.filter(phone=normalized)
        if self.instance.user_id:
            owner = owner.exclude(pk=self.instance.user_id)
        if owner.exists():
            raise forms.ValidationError("This phone number is already registered to another account.")
        return normalized

    def clean_phone_alt(self):
        raw = self.cleaned_data.get("phone_alt")
        if not raw:
            return ""
        try:
            return normalize_phone(raw)
        except InvalidPhoneNumber as exc:
            raise forms.ValidationError(exc.messages[0])

    def clean_id_passport_no(self):
        national_id = self.cleaned_data.get("id_passport_no")
        owner = UserProfile.objects.filter(national_id=national_id)
        if self.instance.user_id:
            owner = owner.exclude(user_id=self.instance.user_id)
        if owner.exists():
            raise forms.ValidationError("This ID/passport number is already registered to another account.")
        return national_id

    def clean(self):
        cleaned_data = super().clean()
        graduation_institution = cleaned_data.get("graduation_institution")

        if not graduation_institution:
            return cleaned_data

        if graduation_institution == AlumniProfile.GraduationInstitution.UON:
            faculty = cleaned_data.get("faculty")
            qualification = cleaned_data.get("qualification")

            if not faculty:
                self.add_error("faculty", "Required for University of Nairobi alumni.")
            if not qualification:
                self.add_error("qualification", "Required for University of Nairobi alumni.")
            if faculty and qualification and qualification.faculty_id != faculty.id:
                self.add_error("qualification", "This qualification does not belong to the selected faculty.")

            cleaned_data["other_institution_name"] = ""
            cleaned_data["other_institution_qualification"] = ""

        elif graduation_institution == AlumniProfile.GraduationInstitution.OTHER:
            if not cleaned_data.get("other_institution_name"):
                self.add_error("other_institution_name", "Required if you selected 'Other Institution'.")
            if not cleaned_data.get("other_institution_qualification"):
                self.add_error("other_institution_qualification", "Required if you selected 'Other Institution'.")

            cleaned_data["faculty"] = None
            cleaned_data["qualification"] = None

        return cleaned_data

    def save(self, commit=True):
        alumni = super().save(commit=False)
        user = alumni.user
        profile = getattr(user, "profile", None) or UserProfile(user=user)

        profile.honorific = self.cleaned_data["honorific"]
        profile.given_name = self.cleaned_data["first_name"]
        profile.middle_name = self.cleaned_data.get("middle_name", "")
        profile.family_name = self.cleaned_data["surname"]
        profile.maiden_name = self.cleaned_data.get("maiden_name", "")
        profile.gender = self.cleaned_data.get("gender", "")
        profile.date_of_birth = self.cleaned_data["date_of_birth"]
        profile.national_id = self.cleaned_data.get("id_passport_no") or None
        profile.nationality = self.cleaned_data.get("nationality") or "Kenyan"
        profile.postal_address = self.cleaned_data.get("postal_address", "")
        profile.postal_code = self.cleaned_data.get("postal_code", "")
        profile.city = self.cleaned_data.get("city", "")
        profile.alt_phone = self.cleaned_data.get("phone_alt", "")
        profile.email_opt_in = self.cleaned_data.get("receive_newsletter", False)
        profile.sms_opt_in = self.cleaned_data.get("receive_sms_alerts", False)

        user.phone = self.cleaned_data["phone_mobile"]
        alt_email = self.cleaned_data.get("email")

        if commit:
            profile.save()
            user.save(update_fields=["phone"])
            alumni.save()
            # Alternate email goes through allauth's EmailAddress, not a
            # User column (docs/rebuild-schema.md: "django-allauth is
            # already installed ... do not build a second email model").
            if alt_email:
                from allauth.account.models import EmailAddress
                EmailAddress.objects.get_or_create(
                    user=user, email=alt_email, defaults={"verified": False, "primary": False}
                )
        return alumni


class AlumniRegistrationForm(AlumniProfileForm):
    """
    Registration-only extension of AlumniProfileForm -- adds the
    Membership Subscription fields from the paper form. These aren't
    AlumniProfile fields: membership_tier and payment_method drive a
    separate Payment + pending Membership record, both handled manually
    in AlumniRegisterView.form_valid(), not via ModelForm.save(). Kept
    off the base AlumniProfileForm so editing an existing profile
    (AlumniProfileUpdateView) never re-prompts for or silently discards a
    membership/payment selection.
    """
    membership_tier = forms.ModelChoiceField(
        queryset=MembershipTier.objects.filter(is_active=True).order_by("order"),
        label="Membership Category",
        empty_label=None,
    )
    payment_method = forms.ChoiceField(
        choices=Payment.PAYMENT_METHODS,
        label="Payment Method",
    )
    # Installment plans (2026-08-07): payment_frequency already existed on
    # Membership but nothing let a member actually choose it. "Once" pays
    # the full tier fee now; anything else starts a plan -- membership
    # activates on this first payment regardless of amount (Association
    # decision), the rest tracked as a running balance and confirmed
    # manually by the Secretariat like every other payment here.
    payment_frequency = forms.ChoiceField(
        choices=Membership.PaymentFrequency.choices,
        initial=Membership.PaymentFrequency.ONCE,
        label="Payment Frequency",
        help_text="Choose Once to pay the full fee now, or a recurring option to pay in installments.",
    )
    installment_amount = forms.DecimalField(
        required=False, min_value=Decimal("0.01"), max_digits=10, decimal_places=2,
        label="Amount for this installment",
        help_text="Only needed if Payment Frequency above isn't 'Once' -- leave blank to pay the full fee.",
    )
    # DPA 2019 consent gate -- required=True means the form itself refuses
    # to validate without it, not just a UI nicety. AlumniRegisterView
    # stamps consent_given_at/privacy_notice_version once this (and
    # everything else) passes. Not a model field: nothing to save here
    # directly, it only gates submission.
    privacy_consent = forms.BooleanField(
        required=True,
        # Trailing period, not a fragment: this is a checkbox's full
        # declarative statement, not a field prompt. Also means
        # label_tag's own label_suffix (":") doesn't get appended on
        # top of it -- Django skips the suffix when the label already
        # ends in :.!? -- which would otherwise read as "...Policy:".
        label="I have read and agree to the Privacy Policy.",
        help_text="Required under the Data Protection Act, 2019. Read it first: /uon-alumni-page/privacy/",
    )

    def clean(self):
        cleaned_data = super().clean()
        frequency = cleaned_data.get("payment_frequency")
        installment_amount = cleaned_data.get("installment_amount")
        if frequency == Membership.PaymentFrequency.ONCE:
            # A lump-sum payment always charges the full tier fee -- strip
            # installment_amount here rather than trusting it stays blank,
            # so a stray/crafted value in the POST (e.g. leftover from
            # switching frequency client-side, or a hand-built request)
            # can never override tier.fee at the view layer, which does
            # `form.cleaned_data.get("installment_amount") or tier.fee`.
            cleaned_data["installment_amount"] = None
        elif frequency and not installment_amount:
            self.add_error("installment_amount", "Required when Payment Frequency isn't 'Once'.")

        # M-Pesa gated per-tier (2026-08-07): available up to Gold's fee,
        # everything above must go through bank transfer -- see
        # MembershipTier.allows_mpesa for why this is fee-based, not
        # ladder_rank-based.
        tier = cleaned_data.get("membership_tier")
        if tier and cleaned_data.get("payment_method") == "mpesa" and not tier.allows_mpesa:
            self.add_error(
                "payment_method",
                f"M-Pesa isn't available for {tier.name} -- please choose Bank Transfer instead.",
            )
        return cleaned_data


class MembershipUpdateForm(TailwindStyledFormMixin, forms.Form):
    """
    Renew the current tier or move to a different one (including a
    lifetime tier) -- used by AlumniMembershipUpdateView. Records a
    pending Membership row (see apps/home/models.py's Membership) and a
    Payment; PaymentAdmin.mark_completed() activates the row once the
    Secretariat confirms payment.
    """
    membership_tier = forms.ModelChoiceField(
        queryset=MembershipTier.objects.filter(is_active=True).order_by("order"),
        label="Membership Category",
        empty_label=None,
        help_text="Renew your current tier, or move up to a different one (including a lifetime tier).",
    )
    payment_method = forms.ChoiceField(
        choices=Payment.PAYMENT_METHODS,
        label="Payment Method",
        help_text="How you'll be paying.",
    )
    payment_frequency = forms.ChoiceField(
        choices=Membership.PaymentFrequency.choices,
        initial=Membership.PaymentFrequency.ONCE,
        label="Payment Frequency",
        help_text="Choose Once to pay the full fee now, or a recurring option to pay in installments.",
    )
    installment_amount = forms.DecimalField(
        required=False, min_value=Decimal("0.01"), max_digits=10, decimal_places=2,
        label="Amount for this installment",
        help_text="Only needed if Payment Frequency above isn't 'Once' -- leave blank to pay the full fee.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_tailwind_styling()

    def clean(self):
        cleaned_data = super().clean()
        frequency = cleaned_data.get("payment_frequency")
        installment_amount = cleaned_data.get("installment_amount")
        if frequency == Membership.PaymentFrequency.ONCE:
            # A lump-sum payment always charges the full tier fee -- strip
            # installment_amount here rather than trusting it stays blank,
            # so a stray/crafted value in the POST (e.g. leftover from
            # switching frequency client-side, or a hand-built request)
            # can never override tier.fee at the view layer, which does
            # `form.cleaned_data.get("installment_amount") or tier.fee`.
            cleaned_data["installment_amount"] = None
        elif frequency and not installment_amount:
            self.add_error("installment_amount", "Required when Payment Frequency isn't 'Once'.")

        tier = cleaned_data.get("membership_tier")
        if tier and cleaned_data.get("payment_method") == "mpesa" and not tier.allows_mpesa:
            self.add_error(
                "payment_method",
                f"M-Pesa isn't available for {tier.name} -- please choose Bank Transfer instead.",
            )
        return cleaned_data


class ProfileClaimSearchForm(TailwindStyledFormMixin, forms.Form):
    """"Find my profile" search -- both fields optional individually, but
    clean() requires at least one filled in."""

    email = forms.EmailField(required=False, label="Email address")
    phone = forms.CharField(required=False, max_length=20, label="Phone number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].help_text = "Any email you may have used with us."
        self.fields["phone"].help_text = (
            "Any phone number you may have used with us. 0712345678, or with your "
            "country code if abroad, e.g. +254, +44."
        )
        self.fields["email"].widget.attrs["placeholder"] = "e.g. jane.doe@gmail.com"
        self.fields["phone"].widget.attrs["placeholder"] = "0712345678 (KE) or +447911123456 (UK)"
        self.apply_tailwind_styling()

    def clean_phone(self):
        raw = self.cleaned_data.get("phone")
        if not raw:
            return ""
        try:
            return normalize_phone(raw)
        except InvalidPhoneNumber as exc:
            raise forms.ValidationError(exc.messages[0])

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("email") and not cleaned_data.get("phone"):
            raise forms.ValidationError("Enter an email address, a phone number, or both.")
        return cleaned_data


class ProfileClaimCodeForm(TailwindStyledFormMixin, forms.Form):
    code = forms.CharField(
        max_length=6, min_length=6, label="Verification code",
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "autocomplete": "one-time-code", "placeholder": "6-digit code",
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].help_text = "Enter the 6-digit code we sent you."
        self.apply_tailwind_styling()

    def clean_code(self):
        raw = self.cleaned_data.get("code", "")
        if not raw.isdigit():
            raise forms.ValidationError("Enter the 6-digit numeric code.")
        return raw


