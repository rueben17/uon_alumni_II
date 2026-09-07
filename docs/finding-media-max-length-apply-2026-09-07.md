# Media field 500s: `value too long for type character varying(100)`

**Date:** 2026-09-07
**Trigger:** live 500 on `/2005/home/banner/1/change/` uploading a fresh banner image.

## Cause

Django's `FileField`/`ImageField` default `max_length` for the stored filename is 100 characters, and none of the 34 `ImageField`/`FileField`/`ResizedImageField` instances across the project set one explicitly. This project's `upload_to` paths are deep (`banner/top_banner/%Y/%m/%d/`), and Cloudinary's `MediaCloudinaryStorage` appends its own uniqueness suffix on top of that — routinely pushing the combined path + original filename past 100 characters. Same root cause as `UserProfile.city` earlier the same day, just on the media fields.

Live example that actually failed: a `banner/top_banner/2026/09/07/` prefix plus a normal camera-length filename comfortably exceeds 100 characters before Cloudinary even adds its suffix.

## Fix

Two changes, both root-cause, not just a wider column:

1. **`max_length=255`** added to all 34 fields (`apps/home/models.py` ×31, `apps/user/models.py`, `apps/student/models.py`, `apps/staff/models.py` ×1 each) — safety margin.
2. **Stripped `%Y/%m/%d/`/`%Y/%m/` date-nesting from every string `upload_to`** (20 fields) — the actual source of the excess length. Callable `upload_to` functions (`profile_photo_path`, `alumni_qr_upload_path`, `qr_upload_path`, `_scholarship_physical_copy_path`) were already short and UUID-keyed; left untouched.

Forward-only: `upload_to` only affects where a field saves a *new* upload. Existing rows keep whatever name they already have — nothing needed migrating.

## Verified

- `makemigrations`: 4 migrations, pure `AlterField` operations only (`home.0044`, `staff.0003`, `student.0004`, `user.0004`).
- 288 tests, OK. `makemigrations --check`: no changes detected.

## Note on the commit

Landed bundled into `d0d9191` ("Wire the Secretariat Membership CRM route") along with an earlier missed commit for the CRM's URL wiring — a staging mistake (unstaging one unrelated file left the rest of the index staged, then a routine `git add` swept it all into one commit together). Not re-split after the fact — both changes are individually correct and tested, just not documented in that commit's own message. Flagging here so `git log` and this note agree on what actually shipped.
