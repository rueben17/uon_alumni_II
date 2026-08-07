# apps/accounts/admin.py
#
# NOTE (docs/rebuild-schema.md, 2026-08-05): personal fields moved off User
# onto UserProfile. This is the minimal fix to keep the admin importable
# after that split — todo.md 0.5 ("chase every call-site") still owns the
# fuller admin pass (staff/AlumniProfile admin, membership_admin_site).
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.user.models import UserProfile
from apps.home.models import AlumniPhoneNumber

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
        fields = ("email", "phone", "is_active")

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
            "email", "phone", "phone_verified",
            "google_sub", "email_verified", "auth_provider",
            "is_active", "is_staff", "is_superuser",
            "groups", "user_permissions",
        )


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    fk_name = "user"


class AlumniPhoneNumberInline(admin.TabularInline):
    """Overflow phone numbers beyond User.phone/UserProfile.alt_phone --
    see apps/home/models.py's AlumniPhoneNumber docstring. Lives on the
    User admin (not AlumniProfile's) since phone is a User-level handle."""
    model = AlumniPhoneNumber
    extra = 0
    fields = ["phone", "label"]


# -------------------------------------------------------------------
# Admin
# -------------------------------------------------------------------

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User
    add_form = UserCreationForm
    form = UserChangeForm
    inlines = [UserProfileInline, AlumniPhoneNumberInline]

    list_display = [
        "email", "phone", "auth_provider",
        "email_verified", "phone_verified",
        "is_active", "is_staff", "date_joined",
    ]
    list_filter = ["is_active", "is_staff", "is_superuser", "auth_provider", "email_verified", "phone_verified"]
    search_fields = ["email", "phone", "google_sub"]
    ordering = ["email"]
    readonly_fields = [
        "last_login", "date_joined",
        "google_sub", "email_verified", "auth_provider",
    ]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Contact"), {"fields": ("phone", "phone_verified")}),
        (_("Google Data"), {
            "fields": ("google_sub", "email_verified", "auth_provider"),
            "classes": ("wide",),
            "description": _("Data received from Google OAuth (read-only where applicable)."),
        }),
        (_("Permissions"), {
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
            "classes": ("wide",),
        }),
        (_("Important Dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "phone", "password1", "password2", "is_active"),
        }),
    )

    # BaseUserAdmin's filter_horizontal expects these by default — keep them
    filter_horizontal = ("groups", "user_permissions")

    def get_inline_instances(self, request, obj=None):
        # No UserProfile row exists yet for a brand-new (not-yet-saved) User.
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)
