# Rebuild schema — greenfield, new Neon DB

Decided 2026-08-05. Supersedes the migration-based path in `todo.md` 0.3 and
parts of `docs/0.1-identity-decisions.md` (noted inline below).

The identity restructure was originally planned as a five-step migration over
live data. With a **new Neon database** that constraint disappears, which
changes three things:

- `User.pk` can simply *be* a UUID. The `public_id` workaround from D2 is
  deleted — one identifier per row, and the original `todo.md` guiding decision
  ("identity anchor = `User.pk` (UUID)") becomes literally true for free.
- No rename pass, no backfill, no data migration, no photo file relocation.
- **The `national_id` dedup audit is moot.** It was only ever a risk when
  merging two existing unique columns. Nothing to merge.

The governing rule, from which everything below follows:

> `User` is the auth record. `UserProfile` is the person. Role models
> (`Employee`, `Student`, `AlumniProfile`) hold *only* what is true of that
> role. No field appears in two places.

---

## `apps/user/models.py`

### `User` — auth only

```python
class User(AbstractBaseUser, PermissionsMixin):
    class AuthProvider(models.TextChoices):
        EMAIL  = "email",  _("Email")
        GOOGLE = "google", _("Google")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- Handles: the things you can log in with ----
    email          = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    phone          = PhoneNumberField(region="KE", unique=True, null=True, blank=True)
    phone_verified = models.BooleanField(default=False)

    # ---- Credential provenance ----
    auth_provider = models.CharField(max_length=20, choices=AuthProvider.choices,
                                     default=AuthProvider.EMAIL)
    google_sub    = models.CharField(max_length=255, unique=True, null=True, blank=True)

    # ---- Authorization (is_superuser/groups/user_permissions via mixin) ----
    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()
    USERNAME_FIELD = "email"

    @cached_property
    def roles(self) -> frozenset[str]:
        """{"staff", "student", "alumnus"} — resolved from role rows, never stored.
        Denormalizing this into a column would drift the moment a role record is
        created outside the one code path that maintains it."""

    def has_role(self, name: str) -> bool:
        return name in self.roles

    def get_full_name(self) -> str:
        profile = getattr(self, "profile", None)
        return profile.full_name if profile else self.email
```

`phone` is nullable at the DB level despite being mandatory by policy: Google
OAuth creates the `User` row before any phone has been collected. Requiredness
is enforced at the onboarding gate, not the column. `unique=True` alongside
NULLs is fine on Postgres.

**Why `phone` is here and not on the profile** — it is the primary *login
handle* (`todo.md` 0.4), and its verification flag is auth state. `User` already
pairs `email` with `email_verified`; `phone`/`phone_verified` follows the same
pattern, and the auth backend resolves a login without joining through a
profile. This revises the D-field-map in `0.1-identity-decisions.md`, which had
`phone` on `UserProfile`.

### `UserProfile` — the person, stored once

