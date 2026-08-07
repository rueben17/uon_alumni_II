import uuid
from autoslug import AutoSlugField
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


User = get_user_model()


# -------------------------------------------------------------------
# Slug helpers
# -------------------------------------------------------------------

def get_employee_slug(instance):
    """
    Produces: honorific-firstname-lastname
    e.g. prof-jane-doe
    Reads through UserProfile — Employee no longer holds name/honorific
    itself (docs/rebuild-schema.md). The UUID is a separate URL segment
    (see apps/qr_manager/urls.py), not part of the slug itself -- the slug
    is purely cosmetic.
    """
    profile = instance.user.profile
    honorific = profile.get_honorific_display() if profile.honorific else ""
    return slugify(f"{honorific} {profile.given_name} {profile.family_name}")


def qr_upload_path(instance, filename):
    """
    qr_codes/<unit-slug>/<employee-uuid>.png — unit folder for a
    browsable structure, UUID filename: unique, immutable, no PII.
    Incoming filename ignored so regenerations overwrite in place.
    """
    unit = instance.unit
    unit_slug = unit.slug if unit and unit.slug else "unassigned"
    return f"qr_codes/{unit_slug}/{instance.pk}.png"


# -------------------------------------------------------------------
# 1. Faculty, 2. Department -- moved to apps.home.models (2026-08-06).
# Both are academic/institutional structure, not staff-specific: home
# (AlumniProfile, Chapter, InMemoriam, Qualification) and student
# (Student.faculty) were always the heavier consumers -- staff only ever
# reached Faculty transitively, through Department. See docs/todo.md.
# -------------------------------------------------------------------

# -------------------------------------------------------------------
# 3. Service Unit  (administrative / non-teaching)
# -------------------------------------------------------------------

class ServiceUnit(models.Model):
    class UnitTypeChoices(models.TextChoices):
        OFFICE       = "OFFICE",       _("Office")
        DIRECTORATE  = "DIRECTORATE",  _("Directorate")
        BOARD        = "BOARD",        _("Board")
        CENTRE       = "CENTRE",       _("Centre")
        OTHER        = "OTHER",        _("Other")

    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Service Unit Name"),
        help_text=_("Name of office, directorate, or administrative unit"),
    )
    slug = AutoSlugField(
        populate_from="name",
        unique=True,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
        verbose_name=_("Slug"),
    )
    description = models.TextField(blank=True, null=True)
    unit_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=UnitTypeChoices.choices,
        verbose_name=_("Unit Type"),
    )

    class Meta:
        ordering = ["name"]
        verbose_name = _("Service Unit")
        verbose_name_plural = _("Service Units")

    def __str__(self):
        return self.name


# -------------------------------------------------------------------
# 4. Research Unit  (institutes / centres)
# -------------------------------------------------------------------

class ResearchUnit(models.Model):
    class UnitTypeChoices(models.TextChoices):
        INSTITUTE = "INSTITUTE", _("Institute")
        CENTRE    = "CENTRE",    _("Centre")

    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Research Unit Name"),
        help_text=_("Name of institute or research centre"),
    )
    slug = AutoSlugField(
        populate_from="name",
        unique=True,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
        verbose_name=_("Slug"),
    )
    description = models.TextField(blank=True, null=True)
    unit_type = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        choices=UnitTypeChoices.choices,
        verbose_name=_("Unit Type"),
    )
    parent_faculty = models.ForeignKey(
        'home.Faculty',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="research_units",
        verbose_name=_("Parent Faculty"),
    )

    class Meta:
        ordering = ["name"]
        verbose_name = _("Research Unit")
        verbose_name_plural = _("Research Units")

    def __str__(self):
        return self.name


# -------------------------------------------------------------------
# 5. Position
# -------------------------------------------------------------------

