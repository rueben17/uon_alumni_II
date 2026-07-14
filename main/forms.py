from django import forms


class TailwindStyledFormMixin:
    """
    Applies a consistent Tailwind input style to every field's widget.
    Mix in before forms.ModelForm/forms.Form and call
    self.apply_tailwind_styling() at the end of __init__.
    """

    base_input_class = (
        "mt-1 block w-full rounded-sm border border-slate-300 bg-white px-3 py-1.5 "
        "text-slate-900 shadow-sm focus:border-slate-500 focus:outline-none "
        "focus:ring-2 focus:ring-slate-200"
    )
    file_input_class = (
        "mt-1 block w-full rounded-sm border border-dashed border-slate-300 bg-white "
        "px-3 py-2 text-sm text-slate-700 file:mr-3 file:rounded-sm file:border-0 "
        "file:bg-slate-800 file:px-3 file:py-1.5 file:text-sm file:font-medium "
        "file:text-white hover:file:bg-slate-700"
    )

    def apply_tailwind_styling(self):
        for field in self.fields.values():
            widget = field.widget
            existing_classes = widget.attrs.get("class", "")

            if isinstance(widget, forms.ClearableFileInput):
                widget.attrs["class"] = f"{existing_classes} {self.file_input_class}".strip()
            else:
                widget.attrs["class"] = f"{existing_classes} {self.base_input_class}".strip()
