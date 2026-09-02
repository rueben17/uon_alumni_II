# Ledger decisions — `expires_on`, finding J, and the pass scope

**Date:** 2026-09-02
**Branch:** `coverage/phase-1`
**Status:** recommendations only — no code touched.

Answers the two open questions on the findings ledger in [`coverage-phase1-forms-apply-2026-09-02.md`](coverage-phase1-forms-apply-2026-09-02.md).

---

## First, a correction to the planned pass

**There is no "F/G fix pass" to write — G was retracted.**

Finding G (whitespace defeating the ID uniqueness check) **does not reproduce**. `forms.CharField` strips by default (`strip=True` since Django 1.9), so `" 12345678 "` is already `"12345678"` before `clean_id_passport_no` runs, and the duplicate is caught. The test in `d7de374` documents the correct behaviour and records the retraction.

The two open findings in `forms.py` are **F and K**, and **K is the more urgent of the two**:

| | Reach |
|---|---|
| **K** | Blocks **lump-sum registration outright** — anyone choosing "Once" and leaving the amount blank, exactly as the help text instructs |
| **F** | Bites only accounts that already have `User.phone` populated — a legacy import, or a future flow that captures a phone at signup |

Worth renaming the pass to **F + K** before writing it.

---

## `expires_on` recomputation — **document, do not fix**

### It is no longer reachable

After the finding-D fix, `services.activate_membership` has exactly **one** production caller:

```
services.py:141   activate_membership(membership, payment_date=payment_date)   # inside confirm_payment
```

The other matches in `admin.py` are docstring mentions only. And `confirm_payment` is reached through just two doors, both guarded:

| Door | Guard |
|---|---|
| `Payment.mark_as_completed()` | `old_status != 'completed'` |
| `PaymentAdmin.save_model()` | `'payment_status' in form.changed_data` |

The path that made the double-activation reachable was a **retried admin bulk action**, and finding D's guard closed it.

### It is also defensible on its own terms

"Recompute expiry from the confirmation date" is a reasonable reading: if someone deliberately re-activates a membership, dating the new term from today is arguably what you want. Changing it means deciding what a second activation *should* do — no-op, error, or extend — which is a business rule, not a defect.

The method's docstring only ever claimed idempotency **of supersession**, and it delivers exactly that. `started_on` is preserved (it is only set when unset); only `expires_on` moves.

### The caveat worth threading in

**The safety is currently a property of the callers, not of `activate_membership` itself.** Add a second caller — a payment-gateway callback, a bulk re-activation management command — and the window reopens silently, because nothing in the service function resists a repeat call.

If you want it belt-and-braces, the hardening is about two lines: skip re-stamping the dates when the row is already `ACTIVE`. It would **not** disturb instalments, which reach the model method through `record_installment_payment` rather than through `activate_membership`.

**Recommendation:** document now, with that caveat recorded next to it, and treat the two-line hardening as an optional follow-up rather than part of any current pass.

---

## Finding J (photo size cap) — **keep it out of the F + K pass**

Not the default I would take. F and K are the same *kind* of change; J is a different one.

| | F and K | J |
|---|---|---|
| Nature | Restore intended behaviour | **Add a constraint that never existed** |
| Policy content | None — the code already declares what it should do | Needs a number: 2 MB? 5 MB? max dimensions? |
| User-visible effect | Fixes submissions that are wrongly refused | **Rejects uploads that currently succeed** |
| Revert story | Clean, self-contained | Wants to be revertable on its own if the cap proves too tight |

Three specific reasons to separate it:

1. **It needs a decision I should not make for you.** Any limit I picked would be invented, and it directly constrains what alumni can submit for their Digital ID.
2. **It can break working behaviour.** F and K only ever *unblock* submissions; J blocks some. That is a different risk profile and deserves its own review.
3. **Bundling muddies the revert.** If the cap turns out too tight, you would want to drop just that — awkward when it sits alongside two unrelated logic corrections.

**Recommendation:** ship **F + K** as one pass — same two form classes, same character of bug — and take J separately once you have picked a limit.

If you would rather have it all in one go, name the number and I will fold it in. Either way I would keep it as **its own commit** within the pass, so it stays independently revertable.

---

## Resulting ledger position

| # | Finding | State after these decisions |
|---|---|---|
| — | Membership numbering skips on renewal | Documented — contract holds |
| — | **`activate_membership` recomputes `expires_on`** | **Documented** — unreachable post-D; caller-dependent caveat recorded |
| A | `get_connect_redirect_url` returns `None` | Retracted |
| B | Bare `home:` reverse 500ing staff login | Fixed |
| C | `RESTRICT_*` parsing fails open | Retracted; parsing hardened anyway |
| D | Payment completed outside the bulk action | Fixed |
| E | Refund does not reverse activation | 🛑 Open — policy decision, still outstanding |
| F | Registration rejects the user's own phone | 🛑 Open — **next pass, with K** |
| G | Whitespace defeats ID uniqueness | Retracted |
| H | 1-cent instalment activates any tier | Documented — Association decision |
| I | Two `clean()` methods are verbatim duplicates | Documented — both tested |
| **J** | **No size limit on the Digital ID photo** | 🛑 **Open — separate pass, needs a limit from you** |
| K | `installment_amount` wrongly required | 🛑 Open — **next pass, with F** |

**Still needing a decision from you:** finding E (the refund policy) and finding J's actual limit.
