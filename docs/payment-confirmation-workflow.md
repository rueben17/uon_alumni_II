# Manual payment confirmation workflow (no gateway plugged in yet)

No real payment gateway (M-Pesa STK push, Stripe, etc.) is wired in yet
(see `apps/home/payments.py` — every payment method routes through
`ManualGateway`). Until one is, the Secretariat confirms every payment
by hand in the admin. This is the correct, current workflow for doing
that so a member's `Membership` actually activates — not just their
`Payment` row.

## Normal case: member submitted the request themselves

Registration (`AlumniRegisterView`) and renewal/upgrade
(`MembershipUpdateView`) both already create a `Payment` row and a
`PENDING` `Membership` row, correctly linked, with `membership_tier`
and `amount` pre-filled from what the member selected.

1. Receive the member's M-Pesa/bank/card payment outside the system.
2. In the admin, go to **Payments** and find their record — search by
   name/email, or filter by `payment_status = Pending`.
3. Open it. Confirm **Membership Category** is already set (it will be,
   since it came from their own submission) and **Amount** matches
   what they actually paid.
4. Change **Payment Status** to `Completed`. Optionally fill in the
   M-Pesa receipt number / bank reference for the audit trail.
5. Save.
6. A green **"Payment confirmed — membership activated"** message
   confirms the `Membership` row was activated in the same save
   (status → active, expiry computed, membership number assigned).
7. Verify on their profile page: the tier badge shows **Active**, not
   "Payment Pending."

## Manual entry (cash, or a payment that didn't come through a web submission)

Use **Payments → Add Payment**:

- Set **Alumni**, **Membership Category**, **Amount**, **Payment Method**.
  - **Membership Category is the field that's easy to forget** — it's
    optional on the form (`membership_tier` is `null=True`/`blank=True`
    on the model) but required for activation to actually happen. Leave
    it blank and you'll get a red error telling you exactly that,
    instead of the payment silently doing nothing.
- Leave **Membership** blank for a member's first-ever payment on a
  tier — the system auto-finds or creates the pending row. Only set it
  explicitly when recording a second/later installment against an
  existing plan.
- Set **Payment Status** to `Completed` directly and save — activation
  fires immediately, same as the normal case.

## Things to watch for

- **Activation only fires on a genuine pending → completed transition.**
  Re-saving an already-`Completed` payment (e.g. to fix an unrelated
  typo) will NOT re-activate or re-add anything — this is deliberate,
  so an incidental re-save can't double-count an installment payment.
  If a row somehow ended up `Completed` without ever activating, switch
  its status to something else, save, then switch it back to
  `Completed` and save again to force a real transition.
- **Double-check Amount against the tier's actual fee before saving.**
  A typo here doesn't get caught automatically — it will still say
  "Paid in Full" if the (wrong) amount happens to meet or exceed the
  tier's fee. This exact mistake happened once already (KES 4,000
  entered against a KES 2,000 tier).
- The bulk **"Mark selected payments as completed"** action from the
  Payments list view works identically to the change-form Save button,
  for confirming several payments at once.

## Why this needed fixing (2026-08-27)

Before this, only the bulk action activated the linked `Membership` —
the change form's Save button just wrote the `payment_status` field.
A payment confirmed by opening it and switching the status dropdown
(the workflow above, and the one actually used in practice) showed as
`Completed` while the member's membership silently stayed `pending`
forever, with no error and nothing to indicate why. See
`apps/home/admin.py`'s `PaymentAdmin.save_model()` /
`_activate_membership_for()` for the fix.
