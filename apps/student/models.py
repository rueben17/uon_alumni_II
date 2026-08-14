import uuid

from autoslug import AutoSlugField
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

from apps.staff.models import Employee

User = get_user_model()


def get_student_slug(instance):
    """Mirrors apps/staff/models.py's get_employee_slug — reads through
    UserProfile, since Student holds no name data itself."""
    profile = instance.user.profile
    return slugify(f"{profile.given_name} {profile.family_name}")


class Gender(models.TextChoices):
    MALE = "male", _("Male")
    FEMALE = "female", _("Female")


class AcademicLevel(models.TextChoices):
    UNDERGRADUATE = "undergraduate", _("Undergraduate")
    POSTGRADUATE = "postgraduate", _("Postgraduate")


class ParentalStatus(models.TextChoices):
    ORPHAN = "orphan", _("Orphan")
    ONE_PARENT = "one_parent", _("One Parent")
    BOTH_PARENTS = "both_parents", _("Both Parents")


class Verdict(models.IntegerChoices):
    QUALIFIES = 1, _("Qualifies for scholarship award")
    DOES_NOT_QUALIFY = 2, _("Does not qualify for scholarship award")


class KcseGrade(models.TextChoices):
    # The standard 8-4-4 KCSE grading scale, best to worst -- matches
    # Meta.ordering conventions elsewhere in this file (best-first reads
    # naturally in a dropdown, same as e.g. QualificationLevel above).
    A = "A", _("A")
    A_MINUS = "A-", _("A-")
    B_PLUS = "B+", _("B+")
    B = "B", _("B")
    B_MINUS = "B-", _("B-")
    C_PLUS = "C+", _("C+")
    C = "C", _("C")
    C_MINUS = "C-", _("C-")
    D_PLUS = "D+", _("D+")
    D = "D", _("D")
    D_MINUS = "D-", _("D-")
    E = "E", _("E")


