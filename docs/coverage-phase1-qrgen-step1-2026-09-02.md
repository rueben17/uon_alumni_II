# Coverage priority 6 — QR generation characterisation

**Date:** 2026-09-02
**Branch:** `coverage/phase-1`
**Baseline:** `apps/qr_manager/models.py` 58%
**Status:** 🛑 **Read-and-report only — no test written, no source touched.**

---

## ⚠ Finding L — the storage settings are inert. Cloudinary is not in use.

Found while answering the mocking question, and it matters well beyond this pass.

`main/settings.py` configures storage the pre-Django-4.2 way:

```python
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'   # :365

if os.environ.get('CLOUDINARY_CLOUD_NAME'):
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'    # :370
```

**Both settings were removed in Django 5.1 and are silently ignored in 5.2.** `STORAGES` is never defined anywhere in `settings.py`, so Django falls back to its own defaults. Verified at runtime:

```
Django version: 5.2.15
CLOUDINARY_CLOUD_NAME in env : True
DEFAULT_FILE_STORAGE setting : cloudinary_storage.storage.MediaCloudinaryStorage
default_storage class        : django.core.files.storage.filesystem.FileSystemStorage   <-- not Cloudinary

STATICFILES_STORAGE setting  : whitenoise.storage.CompressedManifestStaticFilesStorage
staticfiles_storage class    : django.contrib.staticfiles.storage.StaticFilesStorage    <-- not WhiteNoise

settings.STORAGES = {'default':    {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                     'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
```

`Employee.qr_code_image.storage` likewise resolves to `FileSystemStorage`.

### What that means in production

1. **All user-uploaded media is on the VPS filesystem, not Cloudinary** — QR badges, Digital ID photos, banners, scholarship attachments. `cloudinary_storage` is installed, credentialed via `.env`, and never used. Any assumption of Cloudinary durability, backup or CDN delivery is currently false.
2. **WhiteNoise's compression and manifest fingerprinting are not active.** The WhiteNoise *middleware* still serves static files, but through plain `StaticFilesStorage` — so no hashed filenames and no pre-compressed assets.

Neither fails loudly. There is no startup warning; the settings simply have no effect.

**The fix is a `STORAGES` dict**, which is a settings change and out of scope here. Flagged for its own gated pass. Note it also interacts with the [VPS migration](../docs/) already on the roadmap: media currently living on the VPS filesystem is a fact worth knowing *before* that move, not after.

**For this pass it is good news:** there is no live-Cloudinary risk, so temp `MEDIA_ROOT` alone is a sufficient and honest test strategy.

---

## Candidate finding M — `revoke()` does not stop a scan

```python
    def revoke(self):
        self.is_active = False
        self.save(update_fields=["is_active"])
```

`verify_scan` checks the holder, then the token, then logs `qr_code.status` and renders the card. **It never consults `is_valid` or `is_active`.** So a revoked badge still renders a normal verification card; the only effect of `revoke()` is that the ScanLog row reads `REVOKED`.

This is **documented as deliberate** — `verify_scan`'s docstring says validity enforcement is *"deferred by design… switching it on later is a few lines here"*. Recorded rather than raised as a defect, but the asymmetry is worth stating plainly, because the two lost-badge levers behave differently:

| Lever | Actually invalidates a scan? |
|---|---|
| `rotate_token()` | ✅ **Yes** — `secrets.compare_digest` fails, 403 + invalid page |
| `revoke()` | ❌ **No** — card still renders; only the log line changes |

`rotate_token` has a second characteristic worth pinning: it changes the token but **does not regenerate the image**, so `holder.qr_code_image` still encodes the old token until someone regenerates. The docstring says *"Regenerate + reprint afterwards"* — a manual step with nothing enforcing it.

---

## Candidate finding N — the encoded origin is baked in, and regeneration is opt-in

`scan_url` reads the origin at call time:

```python
        origin_key = "staff" if self.employee_id else "alumni"
        origin = settings.QR_SCAN_ORIGINS[origin_key]
        return f"{origin.rstrip('/')}/qr/{self.id}/?t={self.token}"
```

`QR_SCAN_ORIGINS` is chosen in `settings.py` by an `if DEBUG:` branch, with env-var overrides. Under the current environment it resolves to:

```
{'staff': 'http://staff.lvh.me:8000', 'alumni': 'http://www.lvh.me:8000'}
```

So **a badge generated while `DEBUG=True` permanently encodes `lvh.me:8000`** into a printed artefact. The settings comment states the intent — *"a QR is a permanent artifact, so the URL it carries must never depend on what mode the generating process happened to run in"* — but the value **is** derived from `DEBUG`; only the env-var override escapes that.

Two things compound it:

- **Nothing in `generate_qr` validates the origin.** No check that it looks like production, no warning.
- **Regeneration is opt-in.** `generate_qr` returns early when an image already exists:

  ```python
        if holder.qr_code_image and not force:
            return holder.qr_code_image.url
  ```

  So the deploy-day regenerate step depends entirely on someone passing `force=True`. Without it, existing badges silently keep whatever origin they were minted with.

The failure is silent at every stage and only surfaces when a member scans a printed badge and reaches nothing.

---

## Smaller observations

