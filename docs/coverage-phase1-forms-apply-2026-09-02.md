# Coverage priority 5 — forms covered, finding K surfaced

**Date:** 2026-09-02
**Branch:** `coverage/phase-1`
**Commit:** `d7de374`
**Executes:** [`coverage-phase1-forms-step1-2026-09-01.md`](coverage-phase1-forms-step1-2026-09-01.md)

**No production code changed.** `git status` showed only `apps/home/tests.py`.

---

## 🛑 New finding K — a live bug on the registration path

**Reported, not fixed.** It is a defect beyond the F/G/H/I/J set this pass was scoped around, so it stops here for a decision.

`installment_amount` is declared `required=False` (`forms.py:350`), and its own help text says *"leave blank to pay the full fee"*. But `AlumniProfileForm.__init__` (`:144-145`) rebuilds **every** field's required flag from an allow-list:

```python
        for field_name in self.fields:
            self.fields[field_name].required = field_name not in optional_fields
```

The four subscription fields `AlumniRegistrationForm` adds — `membership_tier`, `payment_method`, `payment_frequency`, `installment_amount` — are not in `optional_fields`. Three of them *should* be required; the fourth should not. The inherited loop silently overrides the declaration.

Verified directly:

```
AlumniRegistrationForm.installment_amount   required=True    (declared: False)
MembershipUpdateForm.installment_amount     required=False
```

**Effect: a member registering with "Once" who leaves the amount blank — exactly what the help text instructs — is refused.** The lump-sum registration path is blocked at the form.

`MembershipUpdateForm` declares the identical field but has its own `__init__`, so it is unaffected. That contrast is what isolates the fault to the inherited loop rather than to the field, and both halves are asserted in the test.

**Likely fix**, for a separate authorised pass: add `installment_amount` to `optional_fields`, or re-assert `required=False` after `super().__init__()` in `AlumniRegistrationForm`. Small, but it is a production change.

---

## Two of my own Step 1 findings were wrong

Worth recording plainly rather than quietly dropping — this is now the third and fourth candidate finding of this stream that I raised and then had to withdraw or correct.

### Finding F — confirmed, but my test shape was wrong

I built the reproduction with `AlumniProfile(user=registrant)`. Assigning `.user` sets `user_id` **even on an unsaved instance**, so the self-exclusion worked and the form accepted the input — the opposite of what I predicted.

The real registration shape is different: `CreateView` passes **no instance**, so `ModelForm` constructs a bare `AlumniProfile()` whose `user_id` is `None`, and `.user` is only assigned later in `form_valid` (`views.py:468`).

```
instance.user_id on a fresh form: None | _state.adding: True
```

With that shape it reproduces: the registering user's own number is reported as *"already registered to another account."* The edit path is covered alongside it as the contrast, and passes.

**The finding stands; my first attempt to prove it did not.**

### Finding G — retracted

I claimed the exact-match ID lookup would let a duplicate through with incidental whitespace. It does not. `forms.CharField` strips by default (`strip=True` since Django 1.9), so `" 12345678 "` is already `"12345678"` before `clean_id_passport_no` runs, and the duplicate is caught.

```
forms.CharField().clean('  12345678  ')  ->  '12345678'
```

The test now documents the correct behaviour and records the retraction.

---

## Result

| | Before | After |
|---|---:|---:|
| `apps/home/forms.py` | 34% | **99%** |
| Overall | 64% | 67% |
| Suite | 191 tests | **221, all green** |

34 tests. One statement remains uncovered — `forms.py:252`, the early `return cleaned_data` when `graduation_institution` is falsy.

The jump is large because the baseline was misleading: **not one `clean_*`, `clean()`, `save()` or `__init__` in the module had ever executed.** The 34% was almost entirely field declarations running at import, which is exactly the illusion the Phase 0 report warned percentage-reading would create.

---

## Properties now pinned

The Step 1 reassurances are no longer assertions on my part — they are tests:

| Property | Where |
|---|---|
| The ONCE-strip defeats a crafted `installment_amount` | `forms.py:375-382`, `:438-445` — both copies tested independently (finding I) |
| The DPA consent gate refuses submission, not just the UI | `privacy_consent`, `required=True` |
| The M-Pesa fee ceiling is enforced **both ways** | Refused above KES 100,000, accepted below |
| An inactive tier cannot be submitted | The `is_active=True` queryset, re-validated by `ModelChoiceField` |
| `save()` leaves exactly **one** `UserProfile` row | The `getattr` guard co-operating with the auto-create signal |
| `save()` writes `User.phone` and an allauth `EmailAddress` | Not a second e-mail column |
| The cross-field faculty/qualification check | A qualification from another faculty is rejected |

---

## Findings ledger

| # | Finding | Origin | State |
|---|---|---|---|
| — | Membership numbering skips on renewal | lifecycle | Documented; contract holds |
| — | `activate_membership` recomputes `expires_on` | lifecycle | Documented |
| A | `get_connect_redirect_url` returns `None` | adapter | ❌ Retracted — my misread |
| B | Bare `home:` reverse 500ing staff login | adapter | ✅ Fixed (`26dd281`, `6763ba1`) |
| C | `RESTRICT_*` parsing fails open | adapter | ❌ Retracted as a defect; parsing hardened anyway (`590f42f`) |
| D | Payment completed outside the bulk action never activated | payments | ✅ Fixed (`ab52175`, `8f8c27e`) |
| E | Refund does not reverse activation | payments | 🛑 Open — policy decision |
| F | Registration rejects the user's own phone | forms | 🛑 Open — confirmed on the second attempt |
| G | Whitespace defeats ID uniqueness | forms | ❌ Retracted — `CharField` strips |
| H | A 1-cent instalment activates any tier | forms | Documented — Association decision, human-gated |
| I | Two `clean()` methods are verbatim duplicates | forms | Documented — both tested independently |
| J | No size limit on the Digital ID photo | forms | Documented |
| **K** | **`installment_amount` wrongly required; lump-sum registration blocked** | **forms** | 🛑 **Open — live bug, pinned** |

Eleven candidate findings raised across the stream: **two fixed, three retracted, three open, three documented as intended behaviour.** The retraction rate is worth noting — reading code is not the same as running it, and three of my confident diagnoses did not survive contact with a test.

---

## Where the coverage build stands

| Priority | Area | Status |
|---:|---|---|
| 1 | `services.py` lifecycle | ✅ 100% |
| 2 | `expire_lapsed_installment_plans` | ✅ Covered |
| 3 | `adapter.py` OAuth | ✅ 86% |
| 4 | Payment-confirmation path | ✅ `payments.py` 100% |
| 5 | `home/forms.py` | ✅ **99%** |
| 6 | `qr_manager` `generate_qr` and watermarking | 58% — **next** |
| 7 | `home/views.py` / `staff/views.py` POST handling | ~50% |
| 8 | `Membership` model behaviour | 90% |
| 9 | `tasks.py` e-mail and SMS | 18% |
| 10 | `import_legacy_memberships` | 0% |

## Next

1. **Finding K** — small fix, live bug on the primary registration path. My recommendation: take it before continuing, as with finding B. Findings F and K are both in `AlumniProfileForm`/`AlumniRegistrationForm` and could sensibly be one pass.
2. **Coverage priority 6** — `qr_manager`'s `generate_qr` and watermarking at 58%; badges are physical artefacts, so a defect is reprinted rather than redeployed.
3. **Finding E** — the refund policy question, still open.
