# Coverage phase 1, Step 1 — setup, reads and proposed test list

**Date:** 2026-09-01
**Branch:** `coverage/phase-1` (off `feature/qa-500-tests`)
**Tooling commit:** `6f22d04`
**Status:** 🛑 **Step 1 only — no test written, no production code touched.** Awaiting sign-off on the test list.

Executes [`coverage-phase0-2026-09-01.md`](coverage-phase0-2026-09-01.md) priority items 1 and 2 as a single pass: the membership lifecycle end to end.

---

## Correction to the Phase 0 report

Phase 0 stated that `apps/home/factories.py` was dead code that *"nothing imports"*. **That was wrong**, and it is corrected here rather than left in the record.

```
apps/home/management/commands/generate_demo_data.py:44:from apps.home.factories import (
```

`factory_boy==3.3.3` and `Faker==40.21.0` are both in `requirements.txt` (lines 29-30). It reads as 0% coverage because no test runs that management command — not because it is unused.

### Recommendation: neither adopt nor delete — leave it

- Its own docstring is explicit: *"Not test fixtures for the pytest/unittest suite… This exists solely for demo-scale data generation."*
- It is `.build()`-only by design (`generate_demo_data` does the `bulk_create()` itself), which is the wrong strategy for tests that need real rows and FK behaviour.
- Its `UserProfileFactory` constructs a `UserProfile` directly, which would now collide with the row `apps/user/signals.py` auto-creates — `UserProfile`'s pk *is* the user's pk.

Wrong shape for this pass, and live code regardless. This pass builds its own small fixtures.

---

## Setup — committed (`6f22d04`)

| File | Change |
|---|---|
| `requirements-dev.txt` | `coverage==7.16.0` appended |
| `.coveragerc` | New — `source = apps`, `omit = */migrations/*, */tests.py, */__pycache__/*` |

`requirements.txt` is untouched: coverage.py is a development tool and gunicorn never needs it. The `.coveragerc` mirrors the flags used for the Phase 0 baseline so later figures stay comparable with the 59% recorded there.

---

## Behaviour as written — the functions under test

Quoted and read before proposing anything; no name guessed.

### `apps/home/services.py`

| Function | Line | Behaviour |
|---|---:|---|
| `_supersede_prior_active` | 29 | Finds the prior `ACTIVE` row for the user, excluding self. If found **and** the new row has no `membership_number`, copies the prior's number onto it **in memory only** — no save. Returns the prior row, or `None` on a first-ever membership. |
| `_close_out` | 47 | If given a row, sets `SUPERSEDED` and saves `update_fields=["status", "updated_at"]`. |
| `activate_membership` | 53 | `transaction.atomic()`. Computes `first_activation = membership.status != ACTIVE`; if so, closes out the prior active row; then calls `membership.activate(payment_date)`. **Skips supersession entirely when the row is already ACTIVE** — the documented idempotency guard. Returns the membership. |
| `record_installment_payment` | 79 | Same atomic block and same `first_activation` guard, then delegates to the model's `record_installment_payment`. |
| `assign_membership_tier` | 96 | Creates a `PENDING` row. Already covered. |
| `renew_membership` | 108 | Reads `current_active_for`; raises `ValueError` at **:116** when nothing is active; otherwise re-assigns at the same tier. |
| `upgrade_to_lifetime` | 120 | Raises `ValueError` on a non-life tier; otherwise assigns. |

### Model methods the service layer calls

- **`Membership.activate()`** (models.py:1571) — sets `ACTIVE`, derives `is_lifetime` from the tier, sets `started_on` only if unset, sets `expires_on` to `None` for lifetime else `tier.get_expiry_date(payment_date)`, generates a `membership_number` only if unset, saves.
- **`Membership.record_installment_payment()`** (models.py:1620) — accumulates `amount_paid`; activates only if not already `ACTIVE`, else plain save; then, if it is an instalment plan with a balance outstanding, pushes `next_installment_due` forward by the frequency's grace days.
- **`Membership.is_overdue`** (models.py:1607) — `False` unless an instalment plan **and** `ACTIVE`; `False` if the balance is clear or no due date; otherwise `today > next_installment_due + grace_days`.
- **`Membership.generate_membership_number()`** (models.py:1565) — `UoNAA/{count+1:06d}/{year}`, derived from a **`count()`** of numbers ending `/{year}`.