class County(models.TextChoices):
    # All 47 Kenyan counties -- fixed choices, not free text, because
    # county fields feed distribution charts and unconstrained typing
    # fragments a single county into several differently-spelled buckets
    # (2026-08-13). Lives here, not in apps.home, because both consumers
    # (Student.county, ScholarshipApplication.county_of_residence) are
    # student-data models -- moved here together (see move note below).
    MOMBASA = "mombasa", "Mombasa"
    KWALE = "kwale", "Kwale"
    KILIFI = "kilifi", "Kilifi"
    TANA_RIVER = "tana_river", "Tana River"
    LAMU = "lamu", "Lamu"
    TAITA_TAVETA = "taita_taveta", "Taita-Taveta"
    GARISSA = "garissa", "Garissa"
    WAJIR = "wajir", "Wajir"
    MANDERA = "mandera", "Mandera"
    MARSABIT = "marsabit", "Marsabit"
    ISIOLO = "isiolo", "Isiolo"
    MERU = "meru", "Meru"
    THARAKA_NITHI = "tharaka_nithi", "Tharaka-Nithi"
    EMBU = "embu", "Embu"
    KITUI = "kitui", "Kitui"
    MACHAKOS = "machakos", "Machakos"
    MAKUENI = "makueni", "Makueni"
    NYANDARUA = "nyandarua", "Nyandarua"
    NYERI = "nyeri", "Nyeri"
    KIRINYAGA = "kirinyaga", "Kirinyaga"
    MURANGA = "muranga", "Murang'a"
    KIAMBU = "kiambu", "Kiambu"
    TURKANA = "turkana", "Turkana"
    WEST_POKOT = "west_pokot", "West Pokot"
    SAMBURU = "samburu", "Samburu"
    TRANS_NZOIA = "trans_nzoia", "Trans Nzoia"
    UASIN_GISHU = "uasin_gishu", "Uasin Gishu"
    ELGEYO_MARAKWET = "elgeyo_marakwet", "Elgeyo-Marakwet"
    NANDI = "nandi", "Nandi"
    BARINGO = "baringo", "Baringo"
    LAIKIPIA = "laikipia", "Laikipia"
    NAKURU = "nakuru", "Nakuru"
    NAROK = "narok", "Narok"
    KAJIADO = "kajiado", "Kajiado"
    KERICHO = "kericho", "Kericho"
    BOMET = "bomet", "Bomet"
    KAKAMEGA = "kakamega", "Kakamega"
    VIHIGA = "vihiga", "Vihiga"
    BUNGOMA = "bungoma", "Bungoma"
    BUSIA = "busia", "Busia"
    SIAYA = "siaya", "Siaya"
    KISUMU = "kisumu", "Kisumu"
    HOMA_BAY = "homa_bay", "Homa Bay"
    MIGORI = "migori", "Migori"
    KISII = "kisii", "Kisii"
    NYAMIRA = "nyamira", "Nyamira"
    NAIROBI = "nairobi", "Nairobi City"


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

    # University-issued email (consent-form gap analysis, 2026-08-13).
    # Corrected understanding: on the student subdomain, sign-in itself
    # IS the @students.uonbi.ac.ke Google Workspace account -- so once
    # _ensure_student() exists, User.email at sign-in time already *is*
    # this address, the same way it already works for staff/alumni. Kept
    # as its own field regardless (not just read through user.email):
    # preserves the university address as its own record even if the
    # User's primary login email ever changes later. Still optional at
    # the DB level, since apps/user/adapter.py's _ensure_student() is
    # commented out and nothing populates it yet.
    student_email = models.EmailField(
        blank=True,
        verbose_name=_("Student (university) email"),
        help_text=_("The university-issued @students.uonbi.ac.ke address."),
    )
    county = models.CharField(max_length=32, choices=County.choices, blank=True, verbose_name=_("County of residence"))
    alt_phone = PhoneNumberField(region="KE", blank=True)

    faculty = models.ForeignKey(
        "home.Faculty", null=True, blank=True, on_delete=models.SET_NULL, related_name="students"
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


# -------------------------------------------------------------------
# Scholarship applications (2026-08-11, moved from apps.home 2026-08-13)
# -- Google Form applicant data plus the printed interview score sheet.
# Moved out of apps.home: that app is the alumni-facing content site
# (people who have already graduated) -- an undergraduate scholarship
# applicant is a prospective/current student, not an alumnus, so this
# data belongs alongside Student, not Chapter/InMemoriam/Article. The
# DB tables themselves were renamed in place (home_scholarshipapplication
# -> student_scholarshipapplication, same for interviewscoresheet) via
# a state-only migration + AlterModelTable, not dropped and recreated --
# see apps/student/migrations for the exact operations. Gender here is
# deliberately its own 2-choice (male/female) enum, NOT apps.user.models
# .Gender (male/female/other) used by UserProfile -- this form's source
# data (a Google Form) only ever offered two options; conflating the two
# would silently change what values are valid here.
# -------------------------------------------------------------------

def _scholarship_physical_copy_path(instance, filename):
    """Renames the upload to the applicant's own name-slug instead of
    keeping the browser/scanner-supplied filename (2026-08-14) --
    "scan.pdf"/"IMG_0001.pdf" collide constantly across submissions, and
    Django's default collision handling just appends a random suffix
    (e.g. app_zXCuekM.pdf), which is neither readable nor predictable.
    Reuses get_student_slug's exact slug when a Student is linked
    (always true going through the public form now that the scholarship
    page gates on student sign-up -- see apps.home.views
    .uon_alumni_scholarship); falls back to the application's own name
    fields for the nullable legacy/admin-imported path where no Student
    is linked.
    """
    slug = get_student_slug(instance.student) if instance.student_id else slugify(
        f"{instance.first_name} {instance.surname}"
    )
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    year = timezone.now().year
    return f"scholarship_applications/{year}/{slug}.{ext}" if ext else f"scholarship_applications/{year}/{slug}"


class ScholarshipApplication(models.Model):
    """Undergraduate-only alumni scholarship application, sourced from a
    Google Form. Undergraduate-only is enforced here at the model layer
    (clean() + full_clean()-in-save()), not just in whatever form/import
    path collects these -- see academic_level below."""

    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="Timestamp")
    first_name = models.CharField(max_length=100, verbose_name="First/Baptismal")
    middle_name = models.CharField(max_length=100, blank=True)
    surname = models.CharField(max_length=100, verbose_name="Surname/Family Name")
    gender = models.CharField(max_length=10, choices=Gender.choices)
    date_of_birth = models.DateField()
    registration_number = models.CharField(
        max_length=30, unique=True, verbose_name="University registration number"
    )
    # Not required, not unique-enforced against Student.registration_no:
    # there are zero Student rows in production as of 2026-08-13 (no
    # signup flow creates them yet), so this can't be a hard FK without
    # making every existing/near-term application row invalid. Nullable
    # until that changes.
    student = models.OneToOneField(
        "Student", on_delete=models.PROTECT, null=True, blank=True, related_name="applicant"
    )
    current_course = models.CharField(max_length=150)
    year_of_study = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    # Real dropdowns off the existing Faculty/Department reference data
    # (2026-08-11), not free text -- these tables already exist and are
    # seeded. PROTECT rather than SET_NULL/CASCADE: both fields are
    # required (matching the original free-text fields' non-blank
    # intent), so a nullable on_delete would silently change that, and
    # CASCADE would let deleting a Faculty erase scholarship applications.
    # String refs ("home.X"): Faculty/Department live in apps.home, this
    # model lives in apps.student -- same cross-app pattern already used
    # by Student.faculty/Student.programme above.
    department = models.ForeignKey("home.Department", on_delete=models.PROTECT, related_name="scholarship_applications")
    faculty = models.ForeignKey("home.Faculty", on_delete=models.PROTECT, related_name="scholarship_applications")
    mobile_no = models.CharField(max_length=20, verbose_name="Tel./Mobile No")
    alternative_mobile_no = models.CharField(max_length=20, blank=True)
    email = models.EmailField()
    county_of_residence = models.CharField(max_length=100, choices=County.choices)
    sub_county = models.CharField(max_length=100)
    ward = models.CharField(max_length=100)
    location = models.CharField(max_length=100)
    sub_location = models.CharField(max_length=100)

    # Secondary school details
    school_name = models.CharField(max_length=200)
    kcse_grade = models.CharField(max_length=5, choices=KcseGrade.choices, verbose_name="KCSE Grade")
    kcse_year = models.PositiveSmallIntegerField(
        # Upper bound is evaluated once at process start (module import
        # time), same as every other "current year" cap in this file --
        # not per-request, and it will get frozen into the migration at
        # whatever year `makemigrations` was run, same known tradeoff as
        # any other MaxValueValidator(<computed>) pattern.
        validators=[MinValueValidator(1985), MaxValueValidator(timezone.now().year)]
    )
    school_phone_no = models.CharField(max_length=20, blank=True)
    head_teacher_no = models.CharField(max_length=20, blank=True)
    school_county = models.CharField(max_length=100)
    other_achievement_1 = models.TextField(
        blank=True, verbose_name="State any other academic achievement"
    )
    other_achievement_2 = models.TextField(blank=True)  # second achievement field

    # Physical/printed copy of the application, scanned or photographed.
    # PDF only (2026-08-14) -- was pdf/jpg/jpeg/png; the printed form is
    # always scanned to PDF in practice, and narrowing the accepted type
    # avoids phone-camera photos of varying quality/orientation.
    physical_copy = models.FileField(
        upload_to=_scholarship_physical_copy_path,
        validators=[FileExtensionValidator(["pdf"])],
    )

    # Undergraduate-only enforcement -- see clean()/save() below.
    academic_level = models.CharField(
        max_length=20, choices=AcademicLevel.choices, default=AcademicLevel.UNDERGRADUATE
    )

    class Meta:
        db_table = "student_scholarshipapplication"
        verbose_name = "Scholarship Application"
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.surname}, {self.first_name} ({self.registration_number})"

    def clean(self):
        super().clean()
        if self.academic_level != AcademicLevel.UNDERGRADUATE:
            raise ValidationError("Only undergraduate students may apply for this scholarship.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class InterviewScoreSheet(models.Model):
    """Printed interview score sheet, one per ScholarshipApplication."""

    application = models.OneToOneField(
        ScholarshipApplication, on_delete=models.CASCADE, related_name="score_sheet"
    )
    # Who actually ran the interview and awarded these scores -- PROTECT
    # so deleting a staff Employee record can't silently blank out (or
    # cascade-delete) a completed evaluation.
    evaluator = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="evaluations")

    # Header
    venue = models.CharField(max_length=150, default="Alumni Offices")
    interview_date = models.DateField()
    time_start = models.TimeField()
    time_stop = models.TimeField()
    course_undertaking = models.CharField(max_length=150)  # denormalized snapshot from the application

    # Scored questions -- each stores the AWARDED score, capped by its
    # own MaxValueValidator; the eight caps sum to exactly 50.
    score_about_yourself = models.PositiveSmallIntegerField(validators=[MaxValueValidator(5)])
    score_socioeconomic = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10)])
    score_previous_education = models.PositiveSmallIntegerField(validators=[MaxValueValidator(5)])
    score_strength_weakness = models.PositiveSmallIntegerField(validators=[MaxValueValidator(5)])
    score_deserve_scholarship = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10)])
    score_role_model = models.PositiveSmallIntegerField(validators=[MaxValueValidator(5)])
    # Scored per parental_status, per the rubric: Orphan -> 5, One Parent
    # -> 3, Both Parents -> 2 (interviewer enters the awarded score by
    # hand off the printed sheet; not auto-derived from parental_status).
    score_family_status = models.PositiveSmallIntegerField(validators=[MaxValueValidator(5)])
    score_personality = models.PositiveSmallIntegerField(validators=[MaxValueValidator(5)])

    parental_status = models.CharField(max_length=15, choices=ParentalStatus.choices)
    received_other_funding = models.BooleanField(verbose_name="Have you received other funding...")
    verdict = models.IntegerField(choices=Verdict.choices)
    prepared_by_name = models.CharField(max_length=150)
    prepared_by_signature = models.CharField(max_length=150, blank=True)
    other_remarks = models.TextField(blank=True)

    class Meta:
        db_table = "student_interviewscoresheet"
        verbose_name = "Interview Score Sheet"

    def __str__(self):
        return f"Score sheet for {self.application} — {self.total_score}/50"

    @property
    def total_score(self):
        return (
            self.score_about_yourself
            + self.score_socioeconomic
            + self.score_previous_education
            + self.score_strength_weakness
            + self.score_deserve_scholarship
            + self.score_role_model
            + self.score_family_status
            + self.score_personality
        )
