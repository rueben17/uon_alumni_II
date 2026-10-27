# Membership CRM: Add Member field/layout parity + background image — applied 2026-10-27

## What changed
1. **Background image.** `membership_list.html`, `membership_form.html`
   and `membership_confirm_delete.html` now carry the same fixed-position
   `page_background_url` backdrop as `membership_analytics.html`. No
   backend change — `page_background_url` is already a site-wide context
   var from `apps/home/context_processors.py`.

2. **Add Member field parity.** `NewMemberForm`
   (`apps/home/crm_forms.py`) now subclasses `AlumniRegistrationForm`
   directly instead of duplicating a parallel field set, so a walk-in
   registered by Secretariat staff collects the same ~25 fields a member
   would fill in themselves via Google-auth self-registration — minus
   `privacy_consent`, which is deliberately excluded (DPA 2019: consent
   can't be pre-granted on someone else's behalf).

3. **Bundled payment on create.** `MembershipCreateView.post()`
   (`apps/home/crm_views.py`) now mirrors `AlumniRegisterView.form_valid()`
   exactly: creates the `User`, the `AlumniProfile`, a pending
   `Membership` (`services.assign_membership_tier`), and a `PENDING`
   `Payment` in one `transaction.atomic()` block, instead of the CRM's old
   two-step "create membership, record payment later" flow. The payment
   still starts `PENDING` — confirming it (the drawer's Confirm button)
   stays a separate, deliberate action once the money has actually been
   received.

4. **Field order.** The reused form's fields render in `membership_form.html`
   using the same explicit fieldset grouping/order as
   `uon_alumni_register.html` (Personal Details → Contact Information →
   Graduation Details → Membership Subscription → Preferences), including
   the same faculty/qualification ⇄ other-institution toggle and M-Pesa
   eligibility toggle JS. A plain `{% for field in form %}` loop had
   rendered the ModelForm's internal field order instead (education
   fields before bio fields), which read as scrambled.

## Why
The Secretariat's complaint was that walk-in registrations entered through
the CRM were missing data a self-registered member always provides, and
that the form's field order didn't match the familiar self-registration
page. Reusing `AlumniRegistrationForm` directly (rather than hand-rolling
a second, parallel field list) is what actually guarantees the two stay
in parity going forward instead of quietly drifting apart.

## Verification
- `python manage.py check` — clean.
- `python manage.py test apps.home` — 190/190 passing (includes the
  rewritten `apps/home/tests_membership_crm.py` assertions for the new
  `Payment` row and the removed `privacy_consent` field).
- Rendered `/membership-crm/new/`, `/membership-crm/`, and a cancel-confirm
  page via the Django test client to confirm no template errors and the
  expected field order.