### The task and its command

`apps/home/tasks.py:168` is a thin wrapper — `call_command("expire_lapsed_installment_plans")`. The command selects `status=ACTIVE` excluding `payment_frequency=ONCE`, and flips only those where `is_overdue` to `EXPIRED`, saving `update_fields=["status"]`.

### Two details that shape the tests

1. **A partial unique constraint exists** — `unique_active_membership_number`, on `membership_number` **where `status='active'`**. This is precisely why supersession must precede activation: activating first would briefly leave two ACTIVE rows sharing a number and violate it. The tests must exercise that ordering, not just its outcome.
2. **`generate_membership_number` derives from a `count()`**, not a sequence — worth characterising deliberately.

---

## Proposed test list — 18 behavioural tests

Appended to `apps/home/tests.py`. All service-level, so no `HTTP_HOST` is needed; `created_at` set explicitly wherever ordering is load-bearing; local Postgres throughout.

### The one-ACTIVE-row invariant (4)

The invariant the shipped `current_active_for` fix depends on, and which currently has no test at all.

1. Activating over an existing ACTIVE row marks the prior `SUPERSEDED`.
2. **Exactly one** ACTIVE row remains for that user afterwards.
3. The `membership_number` carries forward onto the new row.
4. A first-ever activation supersedes nothing and returns cleanly.

### `activate_membership` (3)

5. Sets `ACTIVE`, `started_on` and `expires_on` from the tier.
6. A lifetime tier leaves `expires_on` null and `is_lifetime` true.
7. Re-calling on an already-ACTIVE row skips supersession — characterising the guard, including that it recomputes `expires_on`.

### `record_installment_payment` (4)

8. The first payment activates and sets `next_installment_due`.
9. A second payment accumulates `amount_paid` **without** re-activating or re-superseding.
10. `next_installment_due` advances by the frequency's grace days.
11. Paying the balance to zero stops setting a further due date.

### `renew_membership` (2)

12. Happy path — renews at the ACTIVE tier.
13. `ValueError` at :116 when nothing is active.

### `upgrade_to_lifetime` (2)

14. Happy path on a life tier.
15. `ValueError` on a non-life tier.

### `expire_lapsed_installment_plans` (3)

16. An overdue instalment plan flips to `EXPIRED`.
17. Run as a **direct callable**, never through the Q2 cluster.
18. **It leaves everything else alone** — `ONCE` plans, `PENDING` rows, already-`EXPIRED` rows and non-overdue instalment plans are all untouched. This is the test that matters most: the failure mode of a scheduled mutation job is collateral damage.

---

## Characterise, do not fix

These tests are written against code assumed correct. If any goes red against real behaviour, it is reported as a **finding** with the failing test and the quoted root cause — and no production module is edited to make it pass, exactly as the 500 sweep was run.

Two places look most likely to surface something:

- **`generate_membership_number`'s `count()`-based derivation.** A count is not a sequence: deleted or superseded rows can make it repeat a number, and the partial unique constraint only guards the ACTIVE ones.
- **`activate_membership` called twice.** The second call takes the `first_activation is False` path, so it re-runs `activate()` without supersession — which recomputes `expires_on` from the new payment date and silently extends the membership.

Neither is asserted to be a bug here. Both are simply where I would look first.

---

## Awaiting sign-off

Confirm the 18-test list — or amend it — and I will write them, then report the new coverage figures for `services.py` (currently 36%) and `tasks.py` (currently 0%).
