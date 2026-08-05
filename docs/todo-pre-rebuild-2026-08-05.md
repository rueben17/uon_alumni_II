# AIMS — Implementation TODO

Working document for the Django AIMS build. Sequenced **core-out**: each ring
works before the next is added. The core isn't payments — it's a member
existing and managing their own membership. Payments attach to that core later.

> **Core-out principle (the thing that sets the order):** sequence follows
> *dependency*, not what was queued first. A membership can be renewed manually
> (Secretariat already does this in admin) with no gateway at all — so
> membership management stands alone. A payment is meaningless until there's a
> membership for it to act on — so payments are an *outer* ring. Build the core
> that works without money first; attach money to it after.

Rings, innermost first:
- **Phase 0** — Identity foundation (who the person is)
- **Phase 1** — Member core (register → dashboard → manage membership; manual activation)
- **Phase 2** — Payments (attach to the core; automate what was manual)
- **Phase 3+** — Comms, events, donations, commerce, QR credential, integrations

---

## Guiding decisions (settled — don't relitigate mid-build)

- **Identity anchor = `User.pk` (UUID).** Stable across student → alumnus →
  staff. Never a login handle directly, never changes.
- **User-anchored identity, not abstract base.** Shared person data lives once
  on a `UserProfile` (O2O to `User`, in `apps/user/`). Role models
  (`AlumniProfile`, `Employee`, future `Student`) become thin.
- **Phone is the mandatory primary login handle** — required, verified, unique.
  Load-bearing for M-Pesa later, so it exists regardless of comms preference.
- **Email is secondary / future.** Built multi-handle-capable now so the future
  `@alumni.uonbi.ac.ke` address slots in with no migration.
- **Access-through, no delegation properties.** Write call-sites in final form
  (`alumni.user.profile.national_id`).
- **Phone stored as E.164 with the `+`** (`+254712345678`) via
  `django-phonenumber-field`. Transform at each boundary, never at storage.
- **One shared normalize function** — both model `save()` and the auth backend
  call it, so registration and login produce byte-identical strings.
- **Transactional vs. consent split:** OTP + receipts ride the phone *always*
  (security/identity). `sms_opt_in` gates only *marketing* comms.
- **Tiers + benefits are admin-managed data, not hardcoded.** `MembershipTier`
  has related `Benefit`/`Entitlement` rows, edited via **inline forms in the
  main Django admin** so the Association changes "what Gold gives" without a
  deploy. The system owns the *mapping*; the Association owns the *values*.

---

## Cross-cutting (applies to EVERY phase — not a phase you finish)

These span the whole build. Stated once here; each phase honors them. DPA
especially can't be bolted on at the end — consent must exist *before* data is
collected.

- **Data Protection Act 2019 (Kenya) — legal, non-optional.** Holding national
  IDs, phones, DOBs for tens of thousands of people.
  - Consent capture at **registration** (Phase 1) — explicit, purpose-stated.
  - Directory listing is **opt-in, private by default** (see Phase 1). Publishing
    by consent, never open search of member data.
  - Scan-log movement data (QR) is personal data — must be in the privacy notice
    with a stated purpose + retention limit.
  - Retention rule + the **soft-delete vs. right-to-erasure** tension: current
    `is_active=False` keeps data forever, which can conflict with an erasure
    request. Decide the reconciliation.
- **Backups / DR.** Data lives on **UoN servers** — a backup + restore method
  must be provided and owned. Live payment + PII data; "who restores this and
  how" needs an answer, not an assumption.
- **Secrets in `.env`** — M-Pesa (Daraja sandbox vs prod keys differ), Stripe,
  SMS/email provider creds. Never in the repo. Standard, but stated.
- **Rate limiting — a must.** Public endpoints (registration, and especially the
  **OTP-send endpoint — every send is an SMS you pay for**) need throttling.
  Abuse *and* cost protection.

---

## PHASE 0 — Identity foundation (prerequisite for everything)

### 0.1 Decide + document, before touching any model
**DONE 2026-08-05 → `docs/0.1-identity-decisions.md`.** Two settled decisions
changed there, with reasons: membership moves off `AlumniProfile` into its own
`Membership` model on `User` (D3 — the free Student tier has no alumni record to
attach to), and the identity anchor gains `User.public_id` rather than migrating
the pk (D2 — `User.pk` is a `BigAutoField`, not a UUID as the plan assumed).
- [x] Confirm `UserProfile` lives in `apps/user/` alongside `User`.
- [x] Write down the final field map:
      - **Move to `UserProfile`:** title, given/middle/family name, DOB,
        national_id (unique here), nationality, postal address, phone,
        contact prefs (`sms_opt_in`, `email_opt_in`).
      - **Stay on `AlumniProfile`:** qualification, graduation year/institution,
        membership fields (tier, expiry, lifetime, membership number, issued-item
        flags), the alumni `slug`, all membership business logic.
- [x] **Student→alumnus lifecycle is the payoff of User-anchored identity.** A
      `Student` role attaches to a User; at graduation the *same* User gains an
      `AlumniProfile` — history intact, no re-registration. The free student
      membership (see Phase 1 tiers) becomes the on-ramp to a paid tier. Design
      the `Student` role thin, on the same User, from the start.
- [x] **Tier taxonomy** (from the Association's form/brochure — set values;
      benefits are admin-managed per the guiding decision):
      - *Life (one-time, permanent, `lifetime=True`, starred perks apply):*
        Gold 100k, Silver 50k, Bronze 25k.
      - *Recurring (per-period, no starred perks):* Full Annual 2,000;
        Honorary 3,000 (**conferred, but still paid** — status granted, payment
        still required); Corporate 1,000,000 (organizational).
      - *Student:* free / nominal — pipeline tier (see Phase 1).
      - **Upgrade ladder is monotonic:** Annual → Bronze → Silver → Gold →
        Corporate. Installment upgrades (Phase 2) target the *next rung's* price.
      - `payment_frequency` (once / monthly / quarterly / annually) is a member
        choice from the form — feeds Phase 3 reminder cadence.

### 0.2 Add the phone infrastructure
- [x] `pip install django-phonenumber-field[phonenumbers]`; add to settings.
      Done 2026-08-05: `phonenumber_field` in `INSTALLED_APPS`, both pins in
      `requirements.txt`, `PHONENUMBER_DEFAULT_REGION`/`_FORMAT` pinned
      explicitly so the stored format can't drift via a settings change.
- [ ] Replace the hand-rolled `+254XXXXXXXXX` regex with
      `PhoneNumberField(region="KE", unique=True)`.
      **Deferred to 0.3 on purpose:** the field it would replace is
      `AlumniProfile.phone_mobile`, which 0.3 moves to `UserProfile` anyway.
      Swapping it in place first would spend a migration on a column that is
      about to be deleted. `UserProfile.phone` is created as a
      `PhoneNumberField` directly.
