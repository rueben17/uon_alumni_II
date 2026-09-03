# Finding H — instalment activation is amount-agnostic (settled)

**Date:** 2026-09-03
**Status:** Settled decision. No code change follows from this note.

## Decision

**A membership activates on its first instalment payment, regardless of amount** (Association decision, reflected in `apps/home/forms.py`). A KES 1,000,000 Corporate membership therefore activates on any first instalment — a token 1-cent payment included — with no size floor enforced in code.

## Why this is not treated as a defect

The safeguard here is **Secretariat confirmation of the payment**, not the amount. Every activation goes through `services.confirm_payment`, which only runs once a payment is confirmed as `completed` — a Secretariat-side judgement call, not an automatic threshold. Adding an amount floor in code would duplicate a check that already exists as a human review step, and would need its own policy answer (what floor? per tier, or a flat minimum?) that has not been asked for.

Instalment plans exist specifically so a member can start their term before paying in full — an amount floor on the *first* instalment would undercut that by design.

## What this means going forward

- `record_installment_payment` and `activate_membership` will keep activating on any confirmed first instalment, at any amount.
- If abuse becomes an actual problem (rather than a theoretical one), the fix is a minimum-first-instalment policy per tier — a new decision, not a reopening of this one.

## Ledger

Finding H is now **closed as intended behaviour**, not left open pending a decision.
