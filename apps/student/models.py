import uuid

from autoslug import AutoSlugField
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

User = get_user_model()


def get_student_slug(instance):
    """Mirrors apps/staff/models.py's get_employee_slug — reads through
    UserProfile, since Student holds no name data itself."""
    profile = instance.user.profile
    return slugify(f"{profile.given_name} {profile.family_name}")


class Student(models.Model):
    """Thin role model. Personal data lives on UserProfile (see
    docs/rebuild-schema.md — supersedes the StudentProfile draft in
    docs/0.1-identity-decisions.md). Graduation is additive, not migratory:
    the same User gains an AlumniProfile and the existing free student
    Membership upgrades in place — this row stays as history, never
    deleted or copied."""

    class Status(models.TextChoices):
        ENROLLED = "enrolled", _("Enrolled")
        DEFERRED = "deferred", _("Deferred")
        GRADUATED = "graduated", _("Graduated")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student")

    registration_no = models.CharField(max_length=50, unique=True)
    faculty = models.ForeignKey(
        "staff.Faculty", null=True, blank=True, on_delete=models.SET_NULL, related_name="students"
    )
    programme = models.ForeignKey(
        "home.Qualification", null=True, blank=True, on_delete=models.SET_NULL, related_name="students"
    )
    year_of_study = models.PositiveSmallIntegerField(null=True, blank=True)
    admitted_on = models.DateField(null=True, blank=True)
    expected_completion = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ENROLLED)

    slug = AutoSlugField(
        populate_from=get_student_slug,
        unique=False,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
        max_length=300,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Student")
        verbose_name_plural = _("Students")

    def __str__(self):
        return f"{self.user.profile.display_name} ({self.registration_no})"
