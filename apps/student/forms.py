from django import forms

from apps.student.models import ScholarshipApplication, Student
from main.forms import TailwindStyledFormMixin, YearAsDateField


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
        self.apply_tailwind_styling()
