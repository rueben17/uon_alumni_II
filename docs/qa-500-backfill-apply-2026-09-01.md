# `UserProfile` backfill migration — apply pass

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Completes:** [`qa_500_report.md`](../qa_500_report.md) findings 4 and 5
**Executes:** [`qa-500-userprofile-design-2026-09-01.md`](qa-500-userprofile-design-2026-09-01.md) §5 — the third and final pass

**Commits:** `81386a7` (migration), `59a96f0` (tests)

This is the last pass of the QA 500 sweep. **Every finding is now closed.**

---

## What changed

| File | Change |
|---|---|
| `apps/user/migrations/0002_backfill_user_profiles.py` | **New.** Data migration creating the missing profiles |
| `apps/user/tests.py` | Six tests exercising `backfill()` and `unbackfill()` |

`apps/user/signals.py` closed the **intake**; this closes the **backlog** — accounts created before the signal landed, by `createsuperuser`, the shell or the Django admin's add form.

```python
def backfill(apps, schema_editor):
    User = apps.get_model("user", "User")
    UserProfile = apps.get_model("user", "UserProfile")

    missing = User.objects.filter(profile__isnull=True).values_list("pk", flat=True)
    for user_pk in missing.iterator():
        UserProfile.objects.get_or_create(user_id=user_pk)
```

### Four design points

**Historical models, so the signal does not fire.** `apps.get_model()` returns the historical `User`, while the `post_save` receiver is bound to the real class. No double-creation, and no dependency on app-loading order during migration.

**Idempotent.** `get_or_create` keyed on the user, so a partial, repeated or re-applied run converges rather than duplicating.

**Reverse is a deliberate no-op.** A profile created by this migration may have been edited since, and nothing distinguishes those from the rest. Deleting on reverse would destroy real data to undo a fix.

**`elidable=True`.** A fresh database never needs this migration — the signal creates a profile from the first account onwards — so a squash may drop it safely.

**No field values are supplied.** `given_name`/`family_name` default to `""` and the DPA-2019 consent flags to `False`. Inventing a name during a data migration would be worse than leaving it blank, and `_holder_name()` in `apps/qr_manager/views.py` already refuses to render a verification card for a holder it cannot name.

---

## Verified against the local database

Run against local Postgres, as agreed. **Production was never touched.**

```
BEFORE   users 5 | without profile 1 | staff/super among them 0/0
RUN      Applying user.0002_backfill_user_profiles... OK
AFTER    users 5 | without profile 0 | profiles 5 | blank-named 1

reverse to 0001   -> profiles 5, without profile 0    (unbackfill deletes nothing)
re-apply          -> profiles 5, without profile 0    (inert, nothing missing)
```

The two properties that matter at deploy time — **reverse is non-destructive** and **re-applying is inert** — are proven against a real database, not merely asserted in a unit test.

### On the production count

It was never an input to the migration, only a pre-flight reassurance. The backfill is correct for zero rows or ten thousand, and reports nothing that would change its behaviour. If you still want the number, the read-only query stands; otherwise running the migration and reading the resulting row count answers the same question.

### On the Neon → VPS move

Because the migration is idempotent, **it imposes no ordering on the move**. It can run on Neon before, on the VPS after, or both — a second run is a no-op. It will simply be part of the normal `migrate` on whichever database is live.

---

## Tests — six cases, all green

| Test | Asserts |
|---|---|
| Backfills a profile-less account | The row lands |
| Backfilled profile invents no data | Blank names, both consent flags `False`, `consent_given_at` unset |
| Running twice is a no-op | Exactly one profile |
| Inert when nothing is missing | Existing values untouched |
| Existing profiles left alone | Mixed database: legacy backfilled, intact profile unchanged |
| Reverse deletes nothing | `unbackfill` leaves the row in place |

They exercise the migration's **own** `backfill()`/`unbackfill()` against the real model registry, rather than asserting on migration bookkeeping — what matters is that the rows land exactly once and nothing existing is disturbed.

**One wrinkle worth remembering:** since the signal landed there is no longer any way to create a profile-less `User` directly, so the legacy state has to be built by deleting the auto-created profile. `_make_profileless_user()` does that explicitly rather than by accident.

---

## Suite state

**94 tests, 4 errors** — only the pre-existing `qr_manager` `Employee()` kwargs fixture errors, untouched throughout the sweep.

---

## Finding status — all nine closed

| # | Finding | Tier | State |
|---|---|---|---|
| 1 | migrate-from-zero | B | ✅ `68bb77c` |
| 2 | `current_for()` ignores status | B | ✅ `01630c2`, `81ee434` |
| 3 | `renew_membership()` wrong tier | B | ✅ same |
| 4 | Badge scan 500 on missing profile | B | ✅ `e00e773`, `df29f70`, `81386a7` |
| 5 | Profile-less user breaks slug save | B | ✅ `e00e773`, `f868455`, `81386a7` |
| 6 | `AlumniProfileDetailView` ungated | B | ✅ `2d452ed`, `663bb73` |
| 7 | Navbar substring host guard | A | ✅ `c307f84` |
| 8 | `student:` namespace | A→B | ✅ `bab912d` |
| — | Staff mis-gating cluster | B | ✅ `a1771ea` |

Findings 4 and 5 took three passes between them: the signal (intake), the badge fallback (presentation), and this backfill (backlog).

---

## Loose ends — neither part of this sweep

1. **`templates/qr_manager/staff_verify.html` is untracked.** It predates this session but is a live dependency of `verify_scan`. Worth committing.
2. **Four pre-existing `qr_manager` fixture errors.** `QRCodeAdminScopingTests`, `QRCodeAdminPermissionMethodTests`, `QRSupervisorSiteTests` and `ScanLogAdminScopingTests` pass `given_name`/`family_name` to `Employee()`, which moved to `UserProfile` per `docs/rebuild-schema.md`. Stale fixtures, not a production defect — a tidy standalone task.
3. **The branch is unmerged.** `feature/qa-500-tests` carries the whole sweep as independently revertable commits; merging is your call.
