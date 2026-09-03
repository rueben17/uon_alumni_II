# Coverage priority 4 — payment-confirmation path covered

**Date:** 2026-09-02
**Branch:** `coverage/phase-1`
**Commit:** `fcbfd01`
**Executes:** [`coverage-phase1-payments-step1-2026-09-01.md`](coverage-phase1-payments-step1-2026-09-01.md), re-scoped as that document recommended

**No production code changed.** `git status` showed only `apps/home/tests.py`.

---

## Result

| Module | Before | After |
|---|---:|---:|
| `apps/home/payments.py` | 55% | **100%** |
| `apps/home/admin.py` | 76% | 80% |
| `apps/home/models.py` | 86% | 90% |
| Overall | 63% | 64% |
| Suite | 164 tests | **182 tests, all green** |

The `admin.py` movement is the one that matters: `PaymentAdmin.mark_completed` (`:718-738`) went from entirely uncovered to fully covered. That is the only code in the project that turns a confirmed payment into an active membership.

---

## Findings D and E — captured, not fixed

**Both reproductions PASS.** That needs stating plainly, because a green test usually means the opposite of what it means here: they assert what the code does **today**, so green means *the defect is pinned*, not *the defect is gone*. Both will need inverting when D is fixed.

### Finding D — a live money bug

`Payment.mark_as_completed()` (`models.py:1749-1759`) touches only the Payment row. **None** of the four `mark_as_*` methods references `Membership` at all.

The service layer is called from exactly one place — the bulk action at `admin.py:727` and `:736`. `PaymentAdmin` has **no `save_model` override**, and `payment_status` is an **editable field** in its fieldset (`:664`); `readonly_fields` (`:656`) lists only `transaction_reference`, `created_at` and `updated_at`.

So a Secretariat member who opens a Payment in the admin change form and sets its status to `completed` — the obvious action, on an editable field — **records the money as received while the membership stays PENDING**. The same applies to `payment.mark_as_completed()` from the shell, or from any future gateway callback that calls the model method rather than the admin action.

The test asserts exactly that, including `current_active_for()` returning `None` afterwards.

### Finding E — policy-dependent

`mark_as_refunded` / `mark_as_failed` (`models.py:1764-1785`) do not touch the membership, so a payment refunded after the bulk action activated it leaves the member **ACTIVE** with no payment behind them.

Whether that is wrong is an Association decision — honouring a membership through a refund dispute is defensible — but it is currently implicit rather than chosen.

---

## What the pass proved

### The money path, all four branches

`mark_completed` is now covered across every route through it:

| Branch | Asserted |
|---|---|
| Linked payment (`payment.membership_id` set) | `record_installment_payment`; membership ACTIVE, `amount_paid` accumulated |
| Unlinked payment | The **newest** PENDING row for that user and tier is activated, the older left alone |
| Unlinked, no PENDING row | One is created and activated **through the service layer** |
| No `membership_tier` | Payment still marked completed, then `continue` — no membership touched |

### The 2026-08-21 due-date decision

`admin.py:704-707` anchors `next_installment_due` to **today**, the confirmation date, not to `payment.payment_date` — because a request can sit pending for weeks and anchoring to submission could make an instalment read as overdue the moment it activates.

Pinned with a payment submitted 45 days earlier: the due date lands 30 days from today, explicitly *not* 30 days from submission, and `is_overdue` is false.

### The invariant, end to end from the payment side

Confirming a renewal through the bulk action supersedes the prior ACTIVE row and leaves **exactly one** active membership. That closes the loop between this pass and the lifecycle pass: `services.py` was proven in isolation, and this proves the payment path actually reaches it.

The one direct write in the admin (`Membership.objects.create` at `:734`) creates a PENDING row and immediately activates it through `services.activate_membership`, so it does not bypass the invariant.

### `payments.py`, closed at 100%

Six tests: dispatch for all three known methods, the unknown-method fallback through `GATEWAYS.get`'s default, `ManualGateway.initiate`/`verify`, the base interface's `NotImplementedError`, and the dispatch seam itself proven with `mock.patch.dict(GATEWAYS, ...)`.

That last one is the only test in the group with real future value: it pins the seam a real gateway would plug into.

---

## Corrections made while writing

Both receipt fields are `null=True` (`models.py:1701-1702`), so after `mark_as_completed` the field **not** used by that payment method is `None`, not `""`. My first assertion expected an empty string.

---

## Remaining in this area

The three thin action wrappers at `admin.py:742-756` — `mark_failed`, `mark_pending_verification`, `mark_refunded` — are still uncovered. Each is a three-line loop over the model method it calls, and all four model methods **are** covered. Low value, cheap to add if wanted.

---

## Where the coverage build stands

| Priority | Area | Status |
|---:|---|---|
| 1 | `services.py` lifecycle | ✅ 100% |
| 2 | `expire_lapsed_installment_plans` | ✅ Covered |
| 3 | `adapter.py` OAuth | ✅ 86% |
| 4 | Payment-confirmation path | ✅ **payments.py 100%, `mark_completed` covered** |
| 5 | `home/forms.py` registration and membership validation | 34% — **next** |
| 6 | `qr_manager` `generate_qr` and watermarking | 58% |
| 7 | `home/views.py` / `staff/views.py` POST handling | ~50% |
| 8 | `Membership` model behaviour | 90% |
| 9 | `tasks.py` e-mail and SMS | 18% |
| 10 | `import_legacy_memberships` | 0% |

## Findings ledger

| # | Finding | Origin | State |
|---|---|---|---|
| — | Membership numbering skips on renewal | lifecycle pass | Documented; contract holds |
| — | `activate_membership` recomputes `expires_on` on re-call | lifecycle pass | Documented |
| B | Bare `home:` reverse 500ing staff login | adapter pass | ✅ **Fixed** (`26dd281`, `6763ba1`) |
| A, C | `get_connect_redirect_url` / `RESTRICT` parsing | adapter pass | Retracted — both my misreads |
| **D** | **Payment completed outside the bulk action never activates** | **this pass** | 🛑 **Open — live money bug, pinned** |
| E | Refund does not reverse activation | this pass | 🛑 Open — policy decision needed |

## Next

Two candidates:

1. **Fix finding D** — now well-pinned, and a small authorised pass. The likely shape is activating through the service layer whenever a payment transitions to `completed`, wherever that transition happens, rather than only in the bulk action. It is a real behaviour change and wants its own gated pass.
2. **Coverage priority 5** — `home/forms.py` at 34%, the registration and membership validation deciding what reaches the database.

My recommendation is D first: it is a money bug with a known reproduction, and every day it stays open is a day a Secretariat member can silently take payment without granting membership.
