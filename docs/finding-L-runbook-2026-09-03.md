# Finding L — production runbook

**Date:** 2026-09-03
**Branch:** `fix/finding-l-storage`
**Design:** [`finding-L-storage-design-2026-09-03.md`](finding-L-storage-design-2026-09-03.md)

**⚠ This must run BEFORE the Neon → VPS migration.** Media currently lives on the VPS filesystem. Any rebuild, resize or replacement of that box strands ~46 MB of banners, Digital ID photos and scholarship attachments that exist nowhere else. Moving media to Cloudinary first takes it off the machine being changed and makes the database migration a database-only operation.

---

## What has already been done in code

| | |
|---|---|
| `STORAGES` defined in `main/settings.py` | Cloudinary as the media default, inside the existing `CLOUDINARY_CLOUD_NAME` gate |
| The two dead settings deleted | `STATICFILES_STORAGE`, `DEFAULT_FILE_STORAGE` |
| Static backend | `whitenoise.storage.CompressedStaticFilesStorage` — compression, **not** the manifest variant |
| Test isolation | Every `MEDIA_ROOT` override now sets `STORAGES` too, with two guard tests proving it |
| `migrate_media_to_cloudinary` | Written, `--dry-run` tested, **never run for real** |

**Nothing below has been executed.** No Cloudinary write, no `collectstatic`, no badge regenerate, no file moved or deleted.

---

## The steps — all on the production host

Every step from here needs the machine where the files actually are. None of it can be completed from a developer laptop.

### 1. Deploy the code

Ship `fix/finding-l-storage`. From this moment **new** uploads go to Cloudinary; existing rows still point at local paths.

### 2. Verify one new upload actually lands in Cloudinary

Upload a single Banner image or profile photo through the admin, then **confirm it in the Cloudinary console** before going any further.

If this does not work, stop. Everything downstream assumes it does.

### 3. Take the real file count

```bash
find media -type f | wc -l
find media -type f | sed 's|^media/||; s|/.*||' | sort | uniq -c | sort -rn
du -sh media
```

Local development shows **137 files / 46 MB**, of which 88 are QR badges. **Production will differ** — take the real number before sizing anything.

### 4. Dry run the migration

```bash
python manage.py migrate_media_to_cloudinary --dry-run
```

Reports what would move, what is already present, and any row whose file is missing from disk. **Writes nothing.** Read the output before proceeding — particularly the missing-on-disk lines, which are rows pointing at files that are already gone.

Slice it if you want to rehearse a subset:

```bash
python manage.py migrate_media_to_cloudinary --dry-run --model home.Banner
```

### 5. Run the migration

```bash
python manage.py migrate_media_to_cloudinary
```

- **Idempotent** — a file already in Cloudinary is skipped, so an interrupted run resumes cleanly.
- **Never deletes the local copy.** Removing the local tree is step 8, separately approved.
- `home.Publication.file` is excluded: it is pinned to `RawMediaCloudinaryStorage` on the model and has been writing to Cloudinary all along.

### 6. Regenerate the QR badges

```python
# manage.py shell
from apps.qr_manager.models import QRCode
for code in QRCode.objects.all():
    code.generate_qr(force=True)
```

**`force=True` is essential.** Without it `generate_qr` returns early on any badge that already has an image, and nothing happens.

This step does **two** jobs at once, which is why it belongs here rather than being a separate reprint:

1. Re-mints every badge with the **production** scan origin, closing finding N — a badge minted under DEBUG settings encodes `lvh.me:8000` permanently.
2. Writes each badge through the new storage, so **badges never need migrating in step 5** — they are roughly two-thirds of the files.

Confirm `settings.QR_SCAN_ORIGINS` reads the production values **before** running this. Re-minting with the wrong origin would be worse than not re-minting at all.

### 7. Collect static

```bash
python manage.py collectstatic --noinput
```

Required by the new static backend. `CompressedStaticFilesStorage` compresses but does **not** hash or write a manifest, so a missed `collectstatic` degrades performance rather than causing a 500 — which is precisely why the manifest variant was not adopted in the same change.

### 8. Verify, then remove the local tree — separately approved

Only after spot-checking that media renders from Cloudinary URLs across banners, a Digital ID photo, a QR badge and a scholarship attachment.

**Do not delete anything before that check.** The command deliberately leaves every local file in place so this remains a conscious, reversible decision rather than a side effect.

---

## If something goes wrong

| Symptom | Likely cause | Action |
|---|---|---|
| Media 404s after deploy | Rows still point at local names; step 5 not run or incomplete | Re-run step 5 — it is idempotent |
| Uploads fail at step 2 | Credentials or plan limits | Check `CLOUDINARY_*` in the host environment; stop until resolved |
| Badges scan to `lvh.me` | Step 6 skipped, or run without `force=True` | Confirm `QR_SCAN_ORIGINS`, re-run with `force=True` |
| Static assets uncompressed | Step 7 skipped | Run `collectstatic` |
| Need to roll back | — | Revert the `STORAGES` commit. The local tree is still intact — which is why step 8 is last and separate. |

**Rollback is genuinely available right up until step 8**, because nothing before it destroys anything. That ordering is deliberate.

---

## Not in scope here

- Adopting `CompressedManifestStaticFilesStorage` — a later deliberate change, once `collectstatic` is reliably part of the deploy.
- Removing the local media tree — step 8, needs its own approval.
- The Neon → VPS migration itself — separate work, and this runbook precedes it.
