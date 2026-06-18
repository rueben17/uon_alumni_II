# apps/accounts/admin.py
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


# -------------------------------------------------------------------
# Custom forms — required because our User has no `username` field
# -------------------------------------------------------------------

class UserCreationForm(forms.ModelForm):
    """Form for creating new users in the admin. Includes password
    confirmation fields, as Django's default UserCreationForm assumes
    a `username` field."""

    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Confirm Password"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "given_name", "family_name", "is_active")

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(_("Passwords do not match."))
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        if commit:
            user.save()
        return user


class UserChangeForm(BaseUserChangeForm):
    """Form for editing users in the admin.

    Subclasses Django's UserChangeForm so the `password` field renders
    correctly as a read-only hash display with a 'change password' link
    (via ReadOnlyPasswordHashField), instead of a plain editable text
    field showing the raw hash.
    """

    class Meta(BaseUserChangeForm.Meta):
        model = User
        fields = (
            "email", "given_name", "family_name", "google_photo_url",
            "google_sub", "email_verified", "locale", "hd",
            "auth_provider", "is_admin", "is_active", "is_staff", "is_superuser",
            "groups", "user_permissions",
        )


# -------------------------------------------------------------------
# Admin
# -------------------------------------------------------------------

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User
    add_form = UserCreationForm
    form = UserChangeForm

    list_display = [
        "email", "given_name", "family_name", "auth_provider",
        "google_sub", "email_verified", "locale", "hd",
        "is_admin", "is_active", "is_staff", "date_joined", "photo_preview"
    ]
    list_filter = ["is_active", "is_staff", "is_superuser", "is_admin", "auth_provider", "email_verified", "hd"]
    search_fields = ["email", "given_name", "family_name", "google_sub"]
    ordering = ["email"]
    readonly_fields = [
        "last_login", "date_joined", "photo_preview",
        "google_sub", "email_verified", "auth_provider", "hd"
    ]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal Info"), {"fields": ("given_name", "family_name", "google_photo_url", "photo_preview")}),
        (_("Google Data"), {
            "fields": ("google_sub", "email_verified", "locale", "hd", "auth_provider"),
            "classes": ("wide",),
            "description": _("Data received from Google OAuth (read-only where applicable)."),
        }),
        (_("UI / Permissions"), {
            "fields": ("is_admin", "is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
            "classes": ("wide",),
        }),
        (_("Important Dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "given_name", "family_name", "password1", "password2", "is_active"),
        }),
    )

    # BaseUserAdmin's filter_horizontal expects these by default — keep them
    filter_horizontal = ("groups", "user_permissions")

    @admin.display(description=_("Photo"))
    def photo_preview(self, obj):
        from django.utils.html import format_html
        if obj.google_photo_url:
            return format_html(
                '<img src="{}" style="height:40px; width:40px; border-radius:50%; object-fit:cover;" />',
                obj.google_photo_url,
            )
        return "—"