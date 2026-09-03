# Coverage priority 4 — payments characterisation

**Date:** 2026-09-01
**Branch:** `coverage/phase-1`
**Baseline:** `apps/home/payments.py` 55% (9 of 20 statements uncovered)
**Status:** 🛑 **Read-and-report only — no test written, no source touched.**

---

## The headline: priority 4 is not where the money is

`apps/home/payments.py` is **not a gateway integration**. It is a 64-line placeholder seam, and its own docstring says so:

> No real gateway credentials exist yet (no M-Pesa/Daraja, Stripe, etc. in settings) -- this module is the single place a real integration plugs into later. Every payment method currently routes to ManualGateway, which just leaves the Payment record for a supervisor to confirm by hand.

Confirmed independently: a search of `main/settings.py` and `requirements.txt` for `mpesa|daraja|stripe|paystack|flutterwave|gateway` returns **no payment provider at all** — the only hits are the e-mail and SMS placeholders (`SMS_GATEWAY = 'logging'`).

So there is **no external call to mock, no decline, no timeout, no webhook, and no callback replay**. The failure paths this pass was scoped to map do not exist yet.

**Covering `payments.py` to 100% is roughly nine statements of placeholder.** It is cheap and worth doing, but it is not risk reduction, and treating it as priority 4 would be exactly the percentage-chasing the Phase 0 report warned against.

### Where the money actually moves

`PaymentAdmin.mark_completed` — `apps/home/admin.py:686-738`, **and lines 718-738 are uncovered**. That bulk action is the only code in the project that turns a confirmed payment into an active membership, via `services.record_installment_payment()` (`:727`) and `services.activate_membership()` (`:736`).

**Recommendation: re-scope priority 4** from `payments.py` to *the payment-confirmation path* — `PaymentAdmin`'s four actions plus the `Payment.mark_as_*` model methods — and fold `payments.py`'s nine statements in as a cheap extra.

---

## Two candidate findings

Noted, **not fixed**. Both concern payment and membership state diverging.

### Finding D — a payment can be marked paid without activating the membership

`PaymentAdmin` (`admin.py:648-658`):

```python
    readonly_fields = ['transaction_reference', 'created_at', 'updated_at']
    actions = ['mark_completed', 'mark_failed', 'mark_pending_verification', 'mark_refunded']
```

and its fieldset at `:664` exposes `payment_status` as an **editable field**.

The service layer is called from **only one place** — the bulk action `mark_completed` (`:727`, `:736`). There is **no `save_model` override** on `PaymentAdmin`.

`Payment.mark_as_completed()` (`models.py:1749-1759`) touches only the `Payment` row:

```python
        self.payment_status = 'completed'
        self.completion_date = timezone.now()
        ...
        self.save(update_fields=['payment_status', 'completion_date', 'mpesa_receipt_number', 'bank_reference'])
```

Verified: **none** of `mark_as_completed`, `mark_as_failed`, `mark_as_pending_verification` or `mark_as_refunded` references `Membership` at all.

**So a Secretariat member who opens a Payment in the admin change form and sets `payment_status` to `completed`** — an entirely natural thing to do, and the field is editable — **records the money as received while the membership stays PENDING.** The same applies to `payment.mark_as_completed()` from the shell, and would apply to any future gateway callback that called the model method rather than the admin action.

Only the bulk action does both things. Nothing signposts that.

### Finding E — a refund does not reverse an activation

`mark_as_refunded` (`models.py:1779-1785`) and `mark_as_failed` (`:1764-1770`) set the payment's status and log a transaction. Neither touches the membership.

A payment confirmed via the bulk action activates the membership; refunding or failing that payment afterwards leaves the membership **ACTIVE** with no payment behind it. Whether that is wrong is a policy question — an Association may well want to honour a membership through a refund dispute — but it is currently implicit rather than decided.

---

## `payments.py`, method by method

| Lines | Element | Covered | Trigger for the uncovered branch |
|---|---|---|---|
| 22-29 | `PaymentGateway.initiate` / `.verify` | ✗ 26, 29 | The abstract base's `raise NotImplementedError`; only reached if a gateway subclass fails to override, or the base is instantiated directly |
| 38-43 | `ManualGateway.initiate` | ✗ 39-43 | Logs and returns the payment unchanged. Uncovered because no test calls `initiate_payment` |
| 45-46 | `ManualGateway.verify` | ✗ 46 | Returns `payment.payment_status`. No caller in the codebase |
| 49-53 | `GATEWAYS` registry | ✓ | Module-level dict: `mpesa`, `credit_card`, `bank_transfer`, all → `ManualGateway` |
| 56-58 | `get_gateway` | ✗ 57-58 | `GATEWAYS.get(payment_method, ManualGateway)` — the `.get` default is the unknown-method fallback |
| 61-64 | `initiate_payment` | ✗ 63-64 | The single entry point views call after creating a `Payment` |

**A correction to Phase 0:** that report said *"`initiate_payment` is reached but its alternatives are not."* It is **not** reached — lines 63-64 are in the uncovered list. Nothing in the suite calls it.

