# Finding F — fixed

**Date:** 2026-09-02
**Branch:** `fix/forms-fk`
**Commit:** `ec44894`
**Completes:** [`findings-FK-apply-2026-09-02.md`](findings-FK-apply-2026-09-02.md), which fixed K and stopped on F pending the view shape

**223 tests green.** `makemigrations --check` clean. `git status` showed only `apps/home/views.py` and `apps/home/tests.py`.

---

## The bug

`clean_phone_mobile` self-excludes on `self.instance.user_id`:

```python
        owner = User.objects.filter(phone=normalized)
        if self.instance.user_id:
            owner = owner.exclude(pk=self.instance.user_id)
        if owner.exists():
            raise forms.ValidationError("This phone number is already registered to another account.")
```

`CreateView` passed **no instance at all**, so `ModelForm` built a bare `AlumniProfile()` with `user_id` `None`. The exclusion had nothing to exclude, and the user was only attached afterwards in `form_valid` (`views.py:487`), long after `is_valid()` had run.

Result: a registrant whose `User.phone` was already populated was told their **own** number belonged to another account.

## The fix

`AlumniRegisterView.get_form_kwargs`, new:

```python
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Attach the registrant to the (unsaved) instance BEFORE validation.
        # ...
        kwargs["instance"] = AlumniProfile(user=self.request.user)
        return kwargs
```

**`clean_phone_mobile` is unchanged.** The fix corrects *when* the user is attached rather than adding a second way to identify them — the existing exclusion simply now has something to exclude.

---

## Constraints verified, not assumed

Each of these was checked against the tree rather than taken on trust:

| Constraint | How it was confirmed |
|---|---|
| `clean_phone_mobile` unchanged | `git diff apps/home/forms.py` empty for this commit |
| `form_valid`'s assignment left in place | Still present at `views.py:487` |
| `AlumniProfileUpdateView` untouched | Not in the diff |
| No schema change | `makemigrations --check` reports nothing |
| Scope | `git status` showed only the two permitted files |

`form_valid`'s `form.instance.user = self.request.user` is now redundant. It was **deliberately left**: it is the assignment any future non-`CreateView` path would rely on, and removing it would widen the diff for no gain. A comment records that.

`_state.adding` stays `True` on the unsaved instance, so `AlumniProfileForm.__init__`'s prefill branch is still correctly skipped and `get_initial` keeps seeding the form — asserted directly, not reasoned about.

---

## Three tests, covering both directions

**The cause.** A view-level test asserts `get_form_kwargs` returns an instance carrying the registrant and still `_state.adding`. The fix lives in the view, so it is tested there.

**The consequence.** The reproduction is inverted: a registrant whose own number is already on `User.phone` is now accepted.

**The guard against over-correction.** The *"a number owned by a different user is still rejected"* assertion was **moved into the registration shape the view now produces**.

That third one mattered more than it looks. The previous version used no instance at all, so it would have kept passing whether or not the fix broke real duplicate detection. Moving it means the suite now proves the fix did not loosen the check, rather than merely failing to notice.

---

## Coverage

| | Before | After |
|---|---:|---:|
| `apps/home/forms.py` | 99% | 99% |
| Overall | 67% | 67% |
| Suite | 222 tests | **223, all green** |

Flat, and correctly so: this pass changed three statements of production code. The value was the correctness, not the number — the same point the `services.py` 36% → 100% pass made from the other direction.

---

## Ledger position

| # | Finding | State |
|---|---|---|
| — | Numbering skips on renewal | Documented — contract holds |
| — | `activate_membership` recomputes `expires_on` | Documented in code (`73dad3e`) |
| A | `get_connect_redirect_url` returns `None` | Retracted |
| B | Bare `home:` reverse 500ing staff login | ✅ Fixed |
| C | `RESTRICT_*` parsing fails open | Retracted; parsing hardened anyway |
| D | Payment completed outside the bulk action | ✅ Fixed |
| E | Refund does not reverse activation | 🛑 **Open — needs a policy decision** |
| **F** | **Registration rejects the registrant's own phone** | ✅ **Fixed** (`ec44894`) |
| G | Whitespace defeats ID uniqueness | Retracted |
| H | 1-cent instalment activates any tier | Documented — Association decision |
| I | Two `clean()` methods are verbatim duplicates | Documented — both tested |
| J | No size limit on the Digital ID photo | 🛑 **Open — needs a limit from you** |
| **K** | **`installment_amount` wrongly required** | ✅ **Fixed** (`617325a`) |

**Both live registration bugs are now closed.** Of thirteen ledger entries: four fixed, three retracted, four documented as intended, two open on decisions.

---

## `fix/forms-fk` — four commits

```
ec44894  Fix finding F: phone uniqueness no longer rejects the registrant's own number
8ac89d3  Record the K fix and the F stop
73dad3e  Record the expires_on caveat on Membership.activate() (comment only)
617325a  Fix finding K: allow blank installment_amount on lump-sum registration
```

Two production fixes, one comment, one record. Each independently revertable.

## Next

1. **Finding E** — the refund policy question. Does a refunded payment reverse the membership, or is honouring it through a dispute the intent?
2. **Finding J** — name a size limit and I will apply it as its own commit.
3. **Coverage priority 6** — `qr_manager`'s `generate_qr` and watermarking at 58%. Badges are physical artefacts, so a defect there is reprinted rather than redeployed.
4. **Branch housekeeping** — `fix/forms-fk` and `fix/finding-d-payment-activation` are both unmerged, alongside `coverage/phase-1` and `feature/qa-500-tests`.
