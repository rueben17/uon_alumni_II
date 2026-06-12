from django.db import models
from django.utils.text import slugify
from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
from django.urls import reverse
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from autoslug import AutoSlugField


User  = get_user_model()



# -------------------------------------------------------------------
# Helper for Department slug (faculty + name)
# -------------------------------------------------------------------
def get_department_slug(instance):
    return slugify(f"{instance.faculty.faculty_name} {instance.name}")

# -------------------------------------------------------------------
# 1. Faculty (Academic Divisions)
# -------------------------------------------------------------------
class Faculty(models.Model):
    faculty_name = models.CharField(
        max_length=255,
        unique=True,
        blank=False,
        null=False,
        verbose_name=_("Faculty Name"),
        help_text=_("Official name of the faculty (e.g., 'Agriculture')")
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Description")
    )
    slug = AutoSlugField(
        populate_from='faculty_name',
        unique=True,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
        verbose_name=_("Slug")
    )

    class Meta:
        ordering = ['faculty_name']
        verbose_name = _("Faculty")
        verbose_name_plural = _("Faculties")

    def __str__(self):
        return self.faculty_name



# -------------------------------------------------------------------
# 2. Department (Academic Departments under Faculty)
# -------------------------------------------------------------------
class Department(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name=_("Department Name")
    )
    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.CASCADE,
        related_name="departments",
        verbose_name=_("Faculty")
    )
    slug = AutoSlugField(
        populate_from=get_department_slug,
        unique=True,
        editable=True,
        always_update=True,
        null=True,
        verbose_name=_("Slug")
    )
    description = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ('name', 'faculty')
        ordering = ['name']
        verbose_name = _("Department")
        verbose_name_plural = _("Departments")

    def __str__(self):
        return f"{self.faculty.faculty_name} - {self.name}"



# -------------------------------------------------------------------
# 3. Service Unit (Offices, Directorates, Administrative Units)
# -------------------------------------------------------------------
class ServiceUnit(models.Model):
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Service Unit Name"),
        help_text=_("Name of office, directorate, or administrative unit")
    )
    slug = AutoSlugField(
        populate_from='name',
        unique=True,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
        verbose_name=_("Slug")
    )
    description = models.TextField(blank=True, null=True)
    # Optional: categorize as 'Office', 'Directorate', 'Centre', etc.
    unit_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=[
            ('OFFICE', 'Office'),
            ('DIRECTORATE', 'Directorate'),
            ('BOARD', 'Board'),
            ('CENTRE', 'Centre'),
            ('OTHER', 'Other'),
        ],
        verbose_name=_("Unit Type")
    )

    class Meta:
        ordering = ['name']
        verbose_name = _("Service Unit")
        verbose_name_plural = _("Service Units")

    def __str__(self):
        return self.name



# -------------------------------------------------------------------
# 4. Research Unit (Institutes and Centres)
# -------------------------------------------------------------------
class ResearchUnit(models.Model):
    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Research Unit Name"),
        help_text=_("Name of institute or research centre")
    )
    slug = AutoSlugField(
        populate_from='name',
        unique=True,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
        verbose_name=_("Slug")
    )
    description = models.TextField(blank=True, null=True)
    # Optional: distinguish Institute vs Centre
    unit_type = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        choices=[
            ('INSTITUTE', 'Institute'),
            ('CENTRE', 'Centre'),
        ],
        verbose_name=_("Unit Type")
    )
    # Optional relationship to a Faculty (if some institutes belong to a faculty)
    parent_faculty = models.ForeignKey(
        Faculty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="research_units",
        verbose_name=_("Parent Faculty")
    )

    class Meta:
        ordering = ['name']
        verbose_name = _("Research Unit")
        verbose_name_plural = _("Research Units")

    def __str__(self):
        return self.name