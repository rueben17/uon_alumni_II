# Coverage phase 1 — membership lifecycle covered

**Date:** 2026-09-01
**Branch:** `coverage/phase-1`
**Commit:** `2dda0b5`
**Executes:** [`coverage-phase1-step1-2026-09-01.md`](coverage-phase1-step1-2026-09-01.md) — the approved 18-test list plus the added numbering characterisation

**No production code changed.** `git status` showed only `apps/home/tests.py`.

---

## Result

| Module | Before | After |
|---|---:|---:|
| `apps/home/services.py` | 36% | **100%** |
| `apps/home/tasks.py` | 0% | 18% |
| `apps/home/models.py` | 83% | 86% |
| **Overall** | 59% | **61%** |

**Suite: 136 tests, 0 failures** (was 113). 23 test methods covering the 19 approved cases.

`tasks.py` at 18% is the intended outcome, not a shortfall: this pass targeted `expire_lapsed_installment_plans` only. The e-mail and SMS tasks (lines 22-58, 72-117, 130-137, 163-165) remain uncovered and sit at priority 9 in the Phase 0 ranking.

The overall figure moving only 59% → 61% is worth reading correctly. `services.py` is 36 statements; taking it to 100% barely moves a 5,438-statement total. **That is the argument against percentage targets restated as evidence:** the single highest-risk module in the codebase is now fully covered, and the headline number scarcely noticed.

---

## What is now covered

### The one-ACTIVE-row invariant — the point of the pass

`current_active_for()`, shipped in the QA-500 sweep, is correct *only because* the service layer supersedes any prior ACTIVE row before activating a new one. Nothing verified that. Now four tests do:

- activating over an existing ACTIVE row marks the prior `SUPERSEDED`
- **exactly one** ACTIVE row remains, and `current_active_for()` returns it
- the `membership_number` carries forward onto the successor
- a first-ever activation supersedes nothing

A fifth pins the *ordering*: both rows share a number after the carry-forward, and `Membership.Meta`'s partial unique constraint `unique_active_membership_number` guards `membership_number` **where `status='active'`** — so activating before superseding would violate it. Reaching that assertion at all proves the sequence holds.

### `activate_membership`, `record_installment_payment`, `renew_membership`, `upgrade_to_lifetime`

Happy paths, both `ValueError` branches, lifetime-versus-annual expiry, first-payment activation, accumulation without re-activation, grace-day advancement, and the balance-cleared case where no further due date is set.

### `expire_lapsed_installment_plans`

Exercised as a **direct callable**, never through the Q2 cluster. The assertion that matters most is the negative one: it leaves `ONCE` plans, `PENDING` rows, already-`EXPIRED` rows, non-overdue plans and fully-paid plans untouched. The failure mode of a scheduled mutation job is collateral damage, not the row it was aimed at.

---

## Two behaviours characterised, not corrected

Per the characterise-don't-fix rule. Neither was patched; both are recorded for a separate decision.

### 1. Membership numbering skips on renewal

**This is where a test went red — and the code was right about itself. My expectation was wrong.**

`models.py:1565-1569`:

```python
    def generate_membership_number(self):
        """UoNAA/001234/2025 -- unique per calendar year of activation."""
        year = timezone.now().year
        last = Membership.objects.filter(membership_number__endswith=f"/{year}").count()
        return f"UoNAA/{last + 1:06d}/{year}"
```

It counts **rows** whose number ends `/{year}`, not distinct numbers. A superseded row keeps its number and its successor carries the same one forward, so after a single renewal **two rows share one number** — the count reads 2, and the next member is issued `000003`. `000002` is never used.

**Recorded, not raised as a defect.** The method's only stated promise is *"unique per calendar year of activation"*, and uniqueness holds. The practical effect is that numbers are not dense and inflate faster than the membership does: a member renewing annually consumes a number from the sequence every year without receiving a new one. Whether that matters is an Association question, not a code one.

The test was corrected to assert `000003` — the real behaviour — with the reasoning in its docstring, so it reads as deliberate characterisation rather than a magic number.

**A related passing test** records that *deleting* a numbered row **does** free its number for reuse: the count drops and the next activation reissues it. Combined with the above, deleting a superseded row could reissue a number a live member still holds — but both rows would then be ACTIVE with the same number, so the partial unique constraint rejects it with an `IntegrityError` at activation. It fails loudly rather than corrupting silently.

### 2. `activate_membership` on an already-ACTIVE row recomputes `expires_on`

The `first_activation` guard at `services.py:72` correctly prevents a row superseding itself. But `Membership.activate()` still re-runs, and it recomputes `expires_on` from the new payment date while leaving `started_on` alone (it is only set when unset).

So a second call with a later date **silently extends the membership**. The docstring claims idempotency only *of supersession* — *"so a second call ... can't supersede a membership against itself"* — so this is within its stated contract, and a genuine retry would normally pass the same date. Recorded because a retried admin action is the docstring's own named use case, and a retry with today's date rather than the original would quietly extend the term.

---

## Method notes for the next pass

- **`MembershipTier.is_lifetime()` is `tier_type == 'life' **or** duration_months == 0`** (models.py:1005-1007). A test tier meant to be annual must carry a non-zero `duration_months`, or it silently behaves as lifetime.
- **Grace days come from `INSTALLMENT_FREQUENCY_DAYS`** — monthly 30, quarterly 90, annually 365 — and `is_overdue` requires `today > next_installment_due + grace_days`, i.e. a full extra cycle beyond the due date.
- **Large heredocs are unreliable in this shell.** Two attempts to append a long test block via `cat <<'EOF'` failed with a parse error and wrote nothing. The reliable route is to write the block to the scratchpad with the file tool, then `cat scratch >> target`.

---

## Where the coverage build stands

| Priority | Area | Status |
|---:|---|---|
| 1 | `services.py` activation / supersession / instalments | ✅ **100%** |
| 2 | `expire_lapsed_installment_plans` + command | ✅ Covered |
| 3 | `adapter.py` login, domain restriction, subdomain redirects | 24% — **next** |
| 4 | `payments.py` branches and failure paths | 55% |
| 5 | `home/forms.py` registration and membership validation | 34% |
| 6 | `qr_manager` `generate_qr` and watermarking | 58% |
| 7 | `home/views.py` / `staff/views.py` POST handling | ~50% |
| 8 | `Membership` model behaviour | 86% |
| 9 | `tasks.py` e-mail and SMS | 18% |
| 10 | `import_legacy_memberships` | 0% |

**Recommended next: priority 3, `apps/user/adapter.py` at 24%** — the only authentication path in the system, 160 of 210 statements uncovered, including the domain restriction and the whole post-login subdomain redirect resolution. The QA-500 sweep tested the gates thoroughly and never tested the door.

## Decisions outstanding

1. **The two characterised behaviours** — leave as documented behaviour, or open them as findings for a fix pass? My reading: the numbering skip is an Association decision about what a membership number means; the `expires_on` recomputation is the more plausible real bug, but neither is urgent.
2. **Proceed to priority 3** (`adapter.py`), or reorder?
