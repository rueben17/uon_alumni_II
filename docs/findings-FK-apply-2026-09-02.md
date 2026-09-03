# Findings K and F — K fixed, F blocked on a view decision

**Date:** 2026-09-02
**Branch:** `fix/forms-fk` (created off `coverage/phase-1` on the recommendation — easily renamed)
**Commits:** `617325a` (finding K), `73dad3e` (the `expires_on` caveat comment)
**Status:** 🛑 **Finding F stopped** — the correct fix needs `views.py`, and the brief requires confirming the shape first.

**222 tests green.** `makemigrations --check` clean.

---

## ✅ Commit 1 — finding K fixed (`617325a`)

`installment_amount` is declared `required=False` and its help text says *"leave blank to pay the full fee"*, but `AlumniProfileForm.__init__` rebuilds **every** field's required flag from its own `optional_fields` allow-list — which knows nothing about the subscription fields `AlumniRegistrationForm` adds. The inherited loop silently overrode the declaration, so **the primary lump-sum registration path was blocked at the form**.

### The fix

`AlumniRegistrationForm` now defines `__init__` and re-asserts that one field after `super()`:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # AlumniProfileForm.__init__ rebuilds EVERY field's `required`
        # from its own optional_fields allow-list, which knows nothing
        # about the subscription fields this subclass adds ...
        self.fields["installment_amount"].required = False
```

**Exactly one field.** `membership_tier`, `payment_method`, `payment_frequency` and `privacy_consent` are all genuinely required, and the inherited loop is right about them.

Chosen over adding the name to the parent's `optional_fields` list: this keeps the correction in the class that declares the field, rather than putting a subclass-only field name in the parent and relying on action at a distance.

### Verified

```
AlumniRegistrationForm.membership_tier      required=True
AlumniRegistrationForm.payment_method       required=True
AlumniRegistrationForm.payment_frequency    required=True
AlumniRegistrationForm.privacy_consent      required=True
AlumniRegistrationForm.installment_amount   required=False
MembershipUpdateForm.installment_amount     required=False   (never affected)
```

Placement confirmed too: the new `__init__` landed at line 371, inside `AlumniRegistrationForm` (line 318) and well before `MembershipUpdateForm` (line 414) — worth checking explicitly, because the two `clean()` methods are verbatim duplicates (finding I) and a naive anchor could have matched the wrong one.

`clean()` still demands an amount when the frequency is not `Once`, so instalment plans are unaffected.

### Tests

The reproduction is **inverted**: a `Once` registration with a blank amount now validates, and `cleaned_data["installment_amount"]` is `None` so the view still falls back to `tier.fee`.

A **second test** pins that the other four fields stay required, so a future change cannot loosen them alongside. The workaround comment in the bank-transfer test (`installment_amount="500000"  # required here, though it should not be`) is gone.

---

## ✅ `expires_on` caveat comment (`73dad3e`)

Comment only, on `Membership.activate()`, recording the agreed caveat: the re-stamping of `expires_on` on a non-first activation is safe **only because `services.activate_membership` has a single caller reached through two guarded doors**, and that safety lives in the callers rather than in the method.

Put next to the code rather than only in `docs/`, since the next person to add a caller is the one who needs to know.

No behaviour change; `makemigrations --check` reports nothing.

---

## 🛑 Finding F — blocked, needs a `views.py` decision

### There is no form-level fix

```python
        owner = User.objects.filter(phone=normalized)
        if self.instance.user_id:
            owner = owner.exclude(pk=self.instance.user_id)
        if owner.exists():
            raise forms.ValidationError("This phone number is already registered to another account.")
```

`CreateView` builds the form with **no instance**, so `ModelForm` constructs a bare `AlumniProfile()` whose `user_id` is `None`. The user only arrives at `views.py:467-468`:

```python
    def form_valid(self, form):
        form.instance.user = self.request.user
```

— which runs **after** `is_valid()`. Nothing reachable from inside `clean_phone_mobile` knows who is registering, so the exclusion has nothing to exclude. A registrant whose `User.phone` is already populated is told their own number belongs to somebody else.

### Recommended shape — two lines, no change to `clean_phone_mobile`

```python
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = AlumniProfile(user=self.request.user)
        return kwargs
```

That makes `instance.user_id` available during validation, so the **existing** exclusion works unchanged. The cleanest available fix: it corrects when the user is attached rather than adding a second mechanism for identifying them.

### Why it looks safe

- `AlumniProfileForm.__init__` gates prefill on `not self.instance._state.adding`. An unsaved `AlumniProfile(user=...)` still has `_state.adding = True`, so prefill stays skipped and `get_initial` keeps doing that job — verified earlier when a test asserted exactly this.
- The existing `form.instance.user = self.request.user` in `form_valid` becomes redundant but harmless. I would **leave it** rather than widen the diff.
- `AlumniProfileUpdateView` is untouched: it passes a saved instance, so `user_id` is already present and the edit path keeps working.

### The alternative, and why I prefer the above

Passing `user` into the form's `__init__` would also work, but it changes a signature shared by **two** views for the same result — more surface, no benefit.

### Awaiting confirmation

Confirm the `get_form_kwargs` shape and I will apply it, invert F's reproduction (registration accepts the registrant's own number), and keep the edit-path contrast green.

---

## Scope

`git status` showed only `apps/home/forms.py`, `apps/home/models.py` and `apps/home/tests.py`. Untouched as instructed: `national_id` (G, retracted), `digital_id_photo` (J), `activate()`'s logic, refunds (H), the duplicate `clean()` methods (I), `services.py`, `admin.py`, migrations, settings, requirements.

## Ledger position

| # | Finding | State |
|---|---|---|
| — | `activate_membership` recomputes `expires_on` | ✅ Documented in code (`73dad3e`) |
| E | Refund does not reverse activation | 🛑 Open — policy decision |
| F | Registration rejects the registrant's own phone | 🛑 **Blocked — `views.py` shape awaiting confirmation** |
| J | No size limit on the Digital ID photo | 🛑 Open — separate pass, needs a limit |
| **K** | **`installment_amount` wrongly required** | ✅ **Fixed** (`617325a`) |

Coverage delta will follow once F lands; this pass changed only three statements of production code, so the figures are unlikely to move materially.
