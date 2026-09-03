# Coverage priority 5 — `apps/home/forms.py` characterisation

**Date:** 2026-09-02
**Branch:** `coverage/phase-1` (the finding-D fix sits on `fix/finding-d-payment-activation`, unmerged)
**Baseline:** 34% — 161 of 243 statements uncovered
**Status:** 🛑 **Read-and-report only — no test written, no source touched.**

---

## The headline number is worse than 34% suggests

The uncovered ranges are:

```
79-213, 216-227, 230-236, 239-245, 248-277, 280-315,
372-396, 431-432, 435-455, 477-483, 486-489, 501-503, 506-509, 524-530
```

Mapped to source, that is **every `__init__`, every `clean_<field>`, every `clean()` and the one custom `save()` in the file**. The only executed code is class-body field declarations at import time, plus `ContactForm.__init__`.

**Not one validation method in this module has ever run in a test.** The 34% is almost entirely import-time execution — a good illustration of why the Phase 0 report cautioned against reading percentages as coverage of behaviour.

---

## Reassuring findings first

Three things this file does **not** do, all worth stating because they are the risks the brief anticipated:

**No mass assignment.** No form exposes `status`, `amount_paid`, `membership_number`, `is_lifetime`, `expires_on`, `is_active`, or any staff/superuser flag. `AlumniProfileForm.Meta.fields` (`:65-76`) is an explicit ten-field allow-list; `AlumniDigitalIDApplicationForm` exposes exactly one field.

**No invariant bypass.** No form writes `Membership` at all. `MembershipUpdateForm` and `AlumniRegistrationForm` are plain data collectors — the views create the `Membership` through `services.assign_membership_tier`, which is the door the lifecycle tests guard.

**Tier querysets are constrained.** Both membership forms use `MembershipTier.objects.filter(is_active=True)` (`:330`, `:408`), so an inactive tier cannot be submitted even by a hand-built POST — `ModelChoiceField` re-validates against the queryset.

**One genuinely defensive piece of code**, at `:438-445` and again at `:375-382`:

```python
        if frequency == Membership.PaymentFrequency.ONCE:
            # ... strip installment_amount here rather than trusting it stays blank,
            # so a stray/crafted value in the POST ... can never override tier.fee
            cleaned_data["installment_amount"] = None
```

That anticipates a crafted request and neutralises it. It is also completely untested.

---

## Candidate findings

Noted, **not fixed**. Only the first looks like a real defect.

### Finding F — the phone uniqueness check can reject the user's own number

`clean_phone_mobile` (`:215-227`):

```python
        owner = User.objects.filter(phone=normalized)
        if self.instance.user_id:
            owner = owner.exclude(pk=self.instance.user_id)
        if owner.exists():
            raise forms.ValidationError("This phone number is already registered to another account.")
```

The self-exclusion is keyed on `self.instance.user_id`. On the **registration** path that is `None`, because `AlumniRegisterView.form_valid` sets `form.instance.user = self.request.user` at `views.py:468` — which runs only *after* `is_valid()` has passed.

So during validation the exclusion is skipped, and a registering user whose `User.phone` is already populated sees **their own number** reported as *"already registered to another account."*

Reachable when `User.phone` is set before the alumni profile exists: a legacy-imported account, or any future flow that captures a phone at signup. Google OAuth does not set it today, which is why this has not bitten yet.

The edit path is fine — `AlumniProfileUpdateView` works on a saved instance, so `user_id` is present.

### Finding G — ID/passport uniqueness is an exact match only

`clean_id_passport_no` (`:238-245`) does `UserProfile.objects.filter(national_id=national_id)` with no normalisation. `"12345678"`, `" 12345678"` and `"12345678 "` are three different values to both this check and the model's `unique=True`, so the same ID can be registered several times with incidental whitespace. A data-quality gap rather than a security one.

### Finding H — an instalment plan can be opened for one cent

`installment_amount` has `min_value=Decimal("0.01")` (`:351`, `:425`) and **no relation to `tier.fee`**. Since `record_installment_payment` activates on the first payment regardless of amount, a KES 1,000,000 Corporate membership becomes ACTIVE on a 1-cent instalment.

**This is the documented Association decision**, stated at `forms.py:341-343` — *"membership activates on this first payment regardless of amount (Association decision)"* — and a Secretariat member must still confirm the payment, so there is a human gate. Recorded as a business-risk question, not a defect.

### Finding I — two `clean()` methods are verbatim duplicates

`AlumniRegistrationForm.clean` (`:371-396`) and `MembershipUpdateForm.clean` (`:434-455`) contain the same ONCE-stripping logic and the same M-Pesa tier gate, comments included. A change to one will silently miss the other. Maintenance risk; both need testing independently regardless.

### Finding J — no size limit on the Digital ID photo

`AlumniDigitalIDApplicationForm` (`:512-530`) makes `digital_id_photo` required but adds no size or dimension validation. Django's `ImageField` verifies it *is* an image; a 50 MB one is accepted.

---

## Form-by-form

