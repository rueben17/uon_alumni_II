# Finding D — fix design

**Date:** 2026-09-02
**Branch:** `coverage/phase-1` (a dedicated fix branch is recommended — see [Branch](#branch))
**Status:** 🛑 **Read-and-report only — no production code touched.**

Pinned by [`coverage-phase1-payments-apply-2026-09-02.md`](coverage-phase1-payments-apply-2026-09-02.md); characterised in [`coverage-phase1-payments-step1-2026-09-01.md`](coverage-phase1-payments-step1-2026-09-01.md).

---

## The finding that reshapes the fix

**Hooking `Payment.mark_as_completed()` does not close the hole finding D actually describes.**

The most likely real-world trigger is a Secretariat member opening a Payment in the admin change form and setting `payment_status` to `completed`. That path **never calls `mark_as_completed()`** — the Django admin saves through a plain `ModelForm.save()`, and `PaymentAdmin` defines **no `save_model`** (confirmed: zero matches in the class).

So Option 1 alone — putting activation inside the model method — would fix the shell and a future callback while leaving the admin form, the very case that motivated the finding, still broken.

**The fix must therefore be a hybrid.** That is the substantive outcome of this pass.

---

## Every path to `completed`, traced

| Path | Calls `mark_as_completed()`? | Activates today? | Fixed by hooking the model method alone? |
|---|---|---|---|
| `PaymentAdmin.mark_completed` bulk action | Yes, at `admin.py:721` | ✅ Yes — its own block at `:722-737` | n/a, already works |
| **Admin change form** (edit the editable `payment_status`) | **No** — plain `ModelForm.save()` | ❌ **No** | ❌ **No** |
| Shell / script `payment.mark_as_completed()` | Yes | ❌ No | ✅ Yes |
| Shell `p.payment_status = 'completed'; p.save()` | No | ❌ No | ❌ No |
| Future gateway callback | Depends what it calls | — | Only if it calls the method |

`payment_status` is editable because `PaymentAdmin.readonly_fields` (`admin.py:656`) lists only `transaction_reference`, `created_at` and `updated_at`, while the fieldset at `:664` exposes `payment_status` directly.

---

## Source, quoted

### `Payment.mark_as_completed` — `models.py:1749-1762`

```python
    def mark_as_completed(self, receipt_number=None):
        """Mark payment as completed and optionally store receipt."""
        old_status = self.payment_status
        self.payment_status = 'completed'
        self.completion_date = timezone.now()

        if receipt_number:
            if self.payment_method == 'mpesa':
                self.mpesa_receipt_number = receipt_number
            elif self.payment_method == 'bank_transfer':
                self.bank_reference = receipt_number

        self.save(update_fields=['payment_status', 'completion_date', 'mpesa_receipt_number', 'bank_reference'])
        self._log_transaction('complete', request_data={'receipt': receipt_number})
```

**`old_status` is assigned and never read** — a dead variable, and the same is true in `mark_as_failed` at `:1766`. It is exactly the idempotency hook this fix needs, already sitting in place.

`mark_as_failed` (`:1764-1771`), `mark_as_pending_verification` (`:1773-1777`) and `mark_as_refunded` (`:1779-1784`) all mutate the Payment row and call `_log_transaction`. **None references `Membership`.**

### `PaymentAdmin.mark_completed` — the activation block, `admin.py:718-738`

```python
        updated = 0
        today = timezone.now().date()
        for payment in queryset.select_related('alumni__user', 'membership_tier', 'membership'):
            payment.mark_as_completed()
            tier = payment.membership_tier
            if not tier:
                continue

            if payment.membership_id:
                services.record_installment_payment(payment.membership, payment.amount, payment_date=today)
            else:
                payment_date = payment.payment_date.date() if payment.payment_date else None
                user = payment.alumni.user
                membership = Membership.objects.filter(
                    user=user, tier=tier, status=Membership.Status.PENDING
                ).order_by('-created_at').first()
                if membership is None:
                    membership = Membership.objects.create(user=user, tier=tier)
                services.activate_membership(membership, payment_date=payment_date)
            updated += 1
```

Note the **deliberate asymmetry** in date anchoring, explained at `:708-716`: the instalment path passes `payment_date=today` (the confirmation date), while the lump-sum path passes `payment.payment_date.date()`. The docstring is explicit — *"Lump-sum activate_membership() below is untouched -- only the installment path was asked for."* Any fix must preserve both, not unify them.

### The service functions

`services.record_installment_payment(membership, amount, payment_date=None)` and `services.activate_membership(membership, payment_date=None)` — both wrap `transaction.atomic()`, both compute `first_activation = membership.status != ACTIVE` and supersede the prior ACTIVE row only on first activation.

**They are already idempotent against re-activation of the same row**, which matters below.

---

## The design question

### Option 1 — activation inside `Payment.mark_as_completed()`

**Feasible.** `self.membership`, `self.membership_tier`, `self.amount`, `self.alumni.user` and `self.payment_date` are all available, so the whole `admin.py:722-737` block can move.

**But it does not close the admin-form hole**, which is the finding's headline case. And the bulk action calls `mark_as_completed()` at `:721` *and then activates itself* — so without restructuring, it would activate twice.

Rejected on its own.

### Option 2 — `save_model` on `PaymentAdmin`, keeping the bulk action

Closes the admin form. Leaves the shell and any future gateway callback untouched, and duplicates the activation logic in a second place. Rejected on its own.

### Option 3 — centralise in `services.confirm_payment(payment)`, called from both — **recommended, extended**

Move the activation block verbatim into a new service function, then call it from every entry point:

```python
def confirm_payment(payment):
    """Activate the membership a confirmed payment was for.

    The activation half of what PaymentAdmin.mark_completed used to do
    inline. Lives here so every path that completes a payment -- the
    admin bulk action, the admin change form, a shell call, a future
    gateway callback -- reaches the same one door, rather than only the
    bulk action doing it (qa finding D).

    Assumes the payment is already marked completed; it does not touch
    payment status itself.
    """
```

with the three call sites:

1. **`Payment.mark_as_completed()`** — guarded by the already-present `old_status`:

   ```python
        if old_status != 'completed':
            from apps.home import services      # local: services imports models
            services.confirm_payment(self)
   ```

2. **`PaymentAdmin.save_model()`** — new, to catch the change form:

   ```python
        def save_model(self, request, obj, form, change):
            became_completed = (
                'payment_status' in form.changed_data
                and obj.payment_status == 'completed'
            )
            super().save_model(request, obj, form, change)
            if became_completed:
                services.confirm_payment(obj)
   ```

3. **`PaymentAdmin.mark_completed`** — simplifies to a thin loop, since `mark_as_completed()` now activates:

   ```python
        for payment in queryset.select_related(...):
            payment.mark_as_completed()
            updated += 1
   ```

### The idempotency guard — two layers

**Layer one, the transition guard.** `old_status != 'completed'` means re-running `mark_as_completed()` on an already-completed payment does not re-confirm. This is what stops the bulk action double-activating once its own block is removed.

**Layer two, the service layer's own guard.** `activate_membership` and `record_installment_payment` both compute `first_activation = membership.status != ACTIVE` and skip supersession when already active. So even if `confirm_payment` ran twice, no membership would supersede itself.

Belt and braces, and the second layer already exists and is tested.

⚠️ **One behaviour change to note:** `record_installment_payment` **accumulates `amount_paid` unconditionally**, before the `first_activation` check. So a genuine double-confirmation would double-count the money even though the status stayed correct. That is precisely why layer one matters, and why the guard belongs in `mark_as_completed` rather than being left to the service layer.

### Preserving the date anchoring

`confirm_payment` must keep both arms exactly as they are — `payment_date=today` for the linked/instalment path, `payment.payment_date.date()` for the unlinked path. Unifying them would silently revert the 2026-08-21 decision.

### Circular import

`services.py:26` does `from apps.home.models import Membership`, so **`models.py` cannot import `services` at module level**. The call in `mark_as_completed` must be a function-level import — the same pattern `apps/user/adapter.py` already uses for its own model imports.

---

## Residual, deliberately not closed

`p.payment_status = 'completed'; p.save()` — raw field assignment — still would not activate. Catching that needs either a `Payment.save()` override or a `pre_save`/`post_save` signal tracking the previous value, which means an extra DB read or an `__init__` snapshot on every Payment load.

**Not recommended.** It is a heavier mechanism for a path no application code uses, and the three hooked entry points cover every real one. Worth stating in the fix's own docstring so the boundary is explicit rather than accidental.

---

## No schema change

Confirmed. Every field the fix reads — `payment_status`, `membership_id`, `membership`, `membership_tier`, `amount`, `payment_date`, `alumni` — already exists, and `Membership.Status` already carries every value used. **No migration is needed.**

---

## Proposed edits

All proposals; nothing applied.

| File | Change |
|---|---|
| `apps/home/services.py` | **Add** `confirm_payment(payment)` — the activation block moved verbatim from `admin.py:722-737`, both date-anchoring arms preserved |
| `apps/home/models.py` | `mark_as_completed`: use the existing `old_status` to guard a call to `services.confirm_payment(self)`, function-level import |
| `apps/home/admin.py` | **Add** `PaymentAdmin.save_model` for the change form; **simplify** `mark_completed` to a thin loop |

### Test that inverts

`PaymentMembershipDivergenceTests.test_finding_d_marking_a_payment_completed_leaves_membership_pending` — currently asserts the membership stays `PENDING` and `current_active_for()` is `None`. It becomes the fix guard: the membership activates.

Finding E's test (`test_finding_e_a_refund_does_not_reverse_an_activation`) is **unaffected** and stays as-is — refunds remain a separate, open policy question.

### New tests needed

1. Admin **change form** save transitioning status to `completed` activates the membership — the case Option 1 alone would have missed.
2. A change-form save that does **not** touch `payment_status` activates nothing.
3. Shell `payment.mark_as_completed()` activates.
4. Running the bulk action **then** `mark_as_completed()` again does not double-activate, and `amount_paid` is not double-counted.
5. The bulk action still supersedes a prior ACTIVE row — the invariant, re-proven through the new path.
6. Today-anchoring still holds for the instalment path; submission-date anchoring still holds for the lump-sum path.
7. Raw `payment_status = 'completed'; save()` still does **not** activate — the documented residual.

The six existing `PaymentAdminMarkCompletedTests` should pass unchanged; they assert outcomes rather than the route taken.

---

## Branch

This is a production fix, not coverage work. **Recommend a dedicated branch — `fix/finding-d-payment-activation` off `coverage/phase-1`** — so it can be reviewed and merged independently of the coverage stream.

**Not created.** Say the word.

---

## Decisions needed

1. **Approve Option 3 extended** — `services.confirm_payment` plus the `mark_as_completed` guard plus `PaymentAdmin.save_model`?
2. **Accept the residual** — raw field assignment still not activating, rather than adding a `save()` override or signal?
3. **Branch** — create `fix/finding-d-payment-activation`?
4. **Finding E** — leave open, or decide the refund policy in the same pass? My recommendation: leave it; it is a business decision, not a defect.

🛑 Design complete — awaiting confirmation.
