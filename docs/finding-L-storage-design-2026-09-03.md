# Finding L — storage fix design

**Date:** 2026-09-03
**Branch:** `coverage/phase-1` (a dedicated `fix/finding-l-storage` is recommended — see [Branch](#branch))
**Status:** 🛑 **Read-and-report only.** No setting changed, no file moved, no Cloudinary write.

Direction is decided: Cloudinary-on for media. This designs the `STORAGES` dict, the existing-files move, and the sequencing.

---

## ⚠ The risk that must be solved in the same pass

**Turning on Cloudinary as the default storage will point 241 tests at a real Cloudinary account.**

The suite isolates file writes with `override_settings(MEDIA_ROOT=temp_dir)` — the module-level block in `apps/qr_manager/tests.py`, and class-level ones in `apps/home/tests.py`. `MEDIA_ROOT` is a **`FileSystemStorage` concept**. Once `STORAGES['default']` is Cloudinary, that override silently stops isolating anything, and every test that writes a file — QR badge generation, Digital ID photos, badge PDFs, Banner watermarks — begins uploading to the live account configured in `.env`.

It would not fail loudly. It would pass, slowly, while filling a production Cloudinary account with test artefacts.

**This is not a follow-up. It is a precondition**, and it is why the settings change cannot land on its own.

### Recommended mitigation

Override `STORAGES`, not just `MEDIA_ROOT`, wherever files are written in tests:

```python
_media_override = override_settings(
    MEDIA_ROOT=_test_media_root,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
```

Explicit, local to the tests, and no conditional hack in `settings.py`. The alternative — gating on `"test" in sys.argv` — hides the behaviour in settings and is easy to get wrong.

**Both keys must be set.** `override_settings(STORAGES=...)` replaces the whole dict, so omitting `staticfiles` would drop it.

---

## Current state, quoted

`main/settings.py:363-375`:

```python
# WhiteNoise compresses and fingerprints static files for efficient serving.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Cloudinary handles user-uploaded media in production.
# Falls back to local filesystem when CLOUDINARY_CLOUD_NAME is not set (local dev).
if os.environ.get('CLOUDINARY_CLOUD_NAME'):
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
        ...
    }
```

`STORAGES` is **never defined** — confirmed by grep. Both settings above were removed in Django 5.1 and are inert in 5.2.

### Backend strings verified against installed packages

| String | Status |
|---|---|
| `cloudinary_storage.storage.MediaCloudinaryStorage` | ✅ importable |
| `cloudinary_storage.storage.RawMediaCloudinaryStorage` | ✅ importable |
| `cloudinary_storage.storage.StaticHashedCloudinaryStorage` | ✅ importable |
| `whitenoise.storage.CompressedManifestStaticFilesStorage` | ✅ importable |

```
django-cloudinary-storage  0.3.0
cloudinary                 1.44.2
whitenoise                 6.12.0
Django                     5.2.15
```

Credentials present: cloud name, API key and secret all set from `.env`. **Nothing is missing** — no package or credential blocks this.

---

## Proposed `STORAGES`

Replacing lines 363-375, keeping the existing env gate so a developer without Cloudinary credentials still gets local files:

```python
# Django 5.1 removed STATICFILES_STORAGE and DEFAULT_FILE_STORAGE; they are
# silently ignored in 5.2, which is why Cloudinary was configured but never
# actually used (finding L). STORAGES is the only form Django reads now.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

if os.environ.get("CLOUDINARY_CLOUD_NAME"):
    STORAGES["default"] = {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"}
    CLOUDINARY_STORAGE = { ... unchanged ... }
```

The old two settings are deleted rather than left beside it — leaving dead settings that look authoritative is how this was missed for months.

---

## Field inventory — 34 File/Image fields

**Exactly one is already pinned to Cloudinary**, and it is worth knowing before anything else:

| Model | Field | Storage | `upload_to` |
|---|---|---|---|
| `home.Publication` | `file` | **`RawMediaCloudinaryStorage`** | `publications/%Y/%m/` |

That field has been writing to Cloudinary all along, independent of the broken default — which is useful evidence that the credentials and code path work in production.

**The other 33 use the default** (currently `FileSystemStorage`):

| App | Model | Field(s) | `upload_to` |
|---|---|---|---|
| `home` | `AlumniProfile` | `digital_id_photo`, `qr_code_image` | `alumni/digital_id_photos/%Y/%m/%d/`, `alumni_qr_upload_path()` |
| `home` | `Article` | `article_banner_image`, `thumbnail` | `articles/banners/`, `articles/images/` |
| `home` | `Banner` | 16 fields — `image`, `logo`, `top/middle/bottom_banner`, `footer_logo`, `page_background`, `staff_qr_watermark`, `alumni_qr_watermark`, `profile_update_card_image`, `volunteer_card_image`, and 5 `program_areas/*` images | `banner/**/%Y/%m/%d/` |
| `home` | `Chapter`, `CoreValue`, `Event`, `Executive`, `Images`, `InMemoriam`, `Partner`, `Secretariat` | `thumbnail` / `background_image` / `avatar` / `photo` / `image` | various |
| `home` | `Publication` | `cover_image` | `publications/covers/` |
| `staff` | `Employee` | `qr_code_image` | `qr_upload_path()` |
| `student` | `ScholarshipApplication` | `physical_copy` | `_scholarship_physical_copy_path()` |
| `user` | `UserProfile` | `photo` | `profile_photo_path()` |

### Files on disk — local development

```
137 files, 46 MB
   88  qr_codes/
   20  banner/
   14  alumni/
    6  program_areas/
    5  employee_photos/
    3  scholarship_applications/
    1  pdf/
```

**Production counts will differ and must be taken on the host** before the move. But the shape is the point:

---

## The sequencing insight: badges do not need migrating

**64% of the files are QR badges, and badges are regenerable.**

Finding N already requires a deploy-day `generate_qr(force=True)` sweep so badges stop encoding the dev origin. That sweep **writes each badge through whatever storage is then current**. So if the storage cutover lands first, the regenerate does double duty: it re-mints with the correct production origin *and* lands the file in Cloudinary.

**So it is not two reprints — the regenerate replaces the migration for badges entirely.** That removes 88 of 137 files from the migration and leaves roughly 49 to move: banners, Digital ID photos, profile photos, scholarship attachments, and the odd PDF.

That answers the brief's question directly: **one coordinated sweep, with the storage change first.**

---

## Existing-files migration

**Recommended: a management command**, `migrate_media_to_cloudinary`, over Cloudinary's own upload tooling or a manual sync — because it must repoint the database field, not merely copy bytes, and only Django knows which rows hold which names.

### The detail that makes or breaks it

Once `STORAGES` is switched, `field.storage` **is Cloudinary** — so `field.open()` would look for the file in Cloudinary, where it does not yet exist. The command must read from the **local filesystem path explicitly**:

```python
local_path = Path(settings.MEDIA_ROOT) / instance_field.name
```

and then re-save through the field, which now writes to Cloudinary and updates the stored name.

### Shape

```
for each model/field in the inventory (excluding Publication.file, already Cloudinary):
    for each row with a non-empty field value:
        if default_storage.exists(field.name):      # already in Cloudinary
            skip                                     # -> idempotent, re-runnable
        local = MEDIA_ROOT / field.name
        if not local.exists():
            log "missing on disk" and skip           # -> handles orphaned rows
        field.save(basename(field.name), File(open(local,'rb')), save=True)
        # the local copy is NEVER deleted here
```

- **Idempotent** — skips anything already present in the new storage. That is a genuine confirmation, not bookkeeping, so a half-finished run resumes correctly.
- **Never deletes the local copy.** A separate, later, explicitly-approved cleanup removes the local tree once the Cloudinary copies are verified.
- **Handles missing files** — a row whose file is already gone is logged and skipped rather than raising.
- Wants `--dry-run` and `--model app.Model` flags so it can be rehearsed and run in slices.

**Note:** `default_storage.exists()` costs one Cloudinary API call per file. At ~49 files that is trivial; on a much larger production tree it is worth batching or a `--since` filter.

---

## Sequencing

| # | Step | Where | Notes |
|---|---|---|---|
| 1 | Test-storage override (the precondition above) | Repo | Must land **with or before** step 2, or the suite writes to live Cloudinary |
| 2 | Add `STORAGES`, delete the two dead settings | Repo | Verify `makemigrations --check` stays clean |
| 3 | Verify a **new** upload lands in Cloudinary | **Production host** | One banner or profile photo, checked in the Cloudinary console before going further |
| 4 | Take the production file count | **Production host** | The local 137 is not the real number |
| 5 | `migrate_media_to_cloudinary --dry-run`, then for real | **Production host** | Reads `MEDIA_ROOT`, so it must run where the files are |
| 6 | `generate_qr(force=True)` sweep | **Production host** | Finding N's regenerate; also lands badges in Cloudinary — replaces migrating them |
| 7 | `collectstatic` | **Production host** | Required by the manifest backend — see below |
| 8 | Verify, then (separately approved) remove the local media tree | **Production host** | Only after Cloudinary copies are confirmed |

Steps 3-8 are **production-host-only**. Nothing about this can be completed from a developer machine.

### Relative to the Neon → VPS migration

**Do the storage fix first.**

Media currently lives on the VPS filesystem. Any rebuild, resize or replacement of that box during the database migration risks stranding 46 MB of banners, Digital ID photos and scholarship attachments that exist nowhere else. Moving media to Cloudinary *first* takes it off the machine being changed, and makes the VPS move a database-only operation.

Doing it the other way round means carrying a media tree through the migration for no benefit.

---

## Static files

**Recommended: `whitenoise.storage.CompressedManifestStaticFilesStorage`** — restoring the intent of the setting that was silently ignored. It is separate from media and lower risk, but the `STORAGES` dict must set **both** keys or the `staticfiles` entry regresses to Django's plain default.

**`collectstatic` must run after, and must succeed.** The manifest backend raises at template-render time for any `{% static %}` reference missing from the manifest — so a failed or skipped `collectstatic` turns into a 500 on every page using that asset. That is the sharpest edge in this whole design.

**Safer intermediate if you would rather not adopt manifest strictness in the same change:** `whitenoise.storage.CompressedStaticFilesStorage` — compression without hashing or the manifest, and no render-time failure mode. It can be upgraded later.

---

## Risks

| Risk | Consequence | Mitigation |
|---|---|---|
| **Tests write to live Cloudinary** | Silent pollution of a production account | The `STORAGES` override above — a precondition, not a follow-up |
| Bad backend string | `ImproperlyConfigured` at startup — total outage | All four strings verified importable above |
| Manifest storage without `collectstatic` | 500 on every page referencing a missing asset | Step 7; or start with `CompressedStaticFilesStorage` |
| Only one `STORAGES` key set | The other silently regresses to Django's default | Always write both |
| Migration reads through the new storage | Every file "missing" | Read from `MEDIA_ROOT` explicitly |
| Local tree deleted too early | Irrecoverable loss | Never delete in the command; separate approved step |
| Cloudinary quota / plan limits | Upload failures mid-run | Take the production count first (step 4); the command is resumable |

---

## Migration file

**None expected.** `STORAGES` is a setting; field definitions do not change, and `upload_to` is untouched. Django records `storage` in a field's deconstruction only when it is explicitly pinned — which applies to `Publication.file` alone, and that field is not being changed.

**To be verified in the apply pass** with `makemigrations --check --dry-run`, since it cannot be checked here without changing the setting.

---

## Branch

This is a production settings change with a data move. **Recommend `fix/finding-l-storage` off `coverage/phase-1`**, separate from the coverage stream. **Not created** — say the word.

---

## Decisions needed

1. **Approve the `STORAGES` dict**, including deleting the two dead settings rather than leaving them?
2. **Static backend** — WhiteNoise manifest (restores intent, needs `collectstatic` to succeed) or the safer `CompressedStaticFilesStorage` first?
3. **Confirm the test-storage override lands in the same pass** — I would not apply the settings change without it.
4. **Confirm storage-before-VPS-migration**, and that the badge regenerate absorbs the badge migration.
5. **Branch** — create `fix/finding-l-storage`?

🛑 Design complete — awaiting confirmation.
