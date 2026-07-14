# apps/staff/forms.py
from django import forms

from apps.staff.models import Employee
from main.forms import TailwindStyledFormMixin


class CompleteProfileForm(TailwindStyledFormMixin, forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "honorific",
            "academic_rank",
            "given_name",
            # "middle_name",
            "family_name",
            "date_of_birth",
            "national_id",
            "staff_id",
            "alt_email_address",
            "phone_number",
            "alt_phone_number",
            "staff_track",
            "department",
            "service_unit",
            "research_unit",
            "position",
            "employment_type",
            "date_joined",
            "photo",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "date_joined": forms.DateInput(attrs={"type": "date"}),
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ---- 1. Field-level required ----
        # The three unit fields are NOT required here: which one is
        # required depends on staff_track, and clean() enforces that.
        # Marking them all required at field level makes the browser
        # block every submission (two of the three are always empty),
        # so the form never reaches Django and no errors ever render.
        optional_fields = [
            "photo",
            "middle_name",
            "alt_email_address",
            "alt_phone_number",
            "position",
            "department",
            "service_unit",
            "research_unit",
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
            "middle_name": "Middle name (optional)",
            "family_name": "Your surname",
            "date_of_birth": "YYYY-MM-DD",
            "national_id": "National ID number",
            "staff_id": "UoN staff ID",
            "alt_email_address": "Alternate email (optional)",
            "phone_number": "e.g. +254712345678",
            "alt_phone_number": "Alternate phone (optional)",
            "position": "e.g. Head of Department (optional)",
            "employment_type": "e.g. Permanent, Contract",
            "date_joined": "YYYY-MM-DD",
        }
        for name, field in self.fields.items():
            if name in placeholders:
                field.widget.attrs["placeholder"] = placeholders[name]

        # ---- 4. Input styling for a cleaner, consistent UI ----
        self.apply_tailwind_styling()

        # ---- 5. Help texts ----
        self.fields["department"].help_text = "Required if you select 'Teaching'."
        self.fields["service_unit"].help_text = "Required if you select 'Service'."
        self.fields["research_unit"].help_text = "Required if you select 'Research'."
        self.fields["photo"].help_text = "Upload a profile photo (optional)."

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

        return cleaned_data