- [x] Write the **shared normalize function** (e.g. `apps/user/phone.py`):
      any input → parse via `phonenumbers` (`region="KE"`) → E.164 (`+254...`).
      Imported by both the model and the auth backend — never reimplemented.
      Done 2026-08-05: `normalize_phone()` + `try_normalize_phone()` (lenient
      wrapper for the 0.4 auth backend's lookup path), 11 tests in
      `apps/user/tests.py`, all passing.
- [ ] Enforce normalization at `save()` (override or `pre_save`), so the DB
      never holds a non-canonical value regardless of entry path. Uniqueness
      only works if every value is already canonical.
      **Blocked on 0.3** — there is no `UserProfile.save()` to hook until the
      model exists. The function it will call is written and tested.

### 0.3 Build `UserProfile` + migrate live data
- [ ] Create `UserProfile` (O2O → User, `related_name="profile"`).
- [ ] **Rename pass first, as its own migration:** reconcile field-name drift
      between `Employee`/`AlumniProfile` with `RenameField` (never
      drop-and-re-add — data must ride across).
- [ ] **Then** the structural migration: create `UserProfile`, backfill from
      existing rows (data migration), then remove moved fields from role models.
      Separate migrations so a failure is isolated and reversible.
- [ ] `AutoSlugField` wrinkle: point `populate_from` at
      `self.user.profile.full_name`. The alumni `slug` stays on `AlumniProfile`
      (role-scoped public URL).

### 0.4 Auth: phone-as-login
- [ ] Custom auth backend resolving a submitted phone (via the shared normalize
      fn) → User. Email stays usable too.
- [ ] OTP verification for phone (Africa's Talking or chosen provider). This is
      *transactional* SMS — foundational, not the later marketing build.
- [ ] **Identifier-change flow:** new SIM → login handle *and* (future) M-Pesa
      key both move. Deliberate "change verified identifier" flow.
- [ ] Room for multiple verified emails per User (capacity now, activate when
      `@alumni.uonbi.ac.ke` is approved — no schema change then).

### 0.5 Chase every call-site (bites silently)
- [ ] Forms: `AlumniProfileForm.clean()`, registration + update forms →
      repoint to `user.profile.*`.
- [ ] CBVs in `apps/home/views.py`.
- [ ] Both admin registrations, incl. scoped `membership_admin_site`.
- [ ] Templates rendering profile fields.
- [ ] **`apps/user/adapter.py` — test hardest.** Decides login redirects off
      profile existence; a half-done rename bites here silently.

### 0.6 Foundational hygiene
- [ ] Audit trail (`django-simple-history`) while schema is small — who changed
      what, old → new. (2014 doc promised it; doesn't exist yet.)
- [ ] Test suite around the auth backend + profile migration.
- [ ] Containerized deploy if not already.

---

## PHASE 1 — Member core (register → dashboard → manage membership)

The innermost functional ring. Works end-to-end with **no payment gateway** —
activation is manual (Secretariat), exactly as today's `PaymentAdmin.mark_completed`.
This is the loop that must be demonstrable before payments exist.

### 1.1 Self-registration
- [ ] Simple self-service signup → creates User + `UserProfile` + `AlumniProfile`.
      Registration does NOT activate membership (unchanged rule).
- [ ] Phone required + verified at signup (rides Phase 0 OTP).

### 1.2 Member dashboard (your own)
- [ ] Self-resolved from `request.user` (no pk in URL — matches existing
      `AlumniProfileUpdateView` pattern).
- [ ] Shows: profile, membership status, tier, expiry, issued-item flags,
      payment/renewal history.
- [ ] Self-service profile edit.

### 1.3 Membership management + the one door
- [ ] **Service layer first:** wrap `renew_membership()`,
      `upgrade_to_lifetime()`, `assign_membership_tier()` so *every* caller
      (admin now, payment callback later, scheduled jobs) goes through one door.
      Manual approval is its first caller; payments become just another caller
      in Phase 2. Build this here, not later — it's what keeps Phase 2 from
      fragmenting state changes.
- [ ] Member-initiated **renewal** request → pending state.
- [ ] Member-initiated **upgrade** (incl. to lifetime) request → pending state.
- [ ] Expiry / validity tracking surfaced on the dashboard (off `is_membership_valid`).
- [ ] Secretariat **manual approval** in scoped admin calls the service layer to
      activate / stamp membership number. (Same human step as today — just now
      routed through the one door.)

### 1.4 Status visibility
- [ ] Member sees pending vs. active vs. expired clearly.
- [ ] Renewal/upgrade history visible to member and Secretariat.

### 1.5 Registration fields — finalize against the 2024 form
- [ ] Fields are the Association's membership form: personal (title,
      first/middle/surname, gender, national ID/passport), graduation (place,
      name-at-graduation, degree, faculty); contact (employment, position,
      physical + postal address, tel, email).
- [ ] **Graduation year = the FIRST degree's year** — that's when the person
      officially became an alumnus/alumna. `graduation_year` stays
      **single-valued** and means "date of alumnus status," not "any
      graduation." Later/tertiary degrees are additional qualifications, not a
      second entry into the alumni body — if captured at all, they're a separate
      optional list (Association's call), never the anchor.
- [ ] Membership category selected on the form (tier taxonomy from 0.1).

### 1.6 Tier + benefit admin (inline forms, main Django admin)
- [ ] `Benefit`/`Entitlement` model related to `MembershipTier`, editable as
      **inlines** on the tier in the main admin — Association manages what each
      tier grants, no deploy needed.
- [ ] Seed with the **Association's own stated benefits first** (from brochure):
      newsletter/SMS-email alerts, library access, governance participation,
      alumni card, certificate, lapel badge, Chancellor-ranking participation,
      Distinguished Leadership Awards. Starred (card/cert/badge/governance/
      ranking) = **Life members only**, per the brochure's own footnote.
- [ ] Then build on researched references (proposed — for Association approval;
      they set final values):
      - *Gradient within Life tiers:* Bronze = entry to starred perks + base
        discount band; Silver = deeper discount band + priority event
        registration + magazine/website recognition; Gold = top discount band +
        VIP at flagship events + recognition wall/honor roll + board eligibility
        + encouraged Corporate path.
      - *Annual:* newsletter + alerts, paid event access, opt-in directory, QR
        credential, member merchandise rate. No starred perks. (Entry rung.)
      - *Honorary:* conferred dignity tier — recognition + access perks
        regardless of price; should *present* as prestigious.
      - *Corporate:* multiple named reps, event branding/visibility, partnership
        recognition, bulk engagement. Org-shaped, not person-shaped.
      - *Student (pipeline — designed to draw them in):* **free/nominal.** Draw =
        access to *alumni*, not campus resources students already have. Alumni
        **mentorship**, networking nights, internship/job access via the network,
        career workshops, student-ambassador/board roles, event + merch
        discounts, and a **graduation conversion incentive** (discounted/
        streamlined path from free student → paid life/annual at graduation).
        This is the front of the funnel the identity model was built for (0.1).

### 1.7 Directory — opt-in, private by default (DPA)
- [ ] Per-member **visibility toggle** (`private` default; "visible" /
      "members-only" / "private" if you want granularity). Nobody exposed until
      they affirmatively choose.
- [ ] Public directory shows only opted-in members, only the fields they agreed
      to expose (name yes; national ID never; phone optional).
- [ ] **No open search of member data** — a member may *appear* by choice, but
      the system does not let others query/lookup records. Publishing by consent,
      not lookup. (DPA 2019 — see cross-cutting.)

### 1.8 Spreadsheet export/import
- [ ] `django-import-export` in admin — solves the Secretariat's "give me a
      spreadsheet of paid members" on day one, plus bulk import. Retires the
      export gap entirely.

---

## PHASE 2 — Payments (attach to the member core; automate the manual step)

Goal: flip Phase 1's manual approval from *the* path into an *exception* queue.
Everything here plugs into the service layer built in 1.3 — payments become just
another caller of the same door.

### 2.1 M-Pesa (Daraja)
- [ ] STK push for registration + renewal.
- [ ] C2B + callback handling for reconciliation. **Record the Payment
      explicitly in the webhook view — NOT via a signal** (preserves the
      "state changes are explicit" property; the webhook already runs your code,
      a signal would only hide the flow and make retries harder to guard).
      - Persist the provider's transaction ID (`MpesaReceiptNumber`) at callback
        time, independent of end-of-month statements — this is your own record
        of truth for accounting/audit.
      - `provider_txn_id` field with **`unique=True`** — this DB constraint is
        the real idempotency guarantee (providers retry callbacks; the unique
        constraint is what prevents duplicate rows even under a race, not
        `get_or_create` alone).
      - Store the **raw payload verbatim** in a JSON field alongside parsed
        fields — the audit blob statements can't give you.
      - Pattern: `get_or_create(provider_txn_id=...)` → act only if `created` →
        call the 1.3 service layer → always return 200 so retries stop.
- [ ] Daraja boundary strips the `+`:
      `str(profile.phone.as_e164).lstrip("+")` → `254712345678`.
      (Storage stays E.164; only this call site strips.)

### 2.2 Card payments — Stripe
- [ ] Stripe for Visa/Mastercard card processing (international donors).
- [ ] Same webhook pattern as 2.1: record the Payment explicitly in the Stripe
      webhook view, keyed on the Stripe `PaymentIntent`/charge `id` as the
      unique `provider_txn_id`; verify the webhook signature; store raw event;
      idempotent via the unique constraint. (Stripe retries webhooks too.)

### 2.3 Reconciliation + the human's new role
- [ ] Auto-reconciliation → activates membership via the **1.3 service layer**.
      Successful match = no human touch.
- [ ] **Exception queue:** only unmatched/ambiguous payments reach Secretariat.
      Reframes 1.3's manual approval from "approve everything" to "handle only
      what didn't auto-match."
- [ ] **Keep `ManualGateway` alive** as offline/cash fallback — demoted, not deleted.

### 2.4 Transactional receipts
- [ ] Payment receipt via SMS/email on success (transactional — always sent,
      not gated by `sms_opt_in`).

### 2.5 Reconciliation key (design decision)
- [ ] Automated matching links payment → member via the **STK-push / webhook
      identifiers directly** — do NOT inherit the manual "Name & Category in the
      M-Pesa account string" convention from the paper form. That string was a
      human-matching crutch; the automated path has real IDs.

### 2.6 Refunds + installments (end-of-phase financial flows)
- [ ] **Excess-payment refund** method: someone overpays → refund the
      difference. Distinguish from a full reversal: an *excess* refund does NOT
      deactivate membership (they still paid enough); a *full* reversal might.
      Refund/reversal webhooks (M-Pesa reversal, Stripe refund) record via the
      same explicit pattern as 2.1.
- [ ] **Installment upgrades** toward the next ladder rung (0.1): a payment can
      be *partial toward a target*. Accumulate amount-paid-toward-tier; upgrade
      via the **1.3 service layer** only when cumulative payments clear the next
      rung's price. Rides the existing many-Payments-per-member relation; the
      accumulation logic is the new part.

---

## Later phases (direction only — detail when we reach them)

- **Phase 3 — Communications:** consent-gated bulk SMS + email, templated
  renewal reminders + expiry notices off `expiry_date`, scheduled jobs. The
  *marketing* half `sms_opt_in` governs.
  - `Communication`/`Campaign` model: subject, body, type
    (newsletter/bulletin/announcement), channel (email/SMS/both), audience
    filter, scheduled-send time, status.
  - Per-recipient **send log** (who, when, delivered/failed) — audit + prevents
    double-sends. Same reasoning as the payment audit trail: record what
    *actually* went out, not just what was intended.
  - Audience filter respects `sms_opt_in`/`email_opt_in`. This consent-gated
    marketing path stays **separate from the always-send transactional path**
    (OTP, receipts) — same sending infra underneath, different governance on top.
- **Phase 4 — Events:** post an event, members RSVP, reminders ride Phase 3
  comms. Social *login + share*, NOT a rebuilt social network.
- **Phase 5 — Donations:** online giving, pushes to **STK push (M-Pesa) / card
  (Stripe)** — rides the Phase 2 payment rails directly. Records via the same
  explicit webhook-records-Payment pattern (unique `provider_txn_id`, raw
  payload, idempotent) as membership payments; a donation is just a Payment with
  no membership to activate.
- **Phase 6 — Commerce:** UNES merchandise store on Phase 2 payments. Lowest
  priority. Small lift once payments exist — it's the beneficiary of everything
  below, not a hard build. Can jump the queue if the bookstore pushes.
- **Phase 7 — QR membership credential:**
  - QR issued to **all members**, resolves to a **public benefit page** showing
    member category + tier entitlements (name + category + benefits — *nothing
    sensitive*; it's a credential, not a profile). Consumes the 1.6 tier→benefit
    mapping.
  - QR encodes an **opaque token**, not the raw membership number — no scannable
    code should leak a real ID.
  - The **physical/branded card + 20% retail discount is a Life-member benefit**
    (per brochure), distinct from the QR page everyone gets. Two things, one
    word "card" — keep them separate in the model.
  - **Scan log — LAST, separable add-on** (where/when/IP of each scan) for
    audit + analytics (library check-ins, parking peaks). The benefit page
    verifies by *display*, so the log is optional to the core feature — ship the
    page first, add logging after. Movement data ⇒ **DPA notice + retention**
    (cross-cutting).
- **Phase 8 — University integrations:** SMIS first (auto-populate alumni from
  graduation records — where a real API/ETL layer earns its place), then HRMIS
  (staff-alumnus / payroll check-off), Library (SSO / borrowing).

### Parallel workstreams (not in the phase sequence)
- **Booklet digitization 1956–2008:** scan → OCR/structure → load into schema.
  Independent; can grind alongside from Phase 0 onward.
- **DRF / API layer:** resist until Phase 8 or the first real consumer (SMIS ETL,
  mobile app, decoupled portal). Premature before something needs it.

---

## Explicitly out of current scope (conscious deferrals — revisit, not forgotten)

Recorded so nobody later mistakes these for gaps. Executed, the phases above
bring AIMS fully in line with the 2014 scope on a modern stack. These are the
things a *2026-native* build might also carry that we've deliberately parked:

- **API / mobile app.** Building server-rendered Django (modern + maintainable).
  DRF is parked until a real consumer appears. If the Association's idea of "up
  to date" includes a mobile app or PWA, that's a scope conversation not yet had
  — a Phase 9, not an omission.
- **Analytics / leadership dashboard.** The system *captures* rich data
  (payments, scans, engagement) but has no reporting layer for leadership —
  member counts by tier, renewal rate, quarterly revenue. The 2014 doc gestured
  at "multi-dimensional data for decision-making"; revisit once data exists to
  report on.
- **Operational maturity:** CI/CD pipeline, error monitoring/observability,
  accessibility (WCAG) + i18n. Touched only glancingly (0.6 test suite +
  container). A 2026 "done" usually treats these as first-class — worth
  elevating when the build stabilizes.

**Also pending — not technical, but blocking "done":** Association must ratify
the open *policy* items before those features are truly complete — final tier
benefit values (1.6), retention rule + soft-delete-vs-erasure reconciliation
(cross-cutting/DPA), Honorary + Corporate specifics. The plan can't make these
calls; they're the Association's.
