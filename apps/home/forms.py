from django import forms

from apps.home.models import AlumniProfile, MembershipTier, Payment
from main.forms import TailwindStyledFormMixin


class YearAsDateField(forms.IntegerField):
    """
    Renders as a native browser date picker (calendar popup) but stores
    and reads back just the year, matching AlumniProfile.graduation_year
    (a plain IntegerField) -- avoids IntegerField's default NumberInput,
    whose displayed value gets thousand-separator formatted (e.g. "2,015").
    """
    widget = forms.DateInput(attrs={"type": "date"})

    def prepare_value(self, value):
        if isinstance(value, int):
            return f"{value}-01-01"
        return value

    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            # Native date input submits YYYY-MM-DD; keep only the year.
            year = int(str(value).split("-")[0])
        except (TypeError, ValueError, IndexError):
            raise forms.ValidationError("Enter a valid year.", code="invalid")
        return super().to_python(year)


class AlumniProfileForm(TailwindStyledFormMixin, forms.ModelForm):
    graduation_year = YearAsDateField(required=False, label="Year of Graduation")

    class Meta:
        model = AlumniProfile
        fields = [
            "title",
            "surname",
            "first_name",
            "middle_name",
            "maiden_name",
            "gender",
            "date_of_birth",
            "id_passport_no",
            "nationality",
            "postal_address",
            "postal_code",
            "city",
            "phone_mobile",
            "phone_alt",
            "email",
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
            "receive_newsletter",
            "receive_sms_alerts",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Which unit is required depends on graduation_institution; clean()
        # enforces that, so neither branch's fields are required at the
        # field level (see apps/staff/forms.py's CompleteProfileForm for
        # the same pattern with staff_track).
        optional_fields = [
            "middle_name",
            "maiden_name",
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
            "phone_mobile": "e.g. 254712345678",
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

        self.fields["faculty"].help_text = "Required for University of Nairobi alumni."
        self.fields["qualification"].help_text = "Required for University of Nairobi alumni."
        self.fields["other_institution_name"].help_text = "Required if you selected 'Other Institution'."
        self.fields["other_institution_qualification"].help_text = "Required if you selected 'Other Institution'."

        self.apply_tailwind_styling()

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


class AlumniRegistrationForm(AlumniProfileForm):
    """
    Registration-only extension of AlumniProfileForm -- adds the
    Membership Subscription fields from the paper form. These aren't
    AlumniProfile fields: membership_tier maps to
    AlumniProfile.current_membership_tier and payment_method drives a
    separate Payment record, both handled manually in
    AlumniRegisterView.form_valid(), not via ModelForm.save(). Kept off
    the base AlumniProfileForm so editing an existing profile
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


class MembershipUpdateForm(TailwindStyledFormMixin, forms.Form):
    """
    Renew the current tier or move to a different one (including a
    lifetime tier) -- used by AlumniMembershipUpdateView, not tied to
    AlumniProfile via ModelForm since the actual state change goes through
    AlumniProfile.renew_membership()/upgrade_to_lifetime(), not a plain
    field save.
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_tailwind_styling()