class Position(models.Model):
    """
    Seniority scale: 5 (most junior) → 15 (most senior).
        5 – 6  : Support / clerical
        7 – 9  : Officer / administrative
        10 – 12: Senior officer / lecturer
        13 – 14: Manager / senior lecturer / associate professor
        15     : Executive / professor / VC
    """
    title = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    level = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(5), MaxValueValidator(15)],
        default=5,
        help_text=_("Seniority rank: 5 (most junior) – 15 (most senior)"),
    )

    class Meta:
        ordering = ["-level", "title"]
        verbose_name = _("Position")
        verbose_name_plural = _("Positions")

    def __str__(self):
        return f"{self.title} (level {self.level})"


# -------------------------------------------------------------------
# 6. Employee
# -------------------------------------------------------------------

# staff/models.py (or wherever Employee lives)

class Employee(models.Model):
    """Appointment only. Personal data (name, honorific, DOB, photo, national
    ID, contact) lives on UserProfile — see docs/rebuild-schema.md. Access
    it through self.user.profile.* at call sites, not a delegation property
    here (todo.md guiding decision: "access-through, no delegation
    properties")."""

    # ------------------------------------------------------------------
    # Academic titles — shown in slug and name display
    # ------------------------------------------------------------------
    class AcademicRank(models.TextChoices):
        GRADUATE_ASSISTANT = "graduate_assistant", _("Graduate Assistant")
        TUTORIAL_FELLOW = "tutorial_fellow", _("Tutorial Fellow")
        LECTURER = "lecturer", _("Lecturer")
        SENIOR_LECTURER = "senior_lecturer", _("Senior Lecturer")
        ASSOCIATE_PROFESSOR = "associate_professor", _("Associate Professor")
        PROFESSOR = "professor", _("Professor")
        # Optional research-specific ranks
        RESEARCH_FELLOW = "research_fellow", _("Research Fellow")
        SENIOR_RESEARCH_FELLOW = "senior_research_fellow", _("Senior Research Fellow")
        RESEARCH_PROFESSOR = "research_professor", _("Research Professor")

    # ------------------------------------------------------------------
    # Staff track — determines which unit FK is relevant
    # ------------------------------------------------------------------
    class StaffTrack(models.TextChoices):
        TEACHING = "teaching", _("Teaching")
        SERVICE  = "service",  _("Service / Administrative")
        RESEARCH = "research", _("Research")

    # ------------------------------------------------------------------
    # Employment type
    # ------------------------------------------------------------------
    class EmploymentTypeChoices(models.TextChoices):
        PERMANENT = "permanent", _("Permanent")
        CONTRACT  = "contract",  _("Contract")
        PART_TIME = "part_time", _("Part-Time")
        INTERN    = "intern",    _("Intern")

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="employee",
        verbose_name=_("User Account"),
    )
    staff_id = models.CharField(
        max_length=50, unique=True, null=True, blank=True, verbose_name=_("Staff ID")
    )

    academic_rank = models.CharField(
        max_length=50,
        choices=AcademicRank.choices,
        blank=True,
        default="",
        verbose_name=_("Academic Rank"),
        help_text=_("Formal academic rank: Lecturer, Senior Lecturer, Associate Professor, Professor, etc."),
    )

    # ------------------------------------------------------------------
    # Organisational
    # ------------------------------------------------------------------
    staff_track = models.CharField(
        max_length=20,
        choices=StaffTrack.choices,
        blank=True,
        default="",
        verbose_name=_("Staff Track"),
        help_text=_(
            "Teaching → assign a Department. "
            "Service → assign a Service Unit. "
            "Research → assign a Research Unit."
        ),
    )

    department = models.ForeignKey(
        'home.Department',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name=_("Department"),
        help_text=_("Required for teaching staff."),
    )

    service_unit = models.ForeignKey(
        ServiceUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name=_("Service Unit"),
        help_text=_("Required for service / administrative staff."),
    )

    research_unit = models.ForeignKey(
        ResearchUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name=_("Research Unit"),
        help_text=_("Required for research staff."),
    )

    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name=_("Position"),
    )
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentTypeChoices.choices,
        blank=True,
        default="",
        verbose_name=_("Employment Type"),
    )

    # ------------------------------------------------------------------
    # Dates / status
    # ------------------------------------------------------------------
    # NOT date_joined — that's User.date_joined (account creation). This is
    # the appointment start date; the two used to collide under one name.
    employed_on = models.DateField(verbose_name=_("Employed On"), null=True, blank=True)
    is_active   = models.BooleanField(default=True, verbose_name=_("Is Active"))

    # ------------------------------------------------------------------
    # QR code image
    # ------------------------------------------------------------------
    qr_code_image = models.ImageField(
        upload_to=qr_upload_path,
        blank=True,
        null=True,
        verbose_name=_("QR Code"),
        help_text=_("Auto-generated QR code linking to this employee's profile page."),
    )

    # ------------------------------------------------------------------
    # Slug (name only, not unique, because UUID is the real identifier)
    # ------------------------------------------------------------------
    slug = AutoSlugField(
        populate_from=get_employee_slug,
        unique=False,          # ← changed from True
        editable=True,
        always_update=True,
        db_index=True,
        max_length=300,
        verbose_name=_("Slug"),
        help_text=_("Human-readable part of the URL (name only). Not used for lookup."),
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        verbose_name        = _("Employee")
        verbose_name_plural = _("Employees")
        indexes = [
            models.Index(fields=["staff_track"], name="staff_track_idx"),
            models.Index(fields=["is_active"],   name="active_staff_idx"),
        ]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def profile_is_complete(self) -> bool:
        """Minimum viable profile before a QR code is generated."""
        # Required fields: staff_id, staff_track, date_of_birth (on the
        # profile now), and appropriate unit FK.
        if not (self.staff_id and self.staff_track and self.user.profile.date_of_birth):
            return False
        if self.staff_track == self.StaffTrack.TEACHING and not self.department_id:
            return False
        if self.staff_track == self.StaffTrack.SERVICE and not self.service_unit_id:
            return False
        if self.staff_track == self.StaffTrack.RESEARCH and not self.research_unit_id:
            return False
        return True

    @property
    def unit(self):
        """Returns the organisational unit that matches the selected staff track."""
        if self.staff_track == self.StaffTrack.TEACHING:
            return self.department
        if self.staff_track == self.StaffTrack.SERVICE:
            return self.service_unit
        if self.staff_track == self.StaffTrack.RESEARCH:
            return self.research_unit
        return None

    @property
    def is_teaching_staff(self) -> bool:
        return self.staff_track == self.StaffTrack.TEACHING

    # ------------------------------------------------------------------
    # Methods
    # ------------------------------------------------------------------
    def clean(self):
        errors = {}
        if self.staff_track == self.StaffTrack.TEACHING and not self.department_id:
            errors["department"] = _("Teaching staff must be assigned to a Department.")
        if self.staff_track == self.StaffTrack.SERVICE and not self.service_unit_id:
            errors["service_unit"] = _("Service staff must be assigned to a Service Unit.")
        if self.staff_track == self.StaffTrack.RESEARCH and not self.research_unit_id:
            errors["research_unit"] = _("Research staff must be assigned to a Research Unit.")
        if errors:
            raise ValidationError(errors)


    def save(self, *args, **kwargs):
        # No automatic full_clean() – forms will call it.
        super().save(*args, **kwargs)


    def get_absolute_url(self):
            # Pretty URL once the profile is complete; the form's clean()
            # guarantees exactly one unit matches the track, so self.unit
            # is that unit.
            if self.is_active and self.profile_is_complete and self.slug and self.unit:
                # Keep URL format consistent across tracks:
                # <unit-name-slug>/<employee-slug>/<uuid>/
                unit_slug = slugify(self.unit.name)
                return reverse(
                    'staff:staff_detail',
                    kwargs={
                        'unit_slug': unit_slug,
                        'name_slug': self.slug,
                        'uuid': self.id,
                    },
                    urlconf='apps.staff.site_urls',
                )

            # Fresh-from-Google / incomplete profile: stable UUID URL.
            return reverse(
                'staff:staff_detail_fallback',
                kwargs={'uuid': self.id},
                urlconf='apps.staff.site_urls',
            )

    def __str__(self):
        if self.staff_id:
            return f"{self.user.profile.display_name} ({self.staff_id})"
        return self.user.email