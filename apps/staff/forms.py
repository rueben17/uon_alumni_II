# apps/staff/forms.py
from django import forms

from apps.home.models import Department
from apps.staff.models import Employee
from apps.user.models import Honorific, User, UserProfile
from apps.user.phone import InvalidPhoneNumber, normalize_phone
from main.forms import TailwindStyledFormMixin


class CompleteProfileForm(TailwindStyledFormMixin, forms.ModelForm):
    """
    Employee's one-screen onboarding form. Employee itself only holds
    appointment data now (docs/rebuild-schema.md) -- honorific/name/DOB/
    national ID/photo live on UserProfile, and phone is the primary login
    handle on User, not the profile. The onboarding UX still edits all
    three in one screen, so __init__/save() fan the extra fields out to
    the right model instead of a single ModelForm.Meta.fields list.
    """

    honorific = forms.ChoiceField(choices=Honorific.choices, required=False)
    given_name = forms.CharField(max_length=255)
    family_name = forms.CharField(max_length=255)
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    national_id = forms.CharField(max_length=50, required=False, label="National ID")
    phone = forms.CharField(max_length=20)
    alt_phone = forms.CharField(max_length=20, required=False)
    photo = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={"accept": "image/*"}))

    class Meta:
        model = Employee
        fields = [
            "academic_rank",
            "staff_id",
            "staff_track",
            "department",
            "service_unit",
            "research_unit",
            "position",
            "employment_type",
            "employed_on",
        ]
        widgets = {
            "employed_on": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # The auto-generated ModelChoiceField queryset has no
        # select_related, so rendering the <option> list calls
        # Department.__str__ -> self.faculty.faculty_name once per row --
        # the same N+1 pattern as AlumniProfileForm's qualification field
        # (found via a load-time audit, 2026-08-12), just on Department
        # instead of Qualification.
        self.fields["department"].queryset = Department.objects.select_related("faculty")

        # Seed the profile/user fields from existing data on the edit path
        # (a brand-new Employee has no data to prefill). NOTE: Employee.id
        # is a UUIDField(default=uuid.uuid4), so a freshly-instantiated,
        # unsaved instance already has a non-null pk -- `self.instance.pk`
        # is NOT a valid "does this exist in the DB" check here, unlike an
        # auto-increment pk. `_state.adding` is the check that actually
        # means that. (In practice this form is only ever used as an
        # UpdateView, so self.instance always has a real DB row already —
        # fixed for correctness/defensiveness regardless.)
        if self.instance and not self.instance._state.adding:
            profile = getattr(self.instance.user, "profile", None)
            if profile is not None:
                self.fields["honorific"].initial = profile.honorific
                self.fields["given_name"].initial = profile.given_name
                self.fields["family_name"].initial = profile.family_name
                self.fields["date_of_birth"].initial = profile.date_of_birth
                self.fields["national_id"].initial = profile.national_id
                self.fields["alt_phone"].initial = profile.alt_phone
                self.fields["photo"].initial = profile.photo
            self.fields["phone"].initial = self.instance.user.phone

        # ---- 1. Field-level required ----
        # The three unit fields are NOT required here: which one is
        # required depends on staff_track, and clean() enforces that.
        # Marking them all required at field level makes the browser
        # block every submission (two of the three are always empty),
        # so the form never reaches Django and no errors ever render.
        optional_fields = [
            "photo",
            "national_id",
            "alt_phone",
            "position",
            "department",
            "service_unit",
            "research_unit",
            "academic_rank",
            "honorific",
        ]
        for field_name in self.fields:
            self.fields[field_name].required = field_name not in optional_fields
        # NOTE: no manual widget attrs["required"] stamping — Django
        # already renders the required attribute for required fields.

        # ---- 2. Placeholders for better UX ----
        placeholders = {
            "honorific": "e.g. Dr., Prof., Mr., Ms.",
            "academic_rank": "e.g. Lecturer, Professor",
            "given_name": "Your first name",
            "family_name": "Your surname",
            "date_of_birth": "YYYY-MM-DD",
            "national_id": "National ID number",
            "staff_id": "UoN staff ID",
            "phone": "0712345678 (KE) or +447911123456 (UK)",
            "alt_phone": "0712345678 (KE) or +447911123456 (UK) -- optional",
            "position": "e.g. Head of Department (optional)",
            "employment_type": "e.g. Permanent, Contract",
            "employed_on": "YYYY-MM-DD",
        }
        for name, field in self.fields.items():
            if name in placeholders:
                field.widget.attrs["placeholder"] = placeholders[name]

        # ---- 4. Input styling for a cleaner, consistent UI ----
        self.apply_tailwind_styling()

        # ---- 5. Help texts ----
        help_texts = {
            "honorific": "How you'd like to be addressed (optional).",
            "given_name": "Your first name.",
            "family_name": "Your surname.",
            "date_of_birth": "Used to verify your identity.",
            "national_id": "Your national ID number (optional, but helps confirm your identity).",
            "phone": "Your primary contact number and login ID -- must be unique to your account. "
                     "0712345678, or with your country code if abroad, e.g. +254, +44.",
            "alt_phone": "An alternate number we can reach you on, if different (optional). Same format as above.",
            "photo": "Upload a profile photo (optional).",
            "staff_id": "Your official University of Nairobi staff ID number.",
            "staff_track": "Choose the track that matches your role -- this determines which unit you'll be assigned to below.",
            "employment_type": "Your employment arrangement with the University.",
            "employed_on": "The date your appointment began.",
        }
        for name, field in self.fields.items():
            if name in help_texts:
                field.help_text = help_texts[name]

        # Conditional-requirement messages win over the generic ones above.
        self.fields["department"].help_text = "Required if you select 'Teaching'."
        self.fields["service_unit"].help_text = "Required if you select 'Service'."
        self.fields["research_unit"].help_text = "Required if you select 'Research'."
        self.fields["academic_rank"].help_text = "Required if you select 'Teaching'."

    def clean_phone(self):
        raw = self.cleaned_data.get("phone")
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

    def clean_alt_phone(self):
        raw = self.cleaned_data.get("alt_phone")
        if not raw:
            return ""
        try:
            return normalize_phone(raw)
        except InvalidPhoneNumber as exc:
            raise forms.ValidationError(exc.messages[0])

    def clean(self):
        cleaned_data = super().clean()
        staff_track = cleaned_data.get("staff_track")

        # Field-level required already reported a missing track;
        # nothing more to validate without it.
        if not staff_track:
            return cleaned_data

        track_unit_map = {
            Employee.StaffTrack.TEACHING: ("department", cleaned_data.get("department")),
            Employee.StaffTrack.SERVICE: ("service_unit", cleaned_data.get("service_unit")),
            Employee.StaffTrack.RESEARCH: ("research_unit", cleaned_data.get("research_unit")),
        }

        # The unit matching the chosen track is required — attach the
        # error to that field so it renders next to the dropdown.
        required_field_name, required_value = track_unit_map[staff_track]
        if not required_value:
            self.add_error(
                required_field_name,
                f"Required when staff track is "
                f"'{cleaned_data.get('staff_track')}'.",
            )

        # Clear the units that don't match the chosen track.
        for track, (field_name, _) in track_unit_map.items():
            if track != staff_track:
                cleaned_data[field_name] = None

        # Academic rank (Lecturer, Professor, etc.) only makes sense for
        # Teaching staff -- Service/Research staff use Position instead.
        if staff_track == Employee.StaffTrack.TEACHING:
            if not cleaned_data.get("academic_rank"):
                self.add_error(
                    "academic_rank",
                    "Required when staff track is 'Teaching'.",
                )
        else:
            cleaned_data["academic_rank"] = ""

        return cleaned_data

    def save(self, commit=True):
        employee = super().save(commit=False)
        user = employee.user
        profile = getattr(user, "profile", None) or UserProfile(user=user)

        profile.honorific = self.cleaned_data["honorific"]
        profile.given_name = self.cleaned_data["given_name"]
        profile.family_name = self.cleaned_data["family_name"]
        profile.date_of_birth = self.cleaned_data["date_of_birth"]
        profile.national_id = self.cleaned_data.get("national_id") or None
        profile.alt_phone = self.cleaned_data.get("alt_phone", "")
        if self.cleaned_data.get("photo"):
            profile.photo = self.cleaned_data["photo"]

        user.phone = self.cleaned_data["phone"]

        if commit:
            profile.save()
            user.save(update_fields=["phone"])
            employee.save()
        return employee
