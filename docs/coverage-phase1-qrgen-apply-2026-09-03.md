# Coverage priority 6 — QR badge generation covered

**Date:** 2026-09-03
**Branch:** `coverage/phase-1`
**Commit:** `dd5461e`
**Executes:** [`coverage-phase1-qrgen-step1-2026-09-02.md`](coverage-phase1-qrgen-step1-2026-09-02.md)

**No production code changed.** `git status` showed only `apps/qr_manager/tests.py`.

---

## Result

| | Before | After |
|---|---:|---:|
| `apps/qr_manager/models.py` | 58% | **96%** |
| Overall | 67% | 69% |
| Suite | 223 tests | **241, all green** |

Twenty tests. The eight statements still uncovered are the deliberately-defensive branches: the two silent `except` blocks (findings P and Q), `clean`'s `ValidationError`, and two `is_valid`/`status` arms.

Scan *verification* was already covered by the QA-500 sweep; this pass was the **minting** path, which is the half where a defect gets reprinted rather than redeployed.

---

## Findings M and N — pinned, not fixed

### M — the two lost-badge levers do not behave alike

| Lever | Effect on a scan |
|---|---|
| `rotate_token()` | ✅ **403** — `secrets.compare_digest` fails, the invalid page renders |
| `revoke()` | ❌ **200** — the card still renders; only the `ScanLog` row reads `REVOKED` |

`verify_scan` never consults `is_valid` or `is_active`. Its own docstring says validity enforcement is *"deferred by design"*, so this is recorded rather than raised as a defect — but the practical consequence deserves stating: **a lost badge that is revoked rather than rotated remains fully scannable.**

A second half, also asserted: `rotate_token()` does not regenerate the image, so the stored badge keeps encoding the old token until somebody regenerates by hand. The docstring says *"Regenerate + reprint afterwards"* — a manual step with nothing enforcing it.

### N — the encoded origin is baked in, and regeneration is opt-in

`scan_url` reads `settings.QR_SCAN_ORIGINS` at **call time**, so whatever origin is configured when a badge is minted goes onto paper permanently. Asserted both ways:

- Under production origins, a staff badge starts `https://staff.uonalumni.or.ke/qr/`, an alumni badge `https://www.uonalumni.or.ke/qr/`, and a holder-less code falls back to the alumni origin.
- Under dev origins, the badge encodes `lvh.me:8000` — with nothing in `generate_qr` validating that the origin looks like production.

Compounded by the early return: `generate_qr` skips regeneration unless `force=True`, so the deploy-day regenerate depends entirely on that flag being passed. A test pins that a rotation followed by a plain `generate_qr()` leaves the old file in place.

---

## Also pinned

| Behaviour | Why it matters |
|---|---|
| The filename is the holder **UUID**, not the slug | A slug change would orphan printed badges |
| Watermark selection is holder-typed | Two distinct institutional marks — the Association's for alumni, the university crest for staff — not one generic logo |
| A missing watermark yields a **silent unwatermarked badge** | `_qr_watermark_image` returning `None` is tolerated rather than raising |
| `delete()` clears the holder's image | Otherwise the profile keeps showing a badge that scans `UNKNOWN` |
| `save_holder=False` leaves the row unwritten | The in-memory field is set; the database is not |
| `unit_q_for` builds the right `Q` for all three unit types | And returns `False` for a non-supervisor |

---

## Two tests I went back and finished

Worth recording, because in both cases the test would have **passed while proving less than the list asked for**.

**Test 12** was specified as *"`_qr_watermark_image` returns `None` when neither exists"*. My first version mocked the helper to return `None`, which proved `generate_qr` tolerates it but never executed the real branch at `models.py:60`. It now points `BASE_DIR` at an empty temporary directory so the genuine no-Banner-no-static path runs — `BASE_DIR` is read at call time, so `override_settings` reaches it.

**Test 18** was specified as *"the right `Q` for each unit type"*. I had covered only `service_unit`. It now covers department and research-unit supervisors as well.

Neither would have failed. Both would have left a gap the coverage number would not have shown.

---

## Method notes

- **The existing module-level temp `MEDIA_ROOT` block was reused**, not duplicated — `setUpModule`/`tearDownModule` were already at the top of `apps/qr_manager/tests.py` from the QA-500 sweep.
- **No Cloudinary mocking was needed.** Finding L means `default_storage` is `FileSystemStorage`, so the writes are real, local, and carry no live-call risk. The mocking question that opened this pass answered itself.
- **Real PIL-generated PNGs throughout.** `ResizedImageField` and PIL both read the bytes back; a hand-rolled blob fails, as the QR-badge PDF pass established.
- **`override_settings` works for the origin.** `scan_url` reads settings at call time — unlike `adapter.py:17-33`, nothing here is captured at import.

---

## Findings ledger

| # | Finding | State |
|---|---|---|
| — | Numbering skips on renewal | Documented |
| — | `activate_membership` recomputes `expires_on` | Documented in code (`73dad3e`) |
| A | `get_connect_redirect_url` returns `None` | Retracted |
| B | Bare `home:` reverse 500ing staff login | ✅ Fixed |
| C | `RESTRICT_*` parsing fails open | Retracted; hardened anyway |
| D | Payment completed outside the bulk action | ✅ Fixed |
| E | Refund does not reverse activation | 🛑 Open — policy decision |
| F | Registration rejects the registrant's own phone | ✅ Fixed |
| G | Whitespace defeats ID uniqueness | Retracted |
| H | 1-cent instalment activates any tier | Documented — Association decision |
| I | Two `clean()` methods are verbatim duplicates | Documented |
| J | No size limit on the Digital ID photo | 🛑 Open — needs a limit |
| K | `installment_amount` wrongly required | ✅ Fixed |
| **L** | **`STORAGES` unset — Cloudinary and WhiteNoise manifest both inert** | 🛑 **Open — largest item, settings change** |
| **M** | **`revoke()` does not block a scan** | Documented — deferred by design |
| **N** | **Badge origin baked in; regeneration opt-in** | Documented |
| O–R | Silent excepts around generation and delete | Documented |

**Sixteen entries: four fixed, three retracted, seven documented, three open.**

---

## Where the coverage build stands

| Priority | Area | Status |
|---:|---|---|
| 1 | `services.py` lifecycle | ✅ 100% |
| 2 | `expire_lapsed_installment_plans` | ✅ Covered |
| 3 | `adapter.py` OAuth | ✅ 86% |
| 4 | Payment-confirmation path | ✅ `payments.py` 100% |
| 5 | `home/forms.py` | ✅ 99% |
| 6 | `qr_manager` generation | ✅ **96%** |
| 7 | `home/views.py` / `staff/views.py` POST handling | ~53% — **next** |
| 8 | `Membership` model behaviour | 90% |
| 9 | `tasks.py` e-mail and SMS | 18% |
| 10 | `import_legacy_memberships` | 0% |

Six of ten priorities done; overall 59% → 69%.

## Next

1. **Finding L** — still the largest open item, and it touches media durability and static-asset delivery. Worth taking before the Neon → VPS migration, since media is currently on the VPS filesystem rather than a CDN.
2. **Finding E** (refund policy) and **J** (photo size limit) — both still waiting on a decision from you.
3. **Coverage priority 7** — `home/views.py` and `staff/views.py` POST handling at roughly half covered. The QA-500 matrix proved they do not 500; it never proved the write paths are correct.
4. **Branch housekeeping** — four stacked unmerged branches from this work: `feature/qa-500-tests`, `coverage/phase-1`, `fix/finding-d-payment-activation`, `fix/forms-fk`.