| Form | Base | Model / fields | Validates | Does **not** validate |
|---|---|---|---|---|
| `ContactForm` `:13` | `ModelForm` | `ContactMessage` — name, email, subject, message | Model-level; `subject` made optional in `__init__` | Nothing custom. No rate limiting or spam gate |
| `AlumniProfileForm` `:31` | `ModelForm` | `AlumniProfile` — 10 fields, plus 19 declared fields fanned out to `User`/`UserProfile` in `save()` | Phone normalisation + uniqueness; ID uniqueness; institution-conditional requirements | Whitespace in IDs (F, G) |
| `AlumniRegistrationForm` `:318` | extends above | + tier, method, frequency, instalment, `privacy_consent` | DPA consent gate (`required=True`); ONCE strip; M-Pesa tier gate | Instalment vs fee (H) |
| `MembershipUpdateForm` `:399` | `Form` | — | Same three as above | Duplicated logic (I) |
| `ProfileClaimSearchForm` `:458` | `Form` | — | Phone normalisation; at least one of email/phone | — |
| `ProfileClaimCodeForm` `:492` | `Form` | — | 6 chars, digits only | — |
| `AlumniDigitalIDApplicationForm` `:512` | `ModelForm` | `AlumniProfile` — `digital_id_photo` only | Required, is-an-image | Size/dimensions (J) |

### The conditional-requirement pattern

`AlumniProfileForm.__init__` (`:121-145`) sets `required` from an `optional_fields` allow-list, so `faculty`, `qualification`, `other_institution_name` and `other_institution_qualification` are all optional at field level. `clean()` (`:247-277`) then enforces whichever branch applies:

- **UoN**: faculty and qualification both required, and `qualification.faculty_id` must match the selected faculty — a cross-field integrity check worth testing.
- **Other**: institution name and qualification required; `faculty`/`qualification` forced to `None`.

### Form ↔ model ↔ signal

`AlumniProfileForm.save` (`:279-315`) is the only form touching multiple models. It is **consistent with the auto-create signal**:

```python
        profile = getattr(user, "profile", None) or UserProfile(user=user)
```

The `getattr` guard finds the signal-created row and updates it rather than creating a second — the same pattern `adapter.py:101` uses, and the `or UserProfile(user=user)` fallback is harmless belt-and-braces now that the signal guarantees the row.

It also writes `User.phone` (`:300`, saved with `update_fields`) and routes the alternate e-mail through allauth's `EmailAddress` rather than a second column (`:310-314`). None of that is covered.

---

## Test hazards

| Hazard | Detail |
|---|---|
| `__init__` querysets | `qualification.queryset` is rebuilt with `select_related` at `:115`; `required` flags are set in `__init__`, so a form must be **instantiated**, not just inspected as a class |
| Unsaved instance | `self.instance._state.adding` — not `pk` — is the existence check (`:88`), because `AlumniProfile.id` is a `UUIDField` with a default and is non-null even when unsaved. Tests must respect that |
| No request/user injection | None of these forms takes `request` or `user` in `__init__` — they are pure-data. **No `HTTP_HOST` needed anywhere** |
| Finding F | Needs the registration shape specifically: an unsaved instance whose user already has a phone |
| Digital ID photo | Needs a real image and a temp `MEDIA_ROOT`, and a PIL-generated PNG — the hand-rolled blob failed in the QR-badge pass |
| `UserProfile` | The signal auto-creates it; fixtures must fill rather than create |
| Phone fixtures | `User.phone` is unique, so each fixture needs its own number |

---

## Proposed test list — 32 tests

All pure-data; none needs a host.

**`ContactForm` (2)** — valid input; missing required fields rejected, `subject` genuinely optional.

**`AlumniProfileForm` (13)**
- `clean_phone_mobile`: normalises a local number; rejects an invalid one; rejects a number owned by another account; **finding F** — an unsaved instance whose user already owns that number
- `clean_phone_alt`: blank returns `""`; valid normalises; invalid rejected
- `clean_id_passport_no`: accepts a fresh ID; rejects one held by another profile; **finding G** — the same ID with surrounding whitespace is accepted twice
- `clean()`: UoN branch requires faculty and qualification; rejects a qualification from a different faculty; Other branch requires both institution fields and nulls faculty/qualification
- `save()`: fans out to `UserProfile`, `User.phone` and an allauth `EmailAddress`, with exactly one profile row
- `__init__`: prefills from an existing profile on the edit path

**`AlumniRegistrationForm` (5)** — `privacy_consent` refused when unticked; ONCE strips a crafted `installment_amount`; non-ONCE requires one; M-Pesa rejected on a tier above the ceiling and accepted below it.

**`MembershipUpdateForm` (5)** — the same four, plus an inactive tier rejected by the queryset.

**`ProfileClaimSearchForm` (4)** — neither field rejected; email alone accepted; phone alone normalised; invalid phone rejected.

**`ProfileClaimCodeForm` (3)** — six digits accepted; non-numeric rejected; wrong length rejected.

**`AlumniDigitalIDApplicationForm` (2)** — required when missing; a real PNG accepted under a temp `MEDIA_ROOT`.

---

## Awaiting sign-off

1. **Approve the 32-test list?**
2. **Finding F** — write it as a documented reproduction asserting current behaviour, as with findings D and B?
3. **Findings G, H, I, J** — record as observations only, or open any as work? My reading: G is worth fixing cheaply (strip and case-fold before the lookup); H is a business question for the Association; I and J are maintenance notes.

🛑 Characterisation + test list complete — awaiting sign-off.