```python
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                related_name="profile", primary_key=True)

    honorific     = models.CharField(max_length=10, choices=Honorific.choices, blank=True)
    given_name    = models.CharField(max_length=255)
    middle_name   = models.CharField(max_length=255, blank=True)
    family_name   = models.CharField(max_length=255)
    maiden_name   = models.CharField(max_length=100, blank=True)
    gender        = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    national_id   = models.CharField(max_length=50, unique=True, null=True, blank=True)
    nationality   = models.CharField(max_length=100, default="Kenyan")

    photo            = models.ImageField(upload_to=profile_photo_path, null=True, blank=True)
    google_photo_url = models.URLField(max_length=2000, blank=True)

    alt_phone      = PhoneNumberField(region="KE", blank=True)
    postal_address = models.CharField(max_length=200, blank=True)
    postal_code    = models.CharField(max_length=20,  blank=True)
    city           = models.CharField(max_length=100, blank=True)

    locale = models.CharField(max_length=10, blank=True)

    # DPA 2019 — consent exists before data is collected, never bolted on later
    sms_opt_in   = models.BooleanField(default=False)
    email_opt_in = models.BooleanField(default=False)
    consent_given_at       = models.DateTimeField(null=True, blank=True)
    privacy_notice_version = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

`primary_key=True` on the O2O: the profile's pk *is* the user's pk. No surrogate
id, 1:1 enforced structurally. Opt-ins default `False` — consent under the DPA
cannot be pre-granted.

One `Honorific` TextChoices (lowercase keys) replaces the **four** overlapping
title vocabularies in the current code: `AlumniProfile.TITLE_CHOICES`,
`Employee.HonorificChoices`, and the separate `TITLE` tuples on `home.Executive`
and `home.Secretariat`.

---

## `apps/staff/models.py` — `Employee`, appointment only

```python
class Employee(models.Model):
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employee")

    staff_id      = models.CharField(max_length=50, unique=True, null=True, blank=True)
    academic_rank = models.CharField(max_length=50, choices=AcademicRank.choices, blank=True)
    staff_track   = models.CharField(max_length=20, choices=StaffTrack.choices, blank=True)

    department    = models.ForeignKey(Department,   null=True, blank=True, on_delete=models.SET_NULL)
    service_unit  = models.ForeignKey(ServiceUnit,  null=True, blank=True, on_delete=models.SET_NULL)
    research_unit = models.ForeignKey(ResearchUnit, null=True, blank=True, on_delete=models.SET_NULL)
    position      = models.ForeignKey(Position,     null=True, blank=True, on_delete=models.SET_NULL)

    employment_type = models.CharField(max_length=20, choices=EmploymentTypeChoices.choices, blank=True)
    employed_on     = models.DateField(null=True, blank=True)   # NOT date_joined
    is_active       = models.BooleanField(default=True)

    qr_code_image = models.ImageField(upload_to=qr_upload_path, null=True, blank=True)
    slug          = AutoSlugField(populate_from=get_employee_slug, unique=False, max_length=300)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)
