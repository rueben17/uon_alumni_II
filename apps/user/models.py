import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField


def profile_photo_path(instance, filename):
    """profile_photos/<user-uuid>.<ext> — stable, immutable, no PII in the
    filename itself. Mirrors apps/staff/models.py's employee_photo_upload_path
    (commit e9bdd48), keyed to the user rather than the (now photo-less)
    Employee row."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"profile_photos/{instance.user_id}.{ext}"


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


class Honorific(models.TextChoices):
    """Canonical title vocabulary — replaces the four overlapping
    vocabularies that used to live on AlumniProfile, Employee, and the
    home app's Executive/Secretariat display models."""

    MR = "mr", _("Mr")
    MRS = "mrs", _("Mrs")
    MS = "ms", _("Ms")
    MISS = "miss", _("Miss")
    DR = "dr", _("Dr")
    PROF = "prof", _("Prof")
    REV = "rev", _("Rev")
    HON = "hon", _("Hon")
    ESQ = "esq", _("Esq")


class Gender(models.TextChoices):
    MALE = "M", _("Male")
    FEMALE = "F", _("Female")
    OTHER = "O", _("Other")


# Single source of truth for "which privacy notice did this consent apply
# to" -- stamped onto UserProfile.privacy_notice_version at the moment of
# consent (apps/home/views.py's AlumniRegisterView), and the exact string
# apps/home/management/commands/seed_legal_pages.py's Privacy Policy
# Article declares itself as. Bump this (and the seed command's body) if
# the notice materially changes -- existing members keep their old
# consent recorded against the old version instead of silently
# appearing to have agreed to text they never saw.
CURRENT_PRIVACY_NOTICE_VERSION = "1.0"


class User(AbstractBaseUser, PermissionsMixin):
    """Auth only. Everything that describes the *person* lives on
    UserProfile — see the guiding rule in docs/rebuild-schema.md."""

    class AuthProvider(models.TextChoices):
        EMAIL = "email", _("Email")
        GOOGLE = "google", _("Google")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- Handles: the things you can log in with ----
    email = models.EmailField(_("Email Address"), unique=True)
    email_verified = models.BooleanField(_("Email Verified by Google"), default=False)
    # Nullable at the DB level despite being mandatory by policy: Google
    # OAuth creates the User row before any phone has been collected.
    # Requiredness is enforced at the onboarding gate, not the column.
    phone = PhoneNumberField(region="KE", unique=True, null=True, blank=True)
    phone_verified = models.BooleanField(default=False)

    # ---- Credential provenance ----
    auth_provider = models.CharField(
        max_length=20,
        choices=AuthProvider.choices,
        default=AuthProvider.EMAIL,
        verbose_name=_("Auth Provider"),
        help_text=_("How this account was created — useful for support/debugging."),
    )
    google_sub = models.CharField(
        _("Google Unique ID (sub)"),
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text=_("Google's immutable user ID from the sub claim. Used to link Google accounts."),
    )

    # ---- Authorization (is_superuser/groups/user_permissions via mixin) ----
    is_staff = models.BooleanField(default=False, verbose_name=_("Staff Status"))
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    date_joined = models.DateTimeField(default=timezone.now, verbose_name=_("Date Joined"))

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["email"]

    def __str__(self):
        return self.email or ""

    @cached_property
    def roles(self) -> frozenset:
        """{"staff", "student", "alumnus"} — resolved from role rows, never
        stored. Denormalizing this into a column would drift the moment a
        role record is created outside the one code path that maintains it."""
        names = set()
        if hasattr(self, "employee"):
            names.add("staff")
        if hasattr(self, "student"):
            names.add("student")
        if hasattr(self, "alumni_profile"):
            names.add("alumnus")
        return frozenset(names)

    def has_role(self, name: str) -> bool:
        return name in self.roles

    def get_full_name(self) -> str:
        profile = getattr(self, "profile", None)
        return profile.full_name if profile else self.email

    def get_short_name(self) -> str:
        profile = getattr(self, "profile", None)
        return profile.given_name if profile else self.email


class UserProfile(models.Model):
    """The person, stored once. primary_key=True on the O2O: the profile's
    pk *is* the user's pk — no surrogate id, 1:1 enforced structurally."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profile", primary_key=True
    )

    honorific = models.CharField(max_length=10, choices=Honorific.choices, blank=True)
    given_name = models.CharField(max_length=255)
    middle_name = models.CharField(max_length=255, blank=True)
    family_name = models.CharField(max_length=255)
    maiden_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    national_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    nationality = models.CharField(max_length=100, default="Kenyan")

    photo = models.ImageField(upload_to=profile_photo_path, null=True, blank=True)
    google_photo_url = models.URLField(max_length=2000, blank=True, default="")

    alt_phone = PhoneNumberField(region="KE", blank=True)
    postal_address = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, blank=True)

    locale = models.CharField(max_length=10, blank=True)

    # DPA 2019 — consent exists before data is collected, never bolted on
    # later. Both default False: consent cannot be pre-granted.
    sms_opt_in = models.BooleanField(default=False)
    email_opt_in = models.BooleanField(default=False)
    consent_given_at = models.DateTimeField(null=True, blank=True)
    privacy_notice_version = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("User Profile")
        verbose_name_plural = _("User Profiles")

    def __str__(self):
        return self.full_name or self.user.email

    @property
    def full_name(self) -> str:
        parts = [self.given_name, self.middle_name, self.family_name]
        return " ".join(filter(None, parts)).strip()

    @property
    def display_name(self) -> str:
        """Honorific + full name — e.g. 'Prof. Jane Doe'."""
        prefix = f"{self.get_honorific_display()}." if self.honorific else ""
        return " ".join(filter(None, [prefix, self.full_name]))

    @property
    def display_photo_url(self) -> str:
        if self.photo:
            return self.photo.url
        return self.google_photo_url or ""
