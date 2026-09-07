# Secretariat Membership CRM — wired in

**Date:** 2026-09-04
**Branch:** `main`
**Executes:** `README_MEMBERSHIP_CRM.md`'s wiring instructions, against code that was already written and committed.

---

## What was added

Nothing new was written from scratch — `apps/home/crm_views.py`, `crm_forms.py`, `crm_urls.py`, and the five `templates/home/crm/*.html` templates already existed, committed but unmounted. This pass:

1. Read every one of those files, plus `docs/rebuild-schema.md` and `docs/payment-confirmation-workflow.md`, and cross-checked every model/mixin/service call the CRM makes against the actual current code.
2. Wired the one missing line.
3. Proved query efficiency with real numbers, not an assumption.
4. Wrote the test coverage that didn't exist yet.
5. Confirmed no regression anywhere else.

## The one wiring change

`main/urls.py`, beside the existing `membership-admin/` include:

```python
path("membership-crm/", include("apps.home.crm_urls")),
```

`include` was already imported; no other line touched. The console now lives at `/membership-crm/` on the main site, staff/superuser gated (`StaffOrSuperuserRequiredMixin` — same gate as `MembershipAnalyticsView`).

## Cross-check against the documented workflow — two notes, neither a defect

- `docs/payment-confirmation-workflow.md` still names `_activate_membership_for()`, a method retired in an earlier pass today (the admin's activation now routes through `services.confirm_payment()` directly). Pre-existing staleness, unrelated to the CRM, left untouched — outside this pass's scope.
- `RecordPaymentView` always sets `Payment.membership` (it's created from inside a specific membership's drawer), so `services.confirm_payment()` always takes the `record_installment_payment()` branch, never the lump-sum `activate_membership()` branch — even for a member's very first payment. Confirmed safe: `record_installment_payment()` activates correctly on first call (checks `status != ACTIVE`, not "is this an installment plan") and syncs `subscription_amount`/`amount_paid` either way. A different path from the admin's manual-entry flow, not a wrong one.

## CRUD / URL surface

| URL | View | Purpose |
|---|---|---|
| `membership-crm:list` | `MembershipListView` | Register: search (`q`), filter (`status`, `tier_type`), stat tiles, pagination |
| `membership-crm:drawer` `<uuid:pk>` | `MemberDrawerView` | Slide-over detail: membership, academics, payment history, record-payment form |
| `membership-crm:create` | `MembershipCreateView` | New person + pending membership (`NewMemberForm`) |
| `membership-crm:edit` `<uuid:pk>` | `MembershipUpdateView` | Direct correction of the row (`MembershipStaffForm`) |
| `membership-crm:record_payment` `<uuid:pk>` | `RecordPaymentView` | Record a payment, optionally confirm it immediately |
| `membership-crm:confirm_payment` `<int:payment_id>` | `ConfirmPaymentView` | Confirm an already-recorded pending payment |
| `membership-crm:cancel` `<uuid:pk>` | `MembershipCancelView` | Soft-cancel (`status=CANCELLED`), record survives |

## Query efficiency — proven, not assumed

Real `CaptureQueriesContext` counts, list grown 3 → 23 members and drawer grown 1 → 11 payments:

| View | Small | Large | Constant? |
|---|---:|---:|---|
| List (`membership_crm:list`) | 12 queries | 12 queries | ✅ |
| Drawer (`membership_crm:drawer`) | 7 queries | 7 queries | ✅ |

`_member_queryset()`'s `select_related("user", "user__profile", "tier", "user__alumni_profile", "user__alumni_profile__faculty")` was already correct in the drop-in code — no missing relation found, nothing needed adding.

## Tests — `apps/home/tests_membership_crm.py`, new module, 23 tests

| Class | Covers |
|---|---|
| `MembershipCrmAccessTests` | Anonymous → login redirect; authenticated non-staff → 403; staff → 200 |
| `MembershipCrmListTests` | Renders; search/status/tier filters narrow correctly; an invalid status value is ignored, not a 500 |
| `MembershipCrmHtmxTests` | `HX-Request` returns only the table partial; a plain request returns the full page |
| `MembershipCrmCreateTests` | Create → `PENDING` membership; an existing email is refused with a clear error, no membership created |
| `NewMemberFormConsentTests` | `sms_opt_in`/`email_opt_in` stay `False` — the DPA 2019 caveat |
| `MembershipCrmRecordPaymentTests` | `mark_completed` → `ACTIVE` + `membership_number` stamped; unchecked → recorded but still `PENDING`; no alumni profile → refused, nothing created |
| `MembershipCrmConfirmPaymentTests` | Confirming a pending payment → `ACTIVE`; confirming an already-completed one is a genuine no-op (membership `updated_at` unchanged) |
| `MembershipCrmEditTests` | Saves a changed tier/status |
| `MembershipCrmCancelTests` | GET shows the confirmation page; POST sets `CANCELLED`, row survives |
| `MembershipCrmQueryEfficiencyTests` | The two `CaptureQueriesContext` proofs above |

Self-contained module — local fixture helpers, no import from `apps/home/tests.py`, so no coupling to that file's much larger module-level setup.

## Verification

```
apps.home.tests_membership_crm:  23 tests, OK
apps.home (full):                149 tests, OK   (126 pre-existing + 23 new)
Full project suite:              288 tests, OK   (265 pre-existing + 23 new)
manage.py check:                 System check identified no issues (0 silenced)
makemigrations --check --dry-run: No changes detected
```

No migration. No file touched outside `main/urls.py` (one line), the three `apps/home/crm_*.py` files (read-only — no edits were needed, everything checked out), the five templates (read-only, no edits needed), the new test module, and this note.
