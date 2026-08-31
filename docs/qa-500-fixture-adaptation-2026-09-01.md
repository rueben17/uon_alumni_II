# Fixture adaptation to the `UserProfile` invariant

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Commit:** `78aaac3`
**Follows:** [`qa-500-userprofile-signal-apply-2026-09-01.md`](qa-500-userprofile-signal-apply-2026-09-01.md)

Test-only. No production code, signal, migration, settings or real-data change.

---

## The collision

`UserProfile`'s primary key **is** the `User`'s primary key (`apps/user/models.py:178-180`, `primary_key=True` on the `OneToOneField`). Once `apps/user/signals.py` began auto-creating a profile for every new `User`, any fixture still calling `UserProfile.objects.create(user=u, ...)` duplicated a row that already existed:

```
IntegrityError: duplicate key value violates unique constraint "user_userprofile_pkey"
```

failing in `setUpClass`, which takes the whole class down with it.

## The fix — identical at each site

Fill the auto-created row rather than making a second one, preserving each fixture's original field values:

```python
profile = user.profile
profile.given_name = given
profile.family_name = family
profile.save(update_fields=["given_name", "family_name"])
```

| Site | Class | Values preserved |
|---|---|---|
| `apps/staff/tests.py:40` | `NavbarStaffHostGuardTests` (via `_make_user`) | `given_name="Test"`, `family_name="Person"` |
| `apps/staff/tests.py:228` | `StaffEmployeeGatingTests` | `given_name="Badge"`, `family_name="Admin"` |
| `apps/qr_manager/tests.py:671` | `VerifyScanMissingProfileTests` | `given_name="Badge"`, `family_name="Holder"` |

`apps/staff/tests.py` does this twice, so it gained a small `_name_profile` helper mirroring the one already in `apps/home/tests.py`. Its `UserProfile` import became unused and was removed.

**Only `VerifyScanMissingProfileTests` was touched in `apps/qr_manager`.** The four pre-existing `Employee() got unexpected keyword arguments: 'given_name', 'family_name'` fixture errors are deliberately left exactly as they are — they predate this sweep and belong to deferred OAuth work.

---

## Suite state — and one thing worth flagging

**84 tests, 5 errors.**

| Error | Status |
|---|---|
| 4 × `qr_manager` `setUpClass` — `Employee()` kwargs | Pre-existing, untouched, unchanged |
| `VerifyScanMissingProfileTests.test_scan_survives_a_holder_whose_profile_row_is_gone` | **Finding 4's genuine reproduction** |

The acceptance criteria for this pass anticipated *"only the four pre-existing errors remain"*. That could not hold, and the reason is worth recording rather than glossing.

That fifth error is **no longer a collision**. `setUpClass` now passes; the failure has moved to the test body and is the real defect:

```
Internal Server Error: /qr/01ef8a72-7b24-4ac5-98ac-467e19565ae7/
```

The test mints a badge, deletes the holder's `UserProfile`, then scans. `apps/qr_manager/views.py:133` still reads `user.profile.display_name` unguarded, so an anonymous scan still returns 500. **That test *is* finding 4** — it cannot go green until the badge fallback lands, and its being red is the reproduction doing its job.

So the accurate reading of this pass: all three collisions cleared, and the only remaining non-pre-existing failure is an open finding.

---

## Verification

- `NavbarStaffHostGuardTests` — green
- `StaffEmployeeGatingTests` — green
- `VerifyScanMissingProfileTests.setUpClass` — green; `test_scan_works_while_the_profile_exists` green; the missing-profile test red for the right reason
- `apps.home` — green throughout
- `git status` showed only `apps/staff/tests.py` and `apps/qr_manager/tests.py`

---

## Finding status — eight of nine closed

| # | Finding | State |
|---|---|---|
| 1 | migrate-from-zero | ✅ Closed (`68bb77c`) |
| 2 | `current_for()` ignores status | ✅ Closed (`01630c2`, `81ee434`) |
| 3 | `renew_membership()` wrong tier | ✅ Closed (same) |
| 4 | Badge scan 500 on missing profile | 🟡 Root cause closed; **fallback outstanding** |
| 5 | Profile-less user breaks slug save | ✅ Closed (`e00e773`, `f868455`) |
| 6 | `AlumniProfileDetailView` ungated | ✅ Closed (`2d452ed`, `663bb73`) |
| 7 | Navbar substring host guard | ✅ Closed (`c307f84`) |
| 8 | `student:` namespace | ✅ Closed (`bab912d`) |
| — | Staff mis-gating cluster | ✅ Closed (`a1771ea`) |

---

## Remaining work

Two passes, both already designed in [`qa-500-userprofile-design-2026-09-01.md`](qa-500-userprofile-design-2026-09-01.md):

1. **Badge fallback** (closes finding 4) — `display_name` → `label` → the existing invalid-scan page, at `apps/qr_manager/views.py:90` and `:133`. Turns the fifth error green. The open question is Q1: whether a holder with neither a name nor a label should get the invalid-scan page (my recommendation) or a card reading "Name unavailable". Not `user.email` — the page deliberately withholds even the tier name.
2. **Backfill migration** — idempotent `get_or_create` for accounts that predate the signal. Worth taking the production profile-less count first; dev holds 1 of 5.

Separately, and outside this sweep: the four pre-existing `qr_manager` fixture errors are still there. They are a stale-fixture problem (`Employee` no longer holds name fields — they moved to `UserProfile` per `docs/rebuild-schema.md`), not a production defect, and would be a tidy standalone task.
