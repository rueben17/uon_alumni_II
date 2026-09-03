# Finding L — storage fix applied (code half)

**Date:** 2026-09-03
**Branch:** `fix/finding-l-storage` (off `coverage/phase-1`)
**Commits:** `d09c3da` (settings + test isolation), `8c3d05a` (command + runbook)
**Executes:** [`finding-L-storage-design-2026-09-03.md`](finding-L-storage-design-2026-09-03.md)

**249 tests green.** `makemigrations --check` clean.

**Nothing was executed against production or Cloudinary** — no upload, no `collectstatic`, no badge regenerate, no file moved or deleted. Those are the [runbook](finding-L-runbook-2026-09-03.md).

---

## Commit 1 — `STORAGES`, and the isolation it required

### The settings change

```python
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

if os.environ.get('CLOUDINARY_CLOUD_NAME'):
    STORAGES['default'] = {
        'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage',
    }
```

Verified at runtime:

```
STORAGES default     : cloudinary_storage.storage.MediaCloudinaryStorage
STORAGES staticfiles : whitenoise.storage.CompressedStaticFilesStorage
default_storage      : MediaCloudinaryStorage
staticfiles_storage  : CompressedStaticFilesStorage
dead settings gone   : True True
```

Both `STATICFILES_STORAGE` and `DEFAULT_FILE_STORAGE` are **deleted**, not left beside the new dict. Settings that still read as authoritative but do nothing are exactly what hid this for months.

`CompressedStaticFilesStorage`, not the Manifest variant — as decided. The manifest backend raises at render time for any `{% static %}` reference missing from the manifest, so a skipped `collectstatic` becomes a 500 on every page using that asset. Compression now; hashing as its own deliberate change once `collectstatic` is reliably part of the deploy.

### The isolation, asserted rather than assumed

`MEDIA_ROOT` is a `FileSystemStorage` concept. With Cloudinary as the default it stops isolating anything, and the suite's file-writing tests would upload to the live account — **while still passing**. That is the whole reason this had to land in the same commit.

All three `MEDIA_ROOT` overrides now set `STORAGES` too, with **both** keys, since `override_settings` replaces the whole dict:

- `apps/qr_manager/tests.py` — the module-level block
- `apps/home/tests.py` — two class-level overrides

And two guard tests prove it took effect, rather than inferring it from the absence of errors:

| Test | Asserts |
|---|---|
| `test_writes_stay_on_the_local_filesystem` | `default_storage` is `FileSystemStorage`; `MEDIA_ROOT` is the throwaway root |
| `test_a_generated_badge_lands_in_the_temp_directory` | End to end — the PNG is on disk under that root, not in a bucket |

A green suite is not evidence of isolation here. These two are.

---

## Commit 2 — the migration command

`apps/home/management/commands/migrate_media_to_cloudinary.py`, with `--dry-run` and `--model app.Model`.

A management command rather than Cloudinary's own upload tooling because the bytes are the easy half: the **database rows have to be repointed**, and only Django knows which row holds which name.

### The detail that would have quietly broken it

It reads from `MEDIA_ROOT` **explicitly**:

```python
    local_path = media_root / name
```

not through `field.open()`. Once `STORAGES` points at Cloudinary, the field's own storage looks *there* — where the file does not exist yet — so reading through it would have reported **every** file as missing and moved nothing. Silently, with a cheerful summary line.

### Safety properties, in the order that matters

1. **It never deletes the local copy.** Removing the tree is runbook step 8, separately approved. That is what keeps rollback available throughout.
2. **It is idempotent** — a file already present in the target storage is skipped. That check is `default_storage.exists()`, a real confirmation rather than bookkeeping, so an interrupted run resumes correctly.
3. **A row whose file is already gone is logged and skipped**, so one orphan cannot halt the run.
4. **`--dry-run` writes nothing**, locally or remotely, and is the posture the tests exercise.

`home.Publication.file` is excluded: it is pinned to `RawMediaCloudinaryStorage` on the model and has been writing to Cloudinary all along, independent of the broken default.

### Six tests, all on filesystem storage

Nothing to move when files are already present; a missing-on-disk row logged and skipped; `--dry-run` mutates no field; `--model` slicing; an unknown model rejected with `CommandError`; and `Publication.file` confirmed excluded.

No Cloudinary call is possible from any of them.

**One test correction worth noting:** my first version asserted `"would move"` was absent from a dry run with nothing to move — but the summary line legitimately reads *"0 file(s) would move"*. The assertion now targets the per-file line, `"  would move:"`. A loose substring that happened to match the summary would have made the test pass or fail for the wrong reason.

---

## Why the badge regenerate sits inside the runbook

`generate_qr(force=True)` does **two** jobs, which is why it belongs mid-runbook rather than as a separate reprint:

1. Re-mints every badge with the **production** scan origin — closing finding N, since a badge minted under DEBUG settings carries `lvh.me:8000` onto paper permanently.
2. Writes each badge through the new storage — so **badges never need migrating at all**.

Badges are roughly two-thirds of the media (88 of 137 files locally). Sequencing the regenerate after the storage change removes them from the migration entirely.

The runbook flags the precondition: confirm `QR_SCAN_ORIGINS` reads production values **before** running it. Re-minting with the wrong origin would be worse than not re-minting.

---

## What remains — all on the production host

The [runbook](finding-L-runbook-2026-09-03.md) has eight ordered steps: deploy, verify one live upload, take the real file count, dry run, migrate, regenerate badges, `collectstatic`, then a separately-approved removal of the local tree.

**Rollback is available right up to step 8**, because nothing before it destroys anything. That ordering is deliberate, not incidental.

**⚠ It precedes the Neon → VPS migration.** Media is on the VPS filesystem; any rebuild of that box during the database move would strand it. Doing storage first makes the VPS migration a database-only operation.

---

## Ledger

| # | Finding | State |
|---|---|---|
| A, C, G | — | Retracted (my misreads) |
| B, D, F, K | — | ✅ Fixed |
| E | Refund does not reverse activation | 🛑 Open — **policy decision needed** |
| H, I, M, N, O–R | — | Documented |
| J | No size limit on the Digital ID photo | 🛑 Open — **needs a limit from you** |
| **L** | **`STORAGES` unset** | ✅ **Code fixed; host runbook pending** |

---

## Next

1. **Run the runbook**, before the VPS migration.
2. **Findings E and J** — both still waiting on a decision.
3. **Coverage priority 7** — `home/views.py` / `staff/views.py` POST handling at ~53%.
4. **Branch housekeeping.** Five unmerged branches now stack on each other:
   `feature/qa-500-tests` → `coverage/phase-1` → `fix/finding-d-payment-activation`, `fix/forms-fk`, `fix/finding-l-storage`. Worth deciding a merge order before the stack gets harder to reason about — the three `fix/*` branches are independent of each other but all sit on top of `coverage/phase-1`.