`ManualGateway.verify` has **no caller anywhere** in the project. It exists to satisfy the interface.

---

## The payments ↔ services handoff

**Good news: the bulk action does not bypass the invariant.** `admin.py:718-738` routes every activation through the service layer:

```python
            if payment.membership_id:
                services.record_installment_payment(payment.membership, payment.amount, payment_date=today)
            else:
                membership = Membership.objects.filter(
                    user=user, tier=tier, status=Membership.Status.PENDING
                ).order_by('-created_at').first()
                if membership is None:
                    membership = Membership.objects.create(user=user, tier=tier)
                services.activate_membership(membership, payment_date=payment_date)
```

The one direct write — `Membership.objects.create(user=user, tier=tier)` at `:734` — creates a **PENDING** row and immediately activates it through `services.activate_membership`, so supersession and the one-ACTIVE-row invariant still hold. That is consistent with `assign_membership_tier`.

`payments.py` itself never touches `Membership`.

**The bypass is finding D**: not a direct mutation, but a path that changes payment state and *never reaches* the service layer at all.

One behaviour worth pinning while here: `admin.py:704-707` anchors `next_installment_due` to **today** (the confirmation date), not `payment.payment_date`, because a request can sit pending for weeks. That is a deliberate 2026-08-21 decision and easy to regress.

---

## Mocking strategy

**Nothing external needs faking.** There is no gateway, so no HTTP, no credentials, no timeouts, and no live-call risk. That is the whole answer to task 5, and it is a much shorter answer than expected.

| Thing | Approach |
|---|---|
| The gateway | None exists. `ManualGateway` is pure — a log line and a return. Test it directly. |
| A future real gateway | `GATEWAYS` is a module-level dict, so a test can swap an entry with `mock.patch.dict` to prove the dispatch seam works. Worth one test, since that seam is the module's entire reason for existing. |
| Admin actions | Call them **directly** — `PaymentAdmin(Payment, admin_site).mark_completed(request, queryset)` — rather than through the admin HTTP flow. Same approach as the backfill-migration tests. Needs a `RequestFactory` request with message storage, because `self.message_user` writes to it. |
| Callback / webhook | **Does not exist.** Nothing to simulate. |
| `override_settings` | No constraint here — `payments.py` captures no settings at import, unlike `adapter.py:17-33`. |

**Nothing is untestable without a live call.**

---

## Proposed test list — 17 tests

No `HTTP_HOST` is needed anywhere: this is all service- and model-level, with admin actions invoked directly.

### `payments.py` — closes the file (5)

1. `get_gateway` returns a `ManualGateway` for each of `mpesa`, `credit_card`, `bank_transfer`.
2. `get_gateway` falls back to `ManualGateway` for an unknown method — the `.get` default.
3. `ManualGateway.initiate` returns the payment unchanged and mutates nothing.
4. `ManualGateway.verify` returns the payment's current status.
5. `PaymentGateway.initiate` / `.verify` raise `NotImplementedError` — the interface contract.

Plus one on the seam itself: `initiate_payment` dispatches through `GATEWAYS`, proven by patching the registry entry.

### `PaymentAdmin` actions — the real target (6)

7. Instalment path: a payment linked to a membership calls `record_installment_payment`; the membership becomes ACTIVE and `amount_paid` accumulates.
8. Lump-sum path: no `membership_id` → the newest PENDING row for that user and tier is found and activated.
9. No matching PENDING row → one is created and activated.
10. A payment with **no** `membership_tier` is skipped (`continue`) and mutates nothing.
11. `next_installment_due` is anchored to **today**, not `payment.payment_date` — the 2026-08-21 decision.
12. Confirming a renewal supersedes the prior ACTIVE row — the invariant still holds end to end from the payment side.

### `Payment.mark_as_*` (4)

13. `mark_as_completed` sets status and `completion_date`, and routes the receipt number to `mpesa_receipt_number` or `bank_reference` by method.
14. `mark_as_failed` sets status and notes.
15. `mark_as_pending_verification` sets status.
16. `mark_as_refunded` sets status and notes.

### Candidate-finding reproductions (2)

17. **Finding D:** `payment.mark_as_completed()` leaves the membership PENDING — assert the current behaviour as a documented reproduction.
18. **Finding E:** refunding a payment after the bulk action activated the membership leaves it ACTIVE — likewise.

---

## Awaiting sign-off

Three things to confirm:

1. **Re-scope priority 4** from `payments.py` alone to the payment-confirmation path (`PaymentAdmin` actions + `Payment.mark_as_*`), with `payments.py` folded in as a cheap extra? My recommendation: yes — `payments.py` on its own is nine statements of placeholder, and `admin.py:718-738` is where a defect would cost money.
2. **Findings D and E** — write them as documented reproductions asserting current behaviour, as with the numbering skip and finding B?
3. **Finding D specifically** may deserve raising as a bug in its own right rather than only a test. An editable `payment_status` with no `save_model` hook is a foot-gun for the Secretariat, and the fix — activating through the service layer whenever a payment transitions to `completed` — is a real behaviour change needing its own gated pass.
