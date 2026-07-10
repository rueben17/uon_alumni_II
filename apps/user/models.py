# apps/accounts/models.py
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("The Email field must be set"))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        # set_password(None) automatically calls set_unusable_password() —
        # correct behaviour for OAuth-created accounts with no password.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self.create_user(email, password, **extra_fields)




class User(AbstractBaseUser, PermissionsMixin):

    class AuthProvider(models.TextChoices):
        EMAIL  = "email",  _("Email")
        GOOGLE = "google", _("Google")

    email = models.EmailField(_("Email Address"), unique=True)
    given_name = models.CharField(_("Given Name"), max_length=150, blank=True)
    family_name = models.CharField(_("Family Name"), max_length=150, blank=True)

    # Profile photo URL from Google (populated by the allauth adapter on
    # sign-up/login). Copied to Employee.google_photo_url by the signal,
    # same pattern as given_name/family_name -> Employee.first_name/last_name.
    google_photo_url = models.URLField(
        _("Google Profile Photo"),
        max_length=2000,
        blank=True,
        default="",
    )

    auth_provider = models.CharField(
        max_length=20,
        choices=AuthProvider.choices,
        default=AuthProvider.EMAIL,
        verbose_name=_("Auth Provider"),
        help_text=_("How this account was created — useful for support/debugging."),
    )

    # Template/view-level convenience flag (e.g. {% if user.is_admin %} to
    # show an admin nav section). NOT a Django permission flag — that's
    # is_staff / is_superuser, both provided below / via PermissionsMixin.
    is_admin = models.BooleanField(
        default=False,
        verbose_name=_("Is Admin (UI flag)"),
        help_text=_("Controls admin-only UI sections in templates. Does not affect Django permissions."),
    )

    is_staff   = models.BooleanField(default=False, verbose_name=_("Staff Status"))
    is_active  = models.BooleanField(default=True,  verbose_name=_("Active"))
    date_joined = models.DateTimeField(default=timezone.now, verbose_name=_("Date Joined"))

    # ========== New fields to store all basic Google userinfo data ==========
    google_sub = models.CharField(
        _("Google Unique ID (sub)"),
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text=_("Google's immutable user ID from the sub claim. Used to link Google accounts."),
    )

    email_verified = models.BooleanField(
        _("Email Verified by Google"),
        default=False,
        help_text=_("Whether Google has verified the user's email address."),
    )

    locale = models.CharField(
        _("Locale"),
        max_length=10,
        blank=True,
        help_text=_("User's preferred language (e.g., 'en', 'fr', 'de')."),
    )

    hd = models.CharField(
        _("Hosted Domain (Google Workspace)"),
        max_length=255,
        blank=True,
        help_text=_("Only present for Google Workspace accounts – the user's organisation domain."),
    )
    # =======================================================================

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["email"]

    def __str__(self):
        return self.email or ""

    def get_full_name(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()

    def get_short_name(self) -> str:
        return self.given_name or self.email