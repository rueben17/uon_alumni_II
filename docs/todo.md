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

> **Rewritten 2026-08-05 for the greenfield rebuild.** Phase 0 is no longer a
> migration over live data — it is a fresh schema on a **new Neon database**.
> The pre-rebuild version of this file is archived at
> `docs/todo-pre-rebuild-2026-08-05.md`. Model definitions live in
> `docs/rebuild-schema.md`; the reasoning behind them in
> `docs/0.1-identity-decisions.md`.

Rings, innermost first:
- **Phase 0** — Identity foundation (who the person is)
- **Phase 1** — Member core (register → dashboard → manage membership; manual activation)
- **Phase 2** — Payments (attach to the core; automate what was manual)
- **Phase 3+** — Comms, events, donations, commerce, QR credential, integrations

---

## Guiding decisions (settled — don't relitigate mid-build)

- **`User` is the auth record, and nothing else.** Login handles, their
  verification flags, credential provenance, Django's authorization. No person
  data. Anything Google hands over at login is person data that merely *arrived*
  via auth.
- **No field lives in two places.** The governing rule of the rebuild. Shared
  person data lives once on `UserProfile` (O2O to `User`, `primary_key=True`, in
  `apps/user/`). Role models (`Employee`, `Student`, `AlumniProfile`) hold only
  what is true of that role.
- **Identity anchor = `User.pk`, a real UUID.** The fresh DB makes this literally
  true rather than approximated — no `public_id` workaround. Stable across
  student → alumnus → staff, never a login handle, never changes.
- **Phone is the mandatory primary login handle — and it lives on `User`.**
  Required, verified, unique. It is a *handle*, so it sits beside `email`, with
  `phone_verified` beside `email_verified`. Load-bearing for M-Pesa later, so it
  exists regardless of comms preference. `UserProfile.alt_phone` is contact data.
- **Email is secondary / future, and multi-handle capability already exists.**
  `allauth.account.models.EmailAddress` gives multiple verified emails per User
  out of the box. **Do not build a second email model** — the future
  `@alumni.uonbi.ac.ke` address slots in with no schema change.
- **Access-through, no delegation properties.** Write call-sites in final form
  (`alumni.user.profile.national_id`).
- **Phone stored as E.164 with the `+`** (`+254712345678`) via
  `django-phonenumber-field`. Transform at each boundary, never at storage.
- **One shared normalize function** — `apps/user/phone.py`. Both the model and
  the auth backend import it, so registration and login produce byte-identical
  strings. Never reimplemented. *(Built — see 0.2.)*
- **Membership is its own model on `User`**, not fields on `AlumniProfile`. FK
  not O2O, so history accumulates. This is what lets a *student* hold the free
  tier before they have an alumni record at all.
- **Transactional vs. consent split:** OTP + receipts ride the phone *always*
  (security/identity). `sms_opt_in` gates only *marketing* comms.
- **Tiers + benefits are admin-managed data, not hardcoded.** `MembershipTier`
  has related `Benefit`/`Entitlement` rows, edited via **inline forms in the
  main Django admin** so the Association changes "what Gold gives" without a
  deploy. The system owns the *mapping*; the Association owns the *values*.

---

## Cross-cutting (applies to EVERY phase — not a phase you finish)

These span the whole build. Stated once here; each phase honors them.

- **Data Protection Act 2019 (Kenya) — legal, non-optional.** Holding national
  IDs, phones, DOBs for tens of thousands of people.
  - Consent fields exist on `UserProfile` **from the first migration** — one
    thing the rebuild gets for free that a retrofit could not.
  - Consent capture at **registration** (Phase 1) — explicit, purpose-stated.
  - Directory listing is **opt-in, private by default** (see 1.7). Publishing
    by consent, never open search of member data.
  - Scan-log movement data (QR) is personal data — must be in the privacy notice
    with a stated purpose + retention limit.
  - Retention rule + the **soft-delete vs. right-to-erasure** tension: an
    `is_active=False` soft delete keeps data forever, which can conflict with an
    erasure request. Decide the reconciliation. **Still open.**
- **Backups / DR.** Data lives on **UoN servers**; the DB is Neon. A backup +
  restore method must be provided and owned. Live payment + PII data; "who
  restores this and how" needs an answer, not an assumption.
- **Secrets in `.env`** — M-Pesa (Daraja sandbox vs prod keys differ), Stripe,
  SMS/email provider creds. Never in the repo.
- **Rate limiting — a must.** Public endpoints (registration, and especially the
  **OTP-send endpoint — every send is an SMS you pay for**) need throttling.
  Abuse *and* cost protection.

---

## PHASE 0 — Identity foundation (greenfield)

### 0.1 Decide + document — **DONE 2026-08-05**
Output: `docs/0.1-identity-decisions.md` (field map, tier taxonomy, seven
numbered decisions) and `docs/rebuild-schema.md` (the models themselves).
- [x] `UserProfile` lives in `apps/user/` alongside `User`.
- [x] Final field map written down, including which of the four overlapping
      honorific vocabularies wins.
- [x] Student→alumnus lifecycle designed: a `Student` role on the same User;
      at graduation the *same* User gains an `AlumniProfile`, the student row
      stays as history, and the free student `Membership` upgrades in place.
      Additive, never a record migration.
- [x] Tier taxonomy set, and reconciled against what is actually seeded
      (Platinum/Diamond exist in data but not in the brochure; Honorary and
      Corporate are accidentally lifetime because `duration_months=0`).

### 0.2 Phone infrastructure — **mostly done**
- [x] `django-phonenumber-field[phonenumbers]` installed, pinned in
      `requirements.txt`, `phonenumber_field` in `INSTALLED_APPS`.
- [x] `PHONENUMBER_DEFAULT_REGION` / `_FORMAT` pinned explicitly in settings, so
      the stored format cannot drift via a settings change.
- [x] **Shared normalize function** — `apps/user/phone.py`: `normalize_phone()`
      plus `try_normalize_phone()` (lenient wrapper for the 0.4 auth backend's
      lookup path). 11 tests in `apps/user/tests.py`, passing.
- [x] Use `PhoneNumberField(region="KE", unique=True)` on `User.phone` when the
      model is written in 0.3. *(No hand-rolled regex is being replaced any
      more — the fresh schema simply never has one.)*
- [ ] Enforce normalization in `User.save()` itself. **Mitigated, not closed:**
      every form path that sets `user.phone` (`CompleteProfileForm`,
      `AlumniProfileForm`) calls `normalize_phone()` in `clean_<field>()`
      before assignment, so the two real entry points are covered — but
      there's still no floor at the model layer for any future call site
      that sets `user.phone` directly.

### 0.3 Write the schema fresh + stand up the new DB — **DONE 2026-08-06**
Replaces the old five-step migration entirely. Definitions: `docs/rebuild-schema.md`.

- [x] **BLOCKING FIRST STEP — inspect the production Neon database.** Resolved
      by conversation, not a query: `.env`'s `DATABASE_URL` was confirmed to
      already point at a *new*, empty Neon database, not the populated
      production one — so there was nothing to discard.
- [x] Write the models: `User`, `UserProfile` (`apps/user/`), `Employee`
      (`apps/staff/`), `Student` (`apps/student/`), `AlumniProfile` +
      `Membership` + `MembershipTier` (`apps/home/`).
- [x] `MembershipTier` fixes while the schema is being written:
      added `student` to `TIER_TYPES`; added `ladder_rank` for the monotonic
      upgrade path (seeded Annual=1→Corporate=5). Honorary/Corporate's
      `duration_months=0` accidental-lifetime bug fixed in the *seed data*
      (`seed_membership_tiers`), not the model — see 0.3's still-open
      `get_expiry_date()` item below, which is the model-level version of
      the same class of bug.
- [ ] Fix `MembershipTier.get_expiry_date()` — it uses
      `timedelta(days=months * 30)`, so a 12-month membership expires after 360
      days and drifts ~5 days earlier every renewal. Use `relativedelta`.
      **Deliberately deferred to 1.3** — not urgent while activation is
      manual, wrong the moment renewals automate.
- [x] One `Honorific` TextChoices in `apps/user/` replaces all four existing
      title vocabularies (`AlumniProfile.TITLE_CHOICES`,
      `Employee.HonorificChoices`, and the `TITLE` tuples on `home.Executive`
      and `home.Secretariat`).
- [x] **Destructive:** every existing migration directory deleted and
      regenerated fresh per app; `DATABASE_URL` repointed at the new Neon DB
      (local `db.sqlite3` backed up alongside, not deleted). No orphaned
      media — the new DB started with zero rows, so there was nothing for
      `media/employee_photos/`/`media/qr_codes/` to orphan *from*.
- [x] Re-seed: `seed_qualifications`, `seed_university_structure` (Position/
      Department/ServiceUnit/ResearchUnit), and `seed_membership_tiers` — all
      run against local sqlite *and* Neon, counts confirmed matching (11
      faculties, 62 departments, 29 service units, 18 research units, 24
      positions, 273 qualifications, 9 tiers). Fixed two bugs found in the
      process: a Windows cp1252 console crash in `seed_university_structure`
      (a `✓` character isn't valid in that codec), and the Honorary/
      Corporate/Student seed-data issues noted above.
- [ ] Create the first superuser on the new DB. **Still open** — only
      throwaway test superusers were created (and deleted) for smoke-testing
      tonight; no real admin account exists on the new DB yet.
- [x] `AutoSlugField` wrinkle: `populate_from` points at
      `self.user.profile.full_name` (or `.display_name`/`.given_name`+
      `.family_name` per call site) on every role model now.

#### 0.3b Content models — write them in the same pass — **DONE 2026-08-06**
The `apps/home` content layer lands on the same fresh DB, so these schema
changes cost **nothing now** and cost a migration each later. The *views* for
all of this are a parallel workstream (see "Content site" below) — only the
models belong here. (Views/routes for most of it got built too, same night —
see C.1/C.5 below; this section tracks the schema only.)

- [x] `Article`: added `type` (`page` / `news` / `feature` / `notice`) and
      `page_key` (choices, `unique=True, null=True`). Fetched by `page_key` in
      the new generic `standing_page` view, never by slug.
- [x] Moved `workshop` / `conference` / `forum` / `training` **off**
      `ARTICLE_TYPE_CHOICES` and onto `Event.event_type` (alongside the
      existing `walk` usage).
- [x] `Article`: added `is_published` + `published_at` (stamped once, on
      first publish, in `save()` — never overwritten on later edits).
- [x] `Article`: dropped `thumbnail_url`.
- [x] New **`Publication`** — newsletters, committee minutes, annual reports,
      policies, financial statements, forms. `visibility=members` gate built;
      `file` uses `RawMediaCloudinaryStorage` explicitly (confirmed that class
      already exists in the installed `cloudinary_storage` package — nothing
      to write). Public-facing Downloads/News-Letters list view built (C.5).
- [x] New **`InMemoriam`** — person registry, reuses `apps.user.models.Honorific`
      rather than a fifth title vocabulary.
- [x] New **`JobPosting`** — model + public Careers list view built (C.7).
      Moderation (`is_approved`) and expiry exist; **membership gating on the
      view does not** — flagged in the view's own docstring, not silently
      decided.
- [x] **Slug link rot fixed.** `Article`/`Event`/`Chapter` now
      `always_update=False`; `django.contrib.redirects` installed
      (`INSTALLED_APPS` + `RedirectFallbackMiddleware`, last in the chain).
- [x] Consolidated the six `get_thumbnail`/`make_thumbnail`/`get_avatar`/
      `make_avatar` implementations into one `ThumbnailMixin` (~80 dead lines
      removed — `make_thumbnail` was genuinely unreachable in every copy).
      Placeholder typo fixed (`240x240x.jpg` → `240x240.jpg`).
- [x] **Did not fold singular images into `Images`** — the decision stands,
      documented in `Images`' own docstring. Extended it with `publication`/
      `in_memoriam` FKs instead (same one-FK-per-model pattern), not a
      generic FK.

### 0.4 Auth: phone-as-login
- [ ] Custom auth backend resolving a submitted phone (via
      `try_normalize_phone`) → User. Email stays usable too.
- [ ] OTP verification for phone (Africa's Talking or chosen provider). This is
      *transactional* SMS — foundational, not the later marketing build.
      Sets `User.phone_verified`.
- [ ] **Identifier-change flow:** new SIM → login handle *and* (future) M-Pesa
      key both move. Deliberate "change verified identifier" flow, which must
      clear `phone_verified` until the new number is confirmed.
- [ ] Multiple verified emails per User — **already provided by allauth's
      `EmailAddress`**. Confirm it is wired, don't build it.

### 0.5 Rewrite every call-site against the new shape — **DONE 2026-08-06**
Bigger than the old "chase a rename" — the models change shape, not just names.
This is where a half-finished rebuild bites silently.
- [x] **`apps/user/adapter.py` — the big one.** Old per-login sync block
      deleted. New `_ensure_profile(user, extra_data=None)` helper get-or-creates
      `UserProfile` and syncs from Google `extra_data` only when passed;
      `_ensure_employee()` calls it first, then ensures the `Employee` row.
- [x] `save_user()` repointed to write onto the profile, `hd` dropped (already
      on `SocialAccount.extra_data` if ever needed).
- [x] Dropped `User.is_admin`.
- [x] `User.get_full_name()` / `get_short_name()` → profile lookups w/ email
      fallback.
- [x] Forms rewritten: `AlumniProfileForm`/`AlumniRegistrationForm`/
      `MembershipUpdateForm`/`CompleteProfileForm` all split across
      `user.profile.*`/`user.*`/role-model fields, per the "access-through, no
      delegation properties" rule.
- [x] CBVs in `apps/home/views.py` and `apps/staff/views.py` rewritten;
      `_get_or_create_staff_employee` now just delegates to the adapter's
      `_ensure_employee` instead of duplicating the sync.
- [x] Both admin registrations (`apps/staff/admin.py`, `apps/home/admin.py`,
      incl. `qr_manager/admin.py`) repointed. `membership_admin_site` didn't
      exist as a separate scoped site — `MembershipAdmin` registered on the
      main admin.
- [x] Templates: every stale field reference found via smoke-testing (not just
      `manage.py check`, which stays silent on missing template attrs) fixed
      — alumni-side and, separately, a whole staff-side pass (`complete_profile`,
      `profile_update`, `staff_header`, `staff_detail*`, `profile_delete_confirm`)
      that had never been audited before.

### 0.6 Foundational hygiene
- [ ] Audit trail (`django-simple-history`) while the schema is small — who
      changed what, old → new. (2014 doc promised it; doesn't exist yet.)
- [ ] Extend the test suite past `apps/user/phone.py`: the auth backend, profile
      creation, and role resolution (`User.roles`).
- [ ] Containerized deploy if not already.
- [ ] Fix `download_staff_qr_code` in `apps/staff/views.py`: it reads
      `employee.qr_code_image.path`, which raises on Cloudinary storage. The PNG
      branch beside it already does the portable `.open()`/`.read()`.

---

## PHASE 1 — Member core (register → dashboard → manage membership)

The innermost functional ring. Works end-to-end with **no payment gateway** —
activation is manual (Secretariat), exactly as today's `PaymentAdmin.mark_completed`.
This is the loop that must be demonstrable before payments exist.

### 1.1 Self-registration
- [ ] Self-service signup → creates `User` + `UserProfile` + `AlumniProfile`.
      Registration does NOT activate membership (unchanged rule).
- [ ] Phone required + verified at signup (rides 0.4's OTP).
- [ ] **BLOCKER — the privacy notice must exist before this ships.** There is no
      privacy policy page on the site today, and `UserProfile.privacy_notice_version`
      presupposes a versioned one to point at. Consent under the DPA 2019 must be
      consent to a *stated purpose*; it cannot be captured against a document
      that does not exist. It must disclose the QR scan-log purpose and retention
      limit (cross-cutting). This is the **only** item from the content
      workstream that sits on the AIMS critical path — everything else there is
      genuinely parallel.
- [ ] Consent captured explicitly at this point, writing
      `consent_given_at` + `privacy_notice_version`.

### 1.2 Member dashboard (your own)
- [ ] Self-resolved from `request.user` (no pk in URL).
- [ ] Shows: profile, current `Membership` (status, tier, expiry), issued-item
      flags, payment/renewal history.
- [ ] Self-service profile edit — split correctly between `UserProfile` fields
      and `AlumniProfile` fields.

### 1.3 Membership management + the one door
- [ ] **Service layer first:** `renew_membership()`, `upgrade_to_lifetime()`,
      `assign_membership_tier()` become functions operating on `Membership`
      rows, not methods mutating `AlumniProfile` in place. *Every* caller
      (admin now, payment callback later, scheduled jobs) goes through one door.
      Build this here — it is what keeps Phase 2 from fragmenting state changes.
- [ ] Member-initiated **renewal** request → pending `Membership`.
- [ ] Member-initiated **upgrade** (incl. to lifetime) request → pending.
- [ ] Expiry / validity tracking surfaced on the dashboard.
- [ ] Secretariat **manual approval** in scoped admin calls the service layer to
      activate / stamp membership number.

### 1.4 Status visibility
- [ ] Member sees pending vs. active vs. expired clearly.
- [ ] Renewal/upgrade history visible to member and Secretariat — now genuinely
      possible, since history is rows rather than overwritten fields.

### 1.5 Registration fields — finalize against the 2024 form
- [ ] Fields are the Association's membership form, split by the new rule:
      **`UserProfile`** — title, first/middle/surname, gender, national
      ID/passport, DOB, postal + physical address, phone (on `User`), email.
      **`AlumniProfile`** — graduation place, name-at-graduation, degree,
      faculty, employment, position.
- [ ] **Graduation year = the FIRST degree's year** — that's when the person
      officially became an alumnus/alumna. `graduation_year` stays
      **single-valued** and means "date of alumnus status," not "any
      graduation." Later degrees are additional qualifications, not a second
      entry into the alumni body.
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
- [ ] Then build on researched references (proposed — for Association approval):
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
        recognition, bulk engagement. Org-shaped, not person-shaped — and
        `Membership` hangs off a `User`, so the multi-rep shape needs a decision.
      - *Student (pipeline):* **free/nominal.** Draw = access to *alumni*, not
        campus resources students already have. Alumni **mentorship**,
        networking nights, internship/job access, career workshops,
        student-ambassador roles, event + merch discounts, and a **graduation
        conversion incentive**. This is the front of the funnel the identity
        model was built for.

### 1.7 Directory — opt-in, private by default (DPA)
- [ ] Per-member **visibility toggle** on `AlumniProfile` (`private` default;
      "visible" / "members-only" / "private" for granularity). Nobody exposed
      until they affirmatively choose.
- [ ] Public directory shows only opted-in members, only the fields they agreed
      to expose (name yes; national ID never; phone optional).
- [ ] **No open search of member data** — a member may *appear* by choice, but
      the system does not let others query/lookup records.

### 1.8 Spreadsheet export/import
- [ ] `django-import-export` in admin — solves the Secretariat's "give me a
      spreadsheet of paid members" on day one, plus bulk import.

---

## PHASE 2 — Payments (attach to the member core; automate the manual step)

Goal: flip Phase 1's manual approval from *the* path into an *exception* queue.
Everything here plugs into the 1.3 service layer — payments become just another
caller of the same door.

### 2.1 M-Pesa (Daraja)
- [ ] STK push for registration + renewal.
- [ ] C2B + callback handling for reconciliation. **Record the Payment
      explicitly in the webhook view — NOT via a signal** (preserves the
      "state changes are explicit" property; a signal would only hide the flow
      and make retries harder to guard).
      - Persist the provider's transaction ID (`MpesaReceiptNumber`) at callback
        time, independent of end-of-month statements.
      - `provider_txn_id` field with **`unique=True`** — this DB constraint is
        the real idempotency guarantee, not `get_or_create` alone.
      - Store the **raw payload verbatim** in a JSON field alongside parsed
        fields — the audit blob statements can't give you.
      - Pattern: `get_or_create(provider_txn_id=...)` → act only if `created` →
        call the 1.3 service layer → always return 200 so retries stop.
- [ ] Daraja boundary strips the `+`: `str(user.phone).lstrip("+")` →
      `254712345678`. Storage stays E.164; only this call site strips.
      (`normalize_phone` already accepts the bare `254...` form on the way back
      in, so callbacks need no special handling.)

### 2.2 Card payments — Stripe
- [ ] Stripe for Visa/Mastercard card processing (international donors).
- [ ] Same webhook pattern as 2.1, keyed on the Stripe
      `PaymentIntent`/charge `id` as the unique `provider_txn_id`; verify the
      webhook signature; store the raw event; idempotent via the constraint.

### 2.3 Reconciliation + the human's new role
- [ ] Auto-reconciliation → activates membership via the **1.3 service layer**.
      Successful match = no human touch.
- [ ] **Exception queue:** only unmatched/ambiguous payments reach Secretariat.
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
- [ ] **Excess-payment refund** method. Distinguish from a full reversal: an
      *excess* refund does NOT deactivate membership (they still paid enough);
      a *full* reversal might. Refund/reversal webhooks record via the same
      explicit pattern as 2.1.
- [ ] **Installment upgrades** toward the next ladder rung: a payment can be
      *partial toward a target*. Accumulate amount-paid-toward-tier on the
      `Membership`; upgrade via the service layer only when cumulative payments
      clear the next rung's `ladder_rank` price.

---

## CONTENT SITE — parallel workstream (`apps/home`, not on the AIMS path)

Runs alongside Phase 0→2 and blocks none of it. The **models** are in 0.3b above
(free while the schema is being written); everything here is views, routes and
features. It matters because it is what the Association and the University
actually *see* — but it must not consume the time self-service needs.

### C.1 Fix what is already broken — **DONE 2026-08-06**
- [x] **Three `get_absolute_url()` methods reverse URL names that do not exist**
      — `Article`, `Event`, `Chapter`. Routes + list/detail views added
      (`article_list`/`article_detail`, `walk_list`/`walk_detail`,
      `chapter_list`/`chapter_detail`).
- [x] `uon_alumni_gallery` now queries `Images` (was a static template).
- [x] `uon_alumni_contact_us` now backed by a real `ContactForm`/`ContactMessage`
      model, with best-effort `send_mail` notification.

### C.2 Standing pages off `Article.page_key`
- [x] Generic `standing_page(request, page_key)` view + `page/<slug:page_key>/`
      route built, replacing the hardcoded-render approach. **Not yet done:**
      migrating the six existing hardcoded pages (`history`, `donate`,
      `scholarship`, `contact`, etc.) onto it — the mechanism exists, the
      content migration doesn't.
- [ ] **Privacy notice + terms of use pages.** `PageKey.TERMS`/`PageKey.PRIVACY`
      exist on `Article` now (added while the model was open), but no `Article`
      rows have been created for them yet. See the 1.1 blocker — legally
      required, and the only content item on the critical path.

### C.3 Editor experience (highest leverage, all small)
- [ ] **Rich text editing.** Every content model has `body = TextField()`, so the
      Association cannot add a heading, a link, or an inline image. Everything
      else here is decoration until this exists.
- [ ] Draft / publish / schedule (rides `is_published` + `published_at` from 0.3b).
- [ ] **Editorial permissions via Django Groups** — a content editor should
      publish articles without holding admin over members, payments and PII.
      Today there is one admin tier over everything.

### C.4 Findability and sharing
- [ ] **SEO + Open Graph meta.** Alumni share links on WhatsApp; without
      `og:title`/`og:image` they render as bare URLs. `Article.thumbnail`
      already exists — it just is not in a meta tag.
- [ ] Site search. Neon is Postgres, so `SearchVector`/`SearchRank` gives real
      full-text search across articles, publications and events with no extra
      infrastructure.
- [ ] Pagination on every list view.
- [ ] RSS feed + `sitemap.xml` — Django ships both (`contrib.syndication`,
      `contrib.sitemaps`). Near-free.
- [ ] Tags / related content for cross-linking.
- [ ] Branded 404 / 500 pages.
- [ ] Structured data (schema.org `Article`, `Event`).

### C.5 Content areas already modelled but unrouted
- [x] **Chapters.** List/detail views + templates built, wired into nav/footer.
- [x] **Partners.** List view + template built (`uon_alumni_partners`), wired
      into nav/footer. **Not yet done:** the actual members-only gating logic
      on partner offers — the page exists and is public, the 20%-discount
      benefit gate the brochure promises isn't wired to `Membership` yet.
- [x] Publication library UI (`publication_list.html`). **Not yet done:** the
      `_is_mobile_request` inline-viewer-vs-download split from
      `apps/staff/views.py:25` — publications currently just link straight to
      the file for both desktop and mobile.

### C.6 Engagement
- [ ] Alumni spotlights (an `Article` type — consistently the most-read content
      on association sites).
- [ ] Class notes / alumni updates — member-submitted, Secretariat-moderated.
- [ ] Obituary submission feeding `InMemoriam`, rather than transcription.
- [ ] Newsletter signup for non-members — email capture feeding Phase 3, the top
      of the funnel above student membership.
- [ ] Analytics. Phase 3 comms will want to know what people actually read, and
      the Association will want evidence the site works.

### C.7 Promised in 1.6 but undeliverable today — decide: build or stop advertising
- [x] Job board (`JobPosting`, model in 0.3b) — public `job_posting_list.html`
      list view + Careers nav link built. **Not yet done:** membership gating
      on the view (currently public, not members-only as the tier brochure
      implies) — flagged in the view's own docstring.
- [ ] Mentorship matching — also promised; realistically Phase 4+.
- [ ] Distinguished Leadership Awards — nominations + past winners.
- [ ] Chancellor-ranking participation — brochure benefit, unimplemented anywhere.

---

## Later phases (direction only — detail when we reach them)

- **Phase 3 — Communications:** consent-gated bulk SMS + email, templated
  renewal reminders + expiry notices off `Membership.expires_on`, scheduled jobs.
  - `Communication`/`Campaign` model: subject, body, type, channel, audience
    filter, scheduled-send time, status.
  - Per-recipient **send log** (who, when, delivered/failed) — audit + prevents
    double-sends.
  - Audience filter respects `sms_opt_in`/`email_opt_in`. This consent-gated
    marketing path stays **separate from the always-send transactional path**
    (OTP, receipts) — same infra underneath, different governance on top.
- **Phase 4 — Events:** post an event, members RSVP, reminders ride Phase 3.
  Social *login + share*, NOT a rebuilt social network.
- **Phase 5 — Donations:** online giving on the Phase 2 rails. A donation is
  just a Payment with no membership to activate.
- **Phase 6 — Commerce:** UNES merchandise store on Phase 2 payments. Lowest
  priority; small lift once payments exist. Can jump the queue if the bookstore
  pushes.
- **Phase 7 — QR membership credential:**
  - QR issued to **all members**, resolving to a **public benefit page** showing
    member category + tier entitlements — nothing sensitive; it's a credential,
    not a profile. Consumes the 1.6 tier→benefit mapping.
  - QR encodes an **opaque token**, not the membership number. The existing
    `QRCode` model already does this (`/qr/<uuid>/?t=<token>`) and is the
    pattern to follow.
  - The **physical/branded card + 20% retail discount is a Life-member benefit**
    (per brochure), distinct from the QR page everyone gets. Two things, one
    word "card" — keep them separate in the model.
  - **Scan log — LAST, separable add-on.** The benefit page verifies by
    *display*, so logging is optional to the core feature. Movement data ⇒
    **DPA notice + retention** (cross-cutting).
- **Phase 8 — University integrations:** SMIS first (auto-populate alumni from
  graduation records — where a real API/ETL layer earns its place), then HRMIS
  (staff-alumnus / payroll check-off), Library (SSO / borrowing).

### Parallel workstreams (not in the phase sequence)
- **Content site (`apps/home`):** see the "Content site" section above. Models in
  0.3b, everything else parallel. `content_todo.txt` holds the separate
  copywriting / data-entry audit — that is authoring work, not dev work.
- **Booklet digitization 1956–2008:** scan → OCR/structure → load into schema.
  Independent; can grind alongside from Phase 0 onward.
- **DRF / API layer:** resist until Phase 8 or the first real consumer (SMIS ETL,
  mobile app, decoupled portal). Premature before something needs it.
- **Campus network access:** `uonalumni.or.ke` is blocked on the UoN network by
  FortiGate SSL deep inspection (attestia.co.ke on the same IP is not
  inspected). ICT applied an exemption 2026-08-05; propagation pending.
  Origin nginx is confirmed clean — do not "fix" the certificate chain.

---

## Explicitly out of current scope (conscious deferrals — revisit, not forgotten)

- **API / mobile app.** Building server-rendered Django (modern + maintainable).
  DRF is parked until a real consumer appears. If the Association's idea of "up
  to date" includes a mobile app or PWA, that's a scope conversation not yet had.
- **Analytics / leadership dashboard.** The system *captures* rich data but has
  no reporting layer — member counts by tier, renewal rate, quarterly revenue.
  Revisit once data exists to report on.
- **Operational maturity:** CI/CD pipeline, error monitoring/observability,
  accessibility (WCAG) + i18n. Touched only glancingly (0.6). Worth elevating
  when the build stabilizes.
- **Staff-subdomain nav (`templates/snippets/navbar.html`'s `staff` branch).**
  "Teaching & Research," "HR & Payroll," and "Administration" — Payslips, Leave
  Application, Course Management, Procurement, IT Support, etc. — have zero
  backing models or views anywhere in the codebase. Reads like leftover
  scaffolding from a generic university-portal starter template, not
  actual AIMS scope (todo.md's Phase 8 is the real staff-facing work: HRMIS/
  payroll *integration*, not a payroll system built here). **Decided
  2026-08-06: leave unwired.** Core focus is alumni onboarding + self-service;
  staff is internal and can wait. Revisit only if the Association explicitly
  asks for a staff portal, not as a byproduct of wiring the main site's nav.
- **Site-wide background image (visual polish).** Tried a fixed, cover-sized
  Cloudinary photo on `<body>` in `base.html` (shows through via template
  inheritance on every page) plus a transparent navbar, to cut down on how
  much flat white space the site reads as. Verified working live via a
  scrolled-viewport screenshot. **Parked, not merged** — sits on its own
  branch `aesthetic/site-background-image`, reverted out of
  `feature/google-auth-qr-redirect` 2026-08-06. Purely cosmetic; revisit once
  core functionality (Phase 0.4/1) is further along, and check text
  legibility against the photo (some sections have no card behind their
  copy) before shipping it.

**Also pending — not technical, but blocking "done":** the Association must
ratify the open *policy* items — final tier benefit values (1.6), Platinum and
Diamond's place in the ladder, Honorary + Corporate billing periods, Corporate's
multi-rep shape, re-consent comms for the opt-in flip, and the retention rule +
soft-delete-vs-erasure reconciliation. The plan can't make these calls.
