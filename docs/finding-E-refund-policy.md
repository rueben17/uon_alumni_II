# Finding E — refund does not reverse activation (settled)

**Date:** 2026-09-03
**Status:** Settled decision. No code change follows from this note.

## Decision

**Refunds do not automatically revoke membership.**

Membership is revoked through the disciplinary/expulsion process. A refund is the *financial* step that may follow an expulsion, not its trigger. To end a membership, the Secretariat cancels it deliberately via the admin; the refund is recorded separately.

## Why the code already matches this

`Payment.mark_as_refunded()` and `Payment.mark_as_failed()` (`apps/home/models.py:1764`, `:1779`) both update only `payment_status` and `notes`. Neither touches `Membership` in any way — no status change, no `expires_on` adjustment. This is **deliberate, not an oversight**: activation is a one-way door opened by `services.confirm_payment` (finding D's fix), and nothing in the refund/failure path is wired to close it.

That asymmetry is correct under this decision. A refund reversing activation automatically would let a member trigger their own expulsion by requesting a refund — the wrong body making the call.

## What this means going forward

- A refunded payment leaves the associated membership **active** until the Secretariat separately cancels it.
- There is no code path from `mark_as_refunded`/`mark_as_failed` to membership state, and none should be added without a new decision.
- If the Association later wants automatic reversal for a specific case (e.g. a chargeback within 24 hours of payment), that is a new policy question, not a bug fix to this one.

## Ledger

Finding E is now **closed as intended behaviour**, not left open pending a decision.
