# Migrate-from-zero fix — apply & verification

**Date:** 2026-08-31
**Branch:** `feature/qa-500-tests`
**File changed:** `apps/home/migrations/0016_seed_tier_benefits.py` — one file, no new migration.

Closes [`qa_500_report.md`](../qa_500_report.md) Finding 1.
Phase 0 proposal: [`migration-seed-fix-phase0-2026-08-31.md`](migration-seed-fix-phase0-2026-08-31.md).

---

## What changed

### 1. `seed()` — eight tiers seeded at the top of the function

A `get_or_create` block for the eight `TIER_ORDER` names that no migration had ever created, inserted at **lines 123-140**, before the two `.update(order=...)` calls at **lines 144-145**. Keyed on `name`, since `code` — the stable key used from `0031` onwards — does not exist at this point in the chain, and this migration already keys `Associate`/`Registered` the same way.

| name | tier_type | fee | duration_months | order | ladder_rank |
|---|---|---|---|---|---|
| Corporate Membership | `corporate` | 1000000 | 12 | 1 | 5 |
| Platinum Life Membership | `life` | 500000 | 0 | 2 | — |
| Diamond Life Membership | `life` | 250000 | 0 | 3 | — |
| Gold Life Member | `life` | 100000 | 0 | 4 | 4 |
| Silver Life Member | `life` | 50000 | 0 | 5 | 3 |
| Bronze Life Member | `life` | 25000 | 0 | 6 | 2 |
| Full Annual Member | `annual` | 2000 | 12 | **9** | 1 |
| Student Annual Membership | `student` | 500 | 12 | **10** | — |

`is_active=True` throughout. `order=7` deliberately left empty — that is dev's `Honorary Member`, outside `TIER_ORDER` and not this migration's concern.

Everything else in `seed()` is untouched: the two `.update()` calls, the `Associate`/`Registered` creation, the validation block, and the benefit loop.

### 2. `unseed()` — comment only, no behaviour change

Still deletes only `Associate` and `Registered`. A comment now records why it is deliberately asymmetric: the eight predate this migration on every existing environment, so a reverse that deleted them would destroy rows the migration never owned.

---

## Deviation from the brief — accepted on your suggestion

The brief's table specified Full Annual at `order=8` and Student at `order=9` (pre-shift), relying on the seed block running *before* the two `.update(order=...)` calls to lift them to 9 and 10.

**Implemented instead at 9 and 10 directly.** The `.update()` calls then become no-ops on a fresh database, while still performing the real shift on any database that reaches this migration with those rows already present at 8/9. The block is *also* placed before those calls, so the end state is correct under either reading.

Net effect: correctness no longer hangs on the block's position. The cost you flagged — those two lines reading as vestigial — is addressed by a comment in the file explaining what they still do and when.

---

## Verification

| Criterion | Result |
|---|---|
| `migrate` from empty through `0041` | **Clean.** `0016`, `0017`, `0021` all `[X]`. No `RuntimeError`, no `DoesNotExist`. |
| Eight tiers created with exact values | **Match.** Full Annual = 9, Student = 10, `order=7` gap intact, 10 tier rows, 250 `TierBenefit` rows. |
| Seed block precedes the `.update()` calls | **Yes** — seed at 123-140, updates at 144-145. |
| Full suite on stock settings | **Yes.** 56 run, 3 failures + 9 errors — an *identical* set of 12 to the shimmed run. |
| Phase-1 `nomig_settings` shim removed | **Deleted.** No longer needed; its removal is the proof the defect is gone. |
| Re-run `migrate` on an already-migrated DB | `No migrations to apply.` — 10 tiers, **0** duplicate names. |
| Dev database untouched | `uon_alumni_II` still holds 13 tiers, unchanged. |
| No new migration, no other migration changed | Confirmed — `git status` shows only `0016` modified. |

Verified against a throwaway local Postgres database, `uon_alumni_fresh_migrate_check`, created empty for this purpose. The dev database was never written to.

### Resulting tier table on a fresh database

```
  1 | Corporate Membership         | corporate   |   1000000.00 |  12mo | ladder=5
  2 | Platinum Life Membership     | life        |    500000.00 |   0mo | ladder=None
  3 | Diamond Life Membership      | life        |    250000.00 |   0mo | ladder=None
  4 | Gold Life Member             | life        |    100000.00 |   0mo | ladder=4
  5 | Silver Life Member           | life        |     50000.00 |   0mo | ladder=3
  6 | Bronze Life Member           | life        |     25000.00 |   0mo | ladder=2
  8 | Associate                    | annual      |      3000.00 |  12mo | ladder=None
  9 | Full Annual Member           | annual      |      2000.00 |  12mo | ladder=1
 10 | Student Annual Membership    | student     |       500.00 |  12mo | ladder=None
 11 | Registered                   | registered  |         0.00 |  12mo | ladder=None
```

Ten rows against dev's thirteen: `Honorary Member`, `Affiliate` and `Senior Citizen` remain unseeded, as scoped. They sit outside `TIER_ORDER`, no migration needs them, and pulling them in would reopen the deferred taxonomy question.

### Remaining test failures — unchanged, all pre-existing

The 12 failures are exactly the Phase 1 findings (8) plus the pre-existing `apps/qr_manager/tests.py` `setUpClass` breakage (4, `Employee() got unexpected keyword arguments: 'given_name', 'family_name'`). **Nothing new appeared** now that data migrations run inside the test database.

---

## Why this is safe on dev and production

`0016` is already recorded in `django_migrations` on both. Django keys migrations by app plus name and never checksums the body, so the edited `RunPython` **never re-runs** there: no duplicate rows, no `InconsistentMigrationHistory`, no manual `--fake`, no deployment step. On those environments this commit is inert.

The seeding is idempotent regardless — `get_or_create` on `name` is a no-op wherever a row already exists, so even a partially-seeded or replayed environment converges rather than duplicating.

---

## Outstanding

1. **Production fee values not verified.** The figures above are transcribed from dev. They are inert on production, but every future fresh database bakes them in. Worth checking prod's tier table; if any fee has drifted, it is a one-line change inside the new block.
2. **`uon_alumni_fresh_migrate_check` still exists** on local Postgres — the disposable verification database. Awaiting the go-ahead to drop it.
3. **Nothing is committed.** `0016`, the Phase 1 tests, and all four `docs/` write-ups plus `qa_500_report.md` are uncommitted on `feature/qa-500-tests`.
