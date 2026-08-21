from django.core.validators import MaxValueValidator

from django import forms

from apps.student.models import InterviewScoreSheet, ScholarshipApplication, Student
from main.forms import TailwindStyledFormMixin, YearAsDateField

# Ordered so both the form (iterating to build fields) and the template
# (iterating to render rows) walk the scoring matrix in the same,
# single defined order -- InterviewScoreSheet's own field declaration
# order (apps/student/models.py).
SCORE_FIELDS = [
    "score_about_yourself",
    "score_socioeconomic",
    "score_previous_education",
    "score_strength_weakness",
    "score_deserve_scholarship",
    "score_role_model",
    "score_family_status",
    "score_personality",
]


def score_field_max(field_name):
    """The awardable max for one InterviewScoreSheet score field, read
    from its own MaxValueValidator -- the model stays the single source
    of truth for these caps (they sum to 50) rather than re-hardcoding
    them here where they could drift out of sync."""
    field = InterviewScoreSheet._meta.get_field(field_name)
    for validator in field.validators:
        if isinstance(validator, MaxValueValidator):
            return validator.limit_value
    raise ValueError(f"{field_name} has no MaxValueValidator")


def score_field_label(field_name):
    """Criterion display name, derived mechanically from the field name
    (strip the score_ prefix, title-case) -- InterviewScoreSheet's score
    fields have no verbose_name of their own to draw a "real" label
    from, so this reformats the actual field name rather than inventing
    rubric wording that isn't in the model."""
    return field_name.removeprefix("score_").replace("_", " ").title()


class ScholarshipApplicationForm(TailwindStyledFormMixin, forms.ModelForm):
    # Native date-picker for a year-only field, same as graduation_year
    # on apps.home.forms.AlumniProfileForm -- avoids IntegerField's
    # default NumberInput, which thousand-separator-formats the displayed
    # value (e.g. "2,019"). year_of_study is NOT this -- it's an ordinal
    # (1st/2nd/... year of study), not a calendar year, so it stays a
    # plain number field.
    kcse_year = YearAsDateField(label="KCSE Year")

    class Meta:
        model = ScholarshipApplication
        # academic_level excluded -- this page IS the undergraduate
        # scholarship's application, so it stays at the model's
        # UNDERGRADUATE default rather than being user-selectable; the
        # model's own clean()/save() still enforces it as a backstop
        # (e.g. if this model is ever reused from a path that does
        # expose academic_level). student excluded -- set from
        # request.user.student in apps.home.views.uon_alumni_scholarship,
        # never user-chosen (2026-08-14 scholarship-page access gate).
        exclude = ["submitted_at", "academic_level", "student"]
        widgets = {
            "other_achievement_1": forms.Textarea(attrs={"rows": 3}),
            "other_achievement_2": forms.Textarea(attrs={"rows": 3}),
            # Native browser date picker -- same pattern as date_of_birth
            # on apps.staff.forms.CompleteProfileForm.
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            # Plain dropdown matching the field's own 1-7 validator range,
            # instead of a free-typed number input.
            "year_of_study": forms.Select(choices=[("", "---------")] + [(i, i) for i in range(1, 8)]),
            # Browser-level filter matching the model's FileExtensionValidator
            # (PDF only, 2026-08-14) -- a UX nicety, not the actual
            # enforcement; the validator is what a JS-disabled or
            # hand-crafted submission still has to pass.
            "physical_copy": forms.ClearableFileInput(attrs={"accept": "application/pdf"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_tailwind_styling()

    def clean(self):
        # faculty/department are independent ModelChoiceFields -- nothing
        # stops a mismatched pair reaching here otherwise (the cascading
        # dropdown JS is a UX nicety, not enforcement; a JS-disabled or
        # hand-crafted submission bypasses it entirely).
        cleaned_data = super().clean()
        faculty = cleaned_data.get("faculty")
        department = cleaned_data.get("department")
        if faculty and department and department.faculty_id != faculty.id:
            self.add_error(
                "department",
                f'"{department.name}" is not a department of {faculty.faculty_name}.',
            )
        return cleaned_data


class StudentRegisterForm(TailwindStyledFormMixin, forms.ModelForm):
    """
    One-time student sign-up on the students subdomain -- mirrors
    apps.home.forms.AlumniRegistrationForm's role (a real form filling
    in the identity data Google auth doesn't provide), not staff's
    stub-then-complete flow (see apps/user/adapter.py's "Students: no
    auto-created stub" note for why). user and student_email are set in
    apps.student.views.StudentRegisterView.form_valid(), not here --
    student_email comes straight from the Google login itself.
    """

    class Meta:
        model = Student
        fields = ["registration_no", "faculty", "programme", "year_of_study", "county", "alt_phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["registration_no"].help_text = "Your University of Nairobi student registration number."
        self.fields["faculty"].required = False
        self.fields["programme"].required = False
        self.fields["year_of_study"].required = False
        self.fields["county"].required = False
        self.fields["alt_phone"].required = False
        self.fields["alt_phone"].widget.attrs["placeholder"] = "0712345678 (KE) or +447911123456 (UK)"
        self.fields["alt_phone"].help_text = (
            "Optional. 0712345678, or with your country code if abroad, e.g. +254, +44."
        )
        self.apply_tailwind_styling()


class InterviewScoreSheetForm(TailwindStyledFormMixin, forms.ModelForm):
    """Staff-only interview scoring form (apps.student.views
    .EvaluateApplicationView). application and evaluator are excluded --
    both are set server-side in the view (application from the URL,
    evaluator from request.user.employee), never user-chosen.

    The 8 score_* fields are rebuilt below as integer dropdowns (0..max,
    max read from each field's own MaxValueValidator via
    score_field_max) instead of ModelForm's default NumberInput -- this
    is the "scoring matrix" UI: one row per criterion, an actual
    integer choice, not free-typed input that could exceed the cap
    client-side.
    """

    class Meta:
        model = InterviewScoreSheet
        exclude = ["application", "evaluator"]
        widgets = {
            "interview_date": forms.DateInput(attrs={"type": "date"}),
            "time_start": forms.TimeInput(attrs={"type": "time"}),
            "time_stop": forms.TimeInput(attrs={"type": "time"}),
            "other_remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in SCORE_FIELDS:
            max_score = score_field_max(field_name)
            self.fields[field_name] = forms.TypedChoiceField(
                label=score_field_label(field_name),
                choices=[(i, i) for i in range(max_score + 1)],
                coerce=int,
                # data-score-select marks this <select> for the live-total
                # JS listener in templates/student/evaluate_application.html
                # -- so header selects (verdict, parental_status) never get
                # summed in by accident.
                widget=forms.Select(attrs={"data-score-select": "1"}),
            )
        # Last, so the rebuilt score selects above also get styled --
        # apply_tailwind_styling() only touches fields present at call
        # time (same ordering already used by ScholarshipApplicationForm).
        self.apply_tailwind_styling()