```

Removed from `Employee` (11 fields): `given_name`, `middle_name`, `family_name`,
`honorific`, `date_of_birth`, `photo`, `google_photo_url`, `phone_number`,
`alt_phone_number`, `alt_email_address`, `national_id`.

`get_employee_slug()` now reads `instance.user.profile`. `academic_rank` stays —
it is an appointment property, unlike `honorific`, which is how the person is
addressed everywhere.

---

## `apps/student/models.py` — `Student`

```python
class Student(models.Model):
    class Status(models.TextChoices):
        ENROLLED  = "enrolled",  _("Enrolled")
        DEFERRED  = "deferred",  _("Deferred")
        GRADUATED = "graduated", _("Graduated")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student")

    registration_no = models.CharField(max_length=50, unique=True)
    faculty         = models.ForeignKey("staff.Faculty", null=True, blank=True, on_delete=models.SET_NULL)
    programme       = models.ForeignKey("home.Qualification", null=True, blank=True, on_delete=models.SET_NULL)
    year_of_study   = models.PositiveSmallIntegerField(null=True, blank=True)
    admitted_on         = models.DateField(null=True, blank=True)
    expected_completion = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ENROLLED)

    slug       = AutoSlugField(populate_from=get_student_slug, unique=False, max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

Graduation is **additive**: flip `status` to `GRADUATED`, create an
`AlumniProfile` on the *same* `User`, upgrade the existing free student
`Membership` in place through the 1.3 service layer. The student row stays as
history. No re-registration, no record copying, no new identity.

---

## Also in the rebuild (decided in 0.1, unchanged)

- **`AlumniProfile`** — academic and external-employment data only:
  `qualification`, `graduation_year`, `graduation_institution`,
  `other_institution_*`, `name_at_graduation`, `faculty`, `current_employer`,
  `employment_position`, `slug`, `is_active`. Membership fields leave.
  Keep `student_reg_no` for pre-system alumni who never had a `Student` row.
- **`Membership`** — FK (not O2O) to `User` so history accumulates; carries
  `tier`, `status`, `started_on`, `expires_on`, `is_lifetime`,
  `membership_number`, `payment_frequency`, and the issued-item flags
  (card/certificate/badge follow the membership, not the person).
- **`MembershipTier`** — add `student` to `TIER_TYPES`; give Honorary and
  Corporate real `duration_months` (0 currently means lifetime, so both are
  permanent by accident); add `ladder_rank` for the monotonic upgrade path.
  Fix `get_expiry_date()` — it uses `timedelta(days=months * 30)`, so a 12-month
  membership expires after 360 days and drifts earlier every renewal. Use
  `dateutil.relativedelta`.
- Reference tables unchanged: `Faculty`, `Department`, `ServiceUnit`,
  `ResearchUnit`, `Position`, `Qualification`.

---

## Where the overlap went

| Data | Was duplicated across | Now lives |
|---|---|---|
| given / middle / family name | `User`, `Employee`, `AlumniProfile`, (`Student`) | `UserProfile` |
| honorific / title | `AlumniProfile.title`, `Employee.honorific`, + 2 more | `UserProfile.honorific` |
| `google_photo_url` | `User`, `Employee` | `UserProfile` |
| `photo` | `Employee` | `UserProfile` |
| date of birth | `AlumniProfile`, `Employee` | `UserProfile` |
| national ID | `id_passport_no`, `national_id` | `UserProfile.national_id` |
| primary phone | `phone_mobile`, `phone_number` | `User.phone` (login handle) |
| alternate phone | `phone_alt`, `alt_phone_number` | `UserProfile.alt_phone` |
| secondary email | `AlumniProfile.email`, `Employee.alt_email_address` | allauth `EmailAddress` |

`django-allauth` is already installed and `allauth.account.models.EmailAddress`
provides multiple verified emails per `User` — which is exactly what `todo.md`
0.4 asks for. Do not build a second email model.

### The payoff, concretely
`_ensure_employee()` in `apps/user/adapter.py` currently runs this on **every
staff login**:

```python
employee.given_name = user.given_name
employee.family_name = user.family_name
employee.google_photo_url = user.google_photo_url
employee.save()
```

The commented-out `_ensure_student()` repeats it verbatim. In the rebuild that
block does not exist — there is nothing to sync when the name is stored once.

---

## Three things that look like duplicates but are not

Do not consolidate these:

1. `User.is_active` (may log in) vs `Employee.is_active` (currently employed) vs
   `Student.status` (enrolled/graduated). Three different facts — a retired
   professor keeps their account.
2. `User.date_joined` (account created) vs `Employee.employed_on` (appointment
   start). Renamed precisely because the collision invites confusion.
3. `UserProfile.honorific` (how the person is addressed) vs
   `Employee.academic_rank` (their appointment). A Dr. who is a Senior Lecturer
   needs both.

## Dropped outright

| Field | Why |
|---|---|
| `User.is_admin` | Zero readers. `apps/user/mixins.py:8` — the project's only "is admin?" helper — uses `is_staff or is_superuser` and ignores it. Editable in admin, consulted by nothing. |
| `User.hd` | Google Workspace domain is already in allauth's `SocialAccount.extra_data`. A third copy that goes stale. |
| `User.public_id` | Unnecessary once `User.pk` is a UUID. |
| `Employee.alt_email_address` | allauth `EmailAddress`. |

---

## NOT done — confirm before executing

Nothing in the repo has been changed to match this document. Still untouched:
`apps/*/models.py`, every migration directory, `db.sqlite3`, and the current
Neon database.

Before the rebuild runs, someone must decide and confirm:

1. **The current Neon DB is discarded.** Local dev holds 1 user, 1 alumni
   profile, 1 employee, 1 payment, 9 membership tiers — but **production has not
   been checked**. Verify what is actually in prod before dropping anything.
2. **Existing migrations are deleted and regenerated** from scratch (a fresh
   initial migration per app). This is the destructive step.
3. **`DATABASE_URL` repointed** to the new Neon database.
4. Media files: existing `media/employee_photos/` and `media/qr_codes/` refer to
   rows that will no longer exist.
5. Re-seed: `seed_qualifications`, the Position ranks (commits 5103049, 5c75ab0),
   and the membership tiers.

## Still the Association's call
Platinum (500k) and Diamond (250k) — fold into the ladder or retire; Honorary and
Corporate billing periods; Corporate's organizational shape (multiple named reps
under one membership); re-consent comms for the opt-in flip; retention rule and
the soft-delete vs. right-to-erasure reconciliation.
