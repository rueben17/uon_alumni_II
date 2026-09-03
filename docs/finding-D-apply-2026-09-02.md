# Finding D — fixed

**Date:** 2026-09-02
**Branch:** `fix/finding-d-payment-activation` (off `coverage/phase-1`)
**Commits:** `ab52175` (the fix), `8f8c27e` (the guards)
**Executes:** [`finding-D-design-2026-09-02.md`](finding-D-design-2026-09-02.md) — Option 3 extended, as signed off

**191 tests green.** `makemigrations --check` reports no changes. `git status` showed only the four in-scope files.

---

## The bug

Activation was bolted onto `PaymentAdmin.mark_completed`, so **only the bulk action did it**. Completing a payment any other way — editing the editable `payment_status` in the admin change form, calling `mark_as_completed()` from the shell, or a future gateway callback — recorded the money while the membership stayed `PENDING`.

The change form was the likeliest real trigger, and the one a model-method hook alone would have missed: the Django admin saves through a plain `ModelForm.save()` and never calls `mark_as_completed()`.

## The fix

`services.confirm_payment(payment)` — the activation block moved **verbatim** out of the admin — with three call sites reaching it:

| Call site | Covers |
|---|---|
| `Payment.mark_as_completed()`, guarded by `old_status` | Shell, scripts, a future gateway callback |
| `PaymentAdmin.save_model()` (new) | The admin change form |
| `PaymentAdmin.mark_completed()`, now a thin loop | The bulk action |

`services` imports `models` at module level, so the call in `models.py` is a **function-level import**.

---

## Three things worth recording about how it landed

### The `old_status` guard is load-bearing, not decorative

`record_installment_payment` accumulates `amount_paid` **before** its own `first_activation` check. So a repeat confirmation would double-count the money even with the status staying correct — the service layer's own idempotency does not cover this.

That is exactly what makes the simplified bulk loop safe: it calls `mark_as_completed()`, which activates, and the guard stops a second pass re-applying it.

The variable was already there — assigned at `models.py:1751` and never read. The fix gave a dead variable its intended job.

**Proven:** confirm via the bulk action, then call `mark_as_completed()` again — `amount_paid` stays at 3000, exactly one ACTIVE row.

### The date asymmetry survived the move

Both arms are verbatim: an instalment anchors `next_installment_due` to **today**, the moment of Secretariat confirmation; a lump sum still uses the payment's own date.

This is the 2026-08-21 decision, and unifying the arms while relocating the block would have silently reverted it — a request can sit pending for weeks, and anchoring to submission could make an instalment read as overdue the moment it activates. **Two separate tests pin the two arms.**

### The bulk action's count semantics are preserved

The original `if not tier: continue` skipped the `updated` increment for tier-less payments. The thin loop reproduces that with `if payment.membership_tier`, so the admin message still reports only payments that had a tier to apply.

**The strongest evidence the relocation was behaviour-neutral:** the six existing `PaymentAdminMarkCompletedTests` pass **unchanged**. They assert outcomes rather than the route taken, so they could not have absorbed a behaviour change silently.

---

## Tests

The finding-D reproduction is **inverted**: it asserted the membership stayed `PENDING` after `mark_as_completed`; it now asserts activation and that `current_active_for()` returns it.

Eight new tests cover every route and both boundaries:

| Test | Asserts |
|---|---|
| Change-form save to completed | Activates — the case a model-method hook alone would have missed |
| Change-form save not touching status | Activates nothing |
| Shell `mark_as_completed()` | Activates |
| Re-completing | No double-activation, `amount_paid` not double-counted |
| Bulk action on a renewal | Still supersedes the prior ACTIVE row, exactly one active |
| Instalment arm | Anchored to today, not overdue |
| Lump-sum arm | Still uses the payment date |
| Raw `payment_status` assignment | Still does **not** activate — the accepted residual |
| No `membership_tier` | Activates nothing, returns rather than raising |

`save_model` is exercised through a small stub form, since it reads only `changed_data` — the `ModelForm` itself is Django's and not under test.

---

## The accepted residual, asserted not assumed

A raw `payment.payment_status = "completed"; payment.save()` still does **not** activate. Nothing observes that transition; catching it would need a `save()` override or a signal tracking the previous value — a heavy mechanism for a path no application code uses.

It is written into `confirm_payment`'s docstring **and** pinned by a test, so the boundary is deliberate rather than accidental.

---

## Untouched, deliberately

`mark_as_failed`, `mark_as_pending_verification` and `mark_as_refunded` — verified unchanged in the diff — along with finding E's test.

**Finding E remains open.** A refund still does not reverse an activation. That is a policy decision for the Association (honouring a membership through a refund dispute is defensible), not a defect to fix in a bug pass.

---

## Coverage

| Module | Before | After |
|---|---:|---:|
| `apps/home/services.py` | 100% (36 stmts) | **100%** (51 stmts) |
| `apps/home/admin.py` | 80% | 80% |
| `apps/home/models.py` | 90% | 90% |
| Overall | 64% | 64% |
| Suite | 182 tests | **191, all green** |

`services.py` staying at 100% while growing by 15 statements is the meaningful number: `confirm_payment` arrived fully covered.

---

## Findings ledger

| # | Finding | Origin | State |
|---|---|---|---|
| — | Membership numbering skips on renewal | lifecycle pass | Documented; contract holds |
| — | `activate_membership` recomputes `expires_on` on re-call | lifecycle pass | Documented |
| A, C | `get_connect_redirect_url` / `RESTRICT` parsing | adapter pass | Retracted — both my misreads |
| B | Bare `home:` reverse 500ing staff login | adapter pass | ✅ Fixed (`26dd281`, `6763ba1`) |
| **D** | **Payment completed outside the bulk action never activated** | payments pass | ✅ **Fixed** (`ab52175`, `8f8c27e`) |
| E | Refund does not reverse activation | payments pass | 🛑 Open — policy decision |

---

## Next

1. **Merge** `fix/finding-d-payment-activation` into `coverage/phase-1`, or keep it separate for review.
2. **Finding E** — decide the refund policy, or leave it documented.
3. **Coverage priority 5** — `apps/home/forms.py` at 34%, the registration and membership validation that decides what reaches the database.
