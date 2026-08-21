from django import forms


class YearAsDateField(forms.IntegerField):
    """
    Renders as a native browser date picker (calendar popup) but stores
    and reads back just the year -- avoids IntegerField's default
    NumberInput, whose displayed value gets thousand-separator formatted
    (e.g. "2,015"). Use only for a field that is genuinely year-only;
    apps.home.forms.AlumniProfileForm used to use this for
    AlumniProfile.graduation_year but that field became a real DateField
    (graduation_date, 2026-08-21) once it turned out members expected
    the picked day/month to actually be saved, not silently discarded --
    this class is exactly the trap that fell into. Still used by
    apps.student.forms.ScholarshipApplicationForm (2026-08-13), where
    the underlying field really is year-only.
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


class TailwindStyledFormMixin:
    """
    Applies a consistent Tailwind input style to every field's widget.
    Mix in before forms.ModelForm/forms.Form and call
    self.apply_tailwind_styling() at the end of __init__.
    """

    base_input_class = (
        "mt-1 block w-full rounded-sm border border-slate-300 bg-white px-3 py-1.5 "
        "text-sm text-slate-900 shadow-sm focus:border-slate-500 focus:outline-none "
        "focus:ring-2 focus:ring-slate-200"
    )
    file_input_class = (
        "mt-1 block w-full rounded-sm border border-dashed border-slate-300 bg-white "
        "px-3 py-2 text-sm text-slate-700 file:mr-3 file:rounded-sm file:border-0 "
        "file:bg-slate-800 file:px-3 file:py-1.5 file:text-sm file:font-medium "
        "file:text-white hover:file:bg-slate-700"
    )
    # 2026-08-19: checkboxes had no branch of their own here, so every
    # BooleanField silently inherited base_input_class instead -- a
    # checkbox stretched to w-full with text-input padding (px-3 py-1.5),
    # not a normal small square. h-4 w-4 is the standard Tailwind
    # checkbox size; no mt-1 (the parent row in snippets/form_field.html
    # handles vertical alignment itself via its own mt-0.5 wrapper).
    checkbox_input_class = (
        "h-4 w-4 rounded border-slate-300 text-[#38b6ff] shadow-sm "
        "focus:ring-2 focus:ring-[#38b6ff] focus:ring-offset-0"
    )

    def apply_tailwind_styling(self):
        for field in self.fields.values():
            widget = field.widget
            existing_classes = widget.attrs.get("class", "")

            if isinstance(widget, forms.ClearableFileInput):
                widget.attrs["class"] = f"{existing_classes} {self.file_input_class}".strip()
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = f"{existing_classes} {self.checkbox_input_class}".strip()
            else:
                widget.attrs["class"] = f"{existing_classes} {self.base_input_class}".strip()