| # | Where | Behaviour |
|---|---|---|
| O | `_qr_watermark_image:50` | `file.open("rb")` has **no** try/except. A Banner watermark whose file is missing from storage raises, and the exception propagates out of `generate_qr` — so one broken watermark file breaks **all** badge generation. |
| P | `generate_qr:291-295` | `qr_img.save(..., dpi=(300,300))` falls back to a plain save inside a bare `except Exception`. A genuine failure to embed 300 DPI is silent — a print-quality regression on a physical artefact, invisible until it is printed. |
| Q | `generate_qr:251-254` | The `force` branch's `qr_code_image.delete(save=False)` is wrapped in `except Exception: pass`, so a failed delete silently orphans the old file. |
| R | `delete():304-312` | `super().delete()` runs **before** the image delete, with no try/except. If the image delete fails, the QRCode row is already gone and the file is orphaned with no record pointing at it. |

`_qr_watermark_image` also iterates **every** `Banner` row in Python (`for banner in Banner.objects.all()`) to find the first truthy field. The comment explains why it is not a DB filter — SQL three-valued logic makes `.exclude(field="")` let NULL rows through — which is correct reasoning; the cost is loading all banners.

---

## `generate_qr`, step by step

| Step | Lines | Behaviour |
|---|---|---|
| Holder guard | 244-246 | Returns `None` for a label-only code (visitor/event pass) |
| Existing-image guard | 248-249 | Returns the existing URL unless `force` |
| Force delete | 250-254 | Deletes the old image, swallowing failures (Q) |
| URL | 256 | `self.scan_url` — the origin decision (N) |
| QR build | 258-270 | version 1, `ERROR_CORRECT_M`, `box_size=40`, `border=6`, `StyledPilImage` + `CircleModuleDrawer`, converted to RGBA |
| Watermark | 275-288 | Holder-typed crest, thumbnailed to 25% of width, white padding box, alpha-composited centre |
| Encode | 290-296 | PNG at 300 DPI, with the silent fallback (P) |
| Write | 298-300 | `holder.qr_code_image.save(f"{holder.pk}.png", ...)`, filename is the holder **UUID** (stable), `save_holder` controls the model save |
| Return | 301 | `holder.qr_code_image.url` |

Watermark selection is by **holder type**: `is_alumni=bool(self.alumni_profile_id)` → the Association mark for alumni, the university crest for staff. Two distinct institutional marks, not one generic logo.

## `Supervisor` — uncovered methods

`unit` (first non-null of department/service/research), `clean` (exactly one must be set, else `ValidationError`), `__str__`, and `unit_q_for(user, prefix="")` — which builds an OR'd `Q` across every unit the user supervises, with `prefix` letting it filter both `Employee` (`prefix=""`) and `QRCode` (`prefix="employee__"`) querysets. Returns `False` when the user supervises nothing.

---

## Mocking strategy

| Concern | Approach |
|---|---|
| **Cloudinary** | **Not a risk** — finding L means `FileSystemStorage` is active. Temp `MEDIA_ROOT` is sufficient and honest. No mocking needed, no live calls possible. |
| Image writes | The module-level `setUpModule`/`tearDownModule` temp `MEDIA_ROOT` block **already exists** at the top of `apps/qr_manager/tests.py` — reuse it rather than adding a second. |
| Watermark images | Real PNGs via PIL, as the QR-badge PDF pass established; a hand-rolled blob fails when PIL reads it back. |
| Origin | `scan_url` reads `settings.QR_SCAN_ORIGINS` **at call time**, so `override_settings` works — unlike `adapter.py:17-33`, nothing here is captured at import. |
| Banner fixtures | Needed for the watermark-from-Banner branch; the static-file fallback needs no fixture. |
| Host | None. This is all model-level — **no `HTTP_HOST` anywhere**. |

Nothing is untestable without a live call.

---

## Proposed test list — 18 tests

**`generate_qr` (8)**
1. A holder-less code returns `None` and writes nothing.
2. Happy path: an image is written to `qr_code_image` and a URL returned.
3. The filename is the holder's **UUID**, not the slug.
4. **The encoded URL carries the right origin** — staff badge → staff origin, alumni badge → alumni origin, asserted under `override_settings` (finding N).
5. The encoded URL contains the id and the current token.
6. An existing image is **not** regenerated without `force`.
7. `force=True` regenerates, and the encoded token changes after `rotate_token`.
8. `save_holder=False` leaves the holder unsaved.

**`_qr_watermark_image` (4)**
9. An admin-uploaded Banner watermark is used when present.
10. Alumni and staff select **different** fields (`alumni_qr_watermark` / `staff_qr_watermark`).
11. Falls back to the static crest when no Banner carries one.
12. Returns `None` when neither exists, and `generate_qr` still produces a badge (silent, unwatermarked).

**`rotate_token` / `revoke` / `delete` (5)**
13. `rotate_token` changes the token and the **old token now fails** `verify_scan` — the real invalidation.
14. `rotate_token` does **not** regenerate the image, so the stored badge still encodes the old token (finding M's second half).
15. **`revoke()` does not block a scan** — the card still renders; only `status` reads `REVOKED` (finding M, current behaviour).
16. `delete()` removes the row **and** clears the holder's image.
17. `delete()` on a holder-less code does not raise.

**`Supervisor` (1, with subTests)**
18. `unit` picks the set one; `clean` rejects zero or two units; `unit_q_for` builds the right `Q` for each unit type and returns `False` for a non-supervisor.

---

## Awaiting sign-off

1. **Approve the 18-test list?**
2. **Findings M and N** — write as documented reproductions asserting current behaviour, as with D, F and K?
3. **Finding L is the big one and is out of this pass's scope.** It is a settings change (`STORAGES` dict) with production consequences for media durability and static-asset delivery. Worth its own gated pass, and worth knowing before the Neon → VPS migration, since media is currently on the VPS filesystem rather than Cloudinary.

🛑 Characterisation + test list complete — awaiting sign-off.
