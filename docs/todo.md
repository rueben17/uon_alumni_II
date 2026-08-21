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
- **Backups / DR.** Data lives on **UoN servers**. **Decided 2026-08-10:
  the DB is moving off Neon onto the VPS itself** (not staying on Neon
  long-term) — sequenced deliberately **last**, after the rest of the
  pending build work below, as its own dedicated migration. A backup +
  restore method must be provided and owned regardless of where it ends up
  hosted. Live payment + PII data; "who restores this and how" needs an
  answer, not an assumption.
  **Incident, 2026-08-10:** the 2026-08-06 Faculty/Department app move
  (staff → home) was reconciled on local sqlite that night but never on
  Neon — its `django_migrations` table kept recording `home`/`staff`
  migration names as applied while Neon's actual live schema still had
  `staff_faculty`/`staff_department` (the pre-move tables), because
  Django tracks "applied" by migration name, not by a file's current
  content. Surfaced tonight when deploy.yml's `migrate` step hit
  `home.0007_...` and failed with `relation "home_faculty" does not
  exist`. Fixed directly against Neon (read-only-verified first: `SELECT
  COUNT(*)` confirmed zero rows in `user_user`/`home_alumniprofile`/
  `staff_employee`/`home_membership`/`home_payment` and the FK dependency
  graph via `information_schema` confirmed a rename would resolve every
  affected table) via `ALTER TABLE staff_faculty RENAME TO home_faculty`
  / same for `department` — Postgres FKs track by object id, not name, so
  every dependent table's constraint followed the rename automatically,
  no data loss, no reseed needed. `migrate` then completed 0007→0017
  cleanly. **Lesson:** any future migration-graph restructuring (renaming
  a table, moving a model between apps) needs the SAME reconciliation
  applied to every real environment, not just the one being tested in at
  the time — this is exactly the kind of gap the Neon→VPS move (above)
  should get a real deploy/migration checklist for.
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
- [x] **Enforce normalization in `User.save()` itself — DONE 2026-08-10.**
      `User.save()` now calls `normalize_phone()` on `self.phone` (skipping
      blank/unset) before every save, as a floor beneath the two form-level
      call sites -- closes the gap for any future direct
      `user.phone = ...; user.save()`. Verified: `'0712345678'` saves as
      `'+254712345678'`; a blank phone round-trips untouched; full
      `apps.user` test suite (11 tests) still green.

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
- [x] **Fix `MembershipTier.get_expiry_date()` — DONE 2026-08-10.** Swapped
      `timedelta(days=months * 30)` for `dateutil.relativedelta` (new
      dependency, `python-dateutil` added to `requirements.txt`) — a
      12-month membership now expires on the true calendar anniversary
      instead of drifting ~5-6 days earlier every renewal. Verified against
      a leap-day join (2024-02-29 → 2025-02-28, not a raw day-count crash)
      and an ordinary date (2025-03-15 → exactly 2026-03-15); Life tiers
      still return `None`. Landed ahead of 1.3 rather than bundled with it,
      per explicit instruction.
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
- [x] **[FIXED 2026-08-13]** `download_staff_qr_code` in `apps/staff/views.py`
      read `employee.qr_code_image.path`, which raises on Cloudinary storage.
      Now uses the same portable `.open()`/`.read()` pattern the PNG branch
      beside it already did, passed to reportlab's `Image`/`LinkedImage` as a
      `BytesIO` instead of a path string (reportlab accepts both). No
      Employee record exists locally to test the view end-to-end, so verified
      the underlying assumption directly instead: built a real QR PNG,
      constructed `RLImage` from a `BytesIO` of it, and rendered a full PDF —
      confirmed reportlab handles the file-like object correctly.

---

## PHASE 1 — Member core (register → dashboard → manage membership)

The innermost functional ring. Works end-to-end with **no payment gateway** —
activation is manual (Secretariat), exactly as today's `PaymentAdmin.mark_completed`.
This is the loop that must be demonstrable before payments exist.

### 1.1 Self-registration — mostly done, phone/OTP intentionally on hold
- [x] Self-service signup → creates `User` + `UserProfile` + `AlumniProfile`
      (`AlumniRegisterView`). Registration does not activate membership.
- [ ] Phone required + verified at signup (rides 0.4's OTP). **On hold
      2026-08-07 — deliberate, not forgotten:** OTP means a paid SMS gateway,
      and that cost conversation hasn't happened with the Association yet.
      Revisit once 0.4 itself is prioritized.
- [x] **BLOCKER resolved 2026-08-07.** `Article` rows seeded for Privacy
      Policy and Cookie Policy (`seed_legal_pages` management command,
      DPA-2019-aligned draft — covers the QR scan-log purpose/retention
      limit as required, but is NOT lawyer-reviewed; Association should have
      it checked before treating it as final). Footer links + a cookie
      consent banner (Alpine, `base.html`) ship too.
- [x] Consent captured explicitly at registration — `privacy_consent`
      checkbox gates form submission, `AlumniRegisterView.form_valid()`
      stamps `consent_given_at` + `privacy_notice_version` (from the new
      shared `apps.user.models.CURRENT_PRIVACY_NOTICE_VERSION` constant, so
      the recorded version can never drift from the actual policy text).
- [x] **[2026-08-20] "Update Your Details" / claim-your-imported-profile flow
      — shipped (email channel).** For alumni already in the DB from the
      legacy spreadsheet import whose Google-login email doesn't match
      anything on file (`SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT`
      only auto-matches when it does). `ProfileClaimVerification`
      (`apps/home/models.py`) + `ProfileClaimSearchView`/`VerifyView`/
      `ContinueView` (`apps/home/views.py`, routes under
      `uon-alumni-claim-profile/`) → email OTP → verified session flag →
      `_connect_verified_claim()` in `apps/user/adapter.py`'s
      `pre_social_login()` links the Google identity to the existing
      imported `User` instead of creating a duplicate. Discovery link on
      both login templates ("Don't remember which email you used?").
      Satisfies the OTP-send throttling requirement above (DB-backed:
      8 searches / 15 min per IP, 5 wrong-code attempts per claim) for the
      email channel; `channel=phone` exists on the model but isn't wired to
      a sender yet. Homepage hero's "Update Your Details" CTA still needs
      pointing at `home:uon_alumni_claim_search` (currently `#`).

### 1.2 Member dashboard (your own) — DONE, already built earlier this session
- [x] Self-resolved from `request.user` (no pk in URL) — `AlumniProfileDetailView`
      via `url_my_profile`, `AlumniProfileUpdateView`/`AlumniMembershipUpdateView`.
- [x] Shows: profile, current `Membership` (status, tier, expiry) via the
      `current_membership` context var, payment history via `alumni.payments`.
- [x] Self-service profile edit, split UserProfile/AlumniProfile per the
      access-through rule. "Real-time" in the sense the alumni self-service
      loop (register/renew/upgrade/edit) needs no staff involvement to
      *submit* — activation of a tier change still needs Secretariat
      confirmation (`PaymentAdmin.mark_completed`), which is the deliberate
      manual-approval design from 1.3/2.3, not a gap.

### 1.3 Membership management + the one door
- [x] **Service layer — DONE 2026-08-10.** `apps/home/services.py`:
      `assign_membership_tier()` (general-purpose door — creates a pending
      `Membership` row), `renew_membership()` (same tier as current) and
      `upgrade_to_lifetime()` (must be a lifetime tier, raises otherwise)
      as narrower purpose-built wrappers around it, plus
      `activate_membership()`/`record_installment_payment()` — the
      activation-side door, replacing direct
      `Membership.activate()`/`.record_installment_payment()` calls.
      **Design decisions ratified 2026-08-08, built 2026-08-10:**
      - Renewal/upgrade request creates a **new pending `Membership` row** —
        confirmed already true of the existing views, now also true via
        the service layer for any future caller.
      - On activation, the prior ACTIVE row (if any) is explicitly flipped
        to **`Status.SUPERSEDED`** (migration `0013_alter_membership_status`)
        — distinct from `EXPIRED` (lapsed with nothing replacing it).
      - **`membership_number` carries forward** across renewals/upgrades.
        Hit a real schema blocker building this: the field was
        `unique=True`, which makes it *impossible* to save the same
        number on both the outgoing and incoming row even for an instant
        — replaced with a **conditional unique constraint** scoped to
        `status="active"` (migration
        `0014_alter_membership_membership_number_and_more`) so exactly one
        row per number may be live at a time, while history keeps its
        number on superseded rows too. Also had to fix the *ordering* —
        supersede the prior row BEFORE activating the new one (not after),
        since the constraint is checked per-statement and activating first
        would briefly leave two rows ACTIVE with the same number. Wrapped
        in `transaction.atomic()` so a reader never observes the gap.
      - Verified end-to-end (direct service calls, and through the real
        `PaymentAdmin.mark_completed()` action with a mock request):
        first activation gets a fresh number; a renewal supersedes the
        prior row and carries the number forward; an upgrade to a Life
        tier does the same (`is_lifetime=True`, `expires_on=None`); the
        installment path (`record_installment_payment()`) supersedes only
        on the first payment, not subsequent ones.
- [x] Member-initiated **renewal** request → pending `Membership` — already
      true of `AlumniMembershipUpdateView.post()`; now also routed through
      `services.assign_membership_tier()` instead of a bare
      `Membership.objects.create()`, same as `AlumniRegisterView`.
- [x] Member-initiated **upgrade** (incl. to lifetime) request → pending —
      same view/form handles this today (one tier dropdown covers both
      renewal and upgrade); `services.upgrade_to_lifetime()` exists as the
      purpose-built door for a future caller that wants to specifically
      mean "upgrade to Life," not a generic tier change.
- [ ] Expiry / validity tracking surfaced on the dashboard. **Not built
      tonight** — a UI/display task, separate from the service layer
      itself.
- [x] Secretariat **manual approval** in scoped admin calls the service layer
      to activate / stamp membership number — `PaymentAdmin.mark_completed()`
      rewired to call `services.activate_membership()`/
      `services.record_installment_payment()` instead of the model methods
      directly.

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
- [x] **`Benefit`/`TierBenefit` models — DONE 2026-08-10.** FK to the
      existing `MembershipTier` (not a new parallel model — a UX/UI spec
      initially proposed a standalone `Tier` model, which would have
      forked the tier concept in two; caught before building anything by
      checking existing models first). `TierBenefit` is the through model
      (`tier` + `benefit`, `unique_together`), `status` is
      included/excluded/not_applicable (never boolean — a cell can carry a
      qualifier like "2 vehicles" or "25% off" in `detail`). `Benefit.axis`
      is one of access/voice/economic/legacy per the spec's four-axis
      test ("every sellable item maps to one of these; anything that
      doesn't is marketing copy, not a benefit"). `TierBenefitInline`
      (`TabularInline`) on `MembershipTierAdmin`; `BenefitAdmin`
      filterable by axis. Verified on both admin sites `MembershipTier`
      is dual-registered on (`/2005/` and `membership_admin_site`).
      `billing_period`/`is_corporate` are **derived properties**, not
      stored fields — both fully determined by existing `fee`/
      `duration_months`/`tier_type`, and "no field lives in two places" is
      this rebuild's own governing rule.
- [x] **Seeded via data migration — DONE 2026-08-10**, all 25 benefits ×
      10 tiers (Honorary excluded — see below), spot-checked 10 cells
      against source. Two new `MembershipTier` rows added along the way
      (Association decision): **Registered** (KES 0, free — didn't exist
      before) and **Associate** (KES 3,000, annual — a new tier, NOT a
      rename of Honorary despite matching its price; Honorary stays a
      conferred distinction, Associate is purchased). Existing tiers'
      `order` shifted to fit; no other existing row touched.
      **Still open:** Honorary Member's own benefits were never specified
      by the source data (its tier list has no "Honorary" row at all) —
      needs the Association's input, not left as fabricated defaults.
      **Also surfaced, unresolved:** the seed data assumes Corporate
      Membership is billed `one_off` (paid once), but the existing
      `Corporate Membership` row has `duration_months=12` — this system
      already treats Corporate as a *recurring annual* fee (built into
      tonight's demo-data generator and the installment-eligibility
      logic already). Derived `billing_period` correctly reads back
      "annual" for Corporate right now, which contradicts the seed data's
      assumption. Not resolved either way — flagged for the Association,
      not silently picked.
- [x] **Differentiation audit + redesign — DONE 2026-08-10**, applied via
      a second data migration (`0017_redesign_tier_benefits.py`, on top of
      `0016` rather than editing it in place). The original matrix had
      one structural break (AGM vote sat on the cheaper Full Annual tier,
      not the pricier Associate — fixed, moved to Associate) and several
      flatlines where 3-8 adjacent tiers shared an identical value across
      large price gaps (career services identical from KES 500-500,000;
      library borrowing identical across all 5 Life tiers; consultancy
      panel and advisory forum each had duplicate adjacent pairs) — all
      converted into real escalation ladders. Two benefits reclassified
      VOICE→ACCESS (publication/speaking slots; VC/Chancellor invitation
      — scarce access, not enforceable governance input). Associate kept
      as its own tier (Association decision) rather than the redesign's
      offered fallback of collapsing it into Full Annual — its full
      differentiator is now the AGM vote. Escalation-ladder wording
      (e.g. "résumé featured to recruiters", "reserved bay + valet") is
      invented copy for the redesign exercise, not Association-authored —
      spot-checked 12 cells against the proposal, all correct; still
      needs a copy pass before this reads as final member-facing text.
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

### 1.8 Spreadsheet export/import — export done, import pipeline built + verified 2026-08-07
- [x] `django-import-export` installed, added to `INSTALLED_APPS` (2026-08-06).
- [x] **Legacy-membership import pipeline — built and verified 2026-08-07**,
      `apps/home/management/commands/import_legacy_memberships.py`. Not a
      django-import-export `Resource`/`ModelResource` in the end -- one row
      fans out into several model instances (User/UserProfile/AlumniProfile/
      Membership + up to 2 overflow `AlumniQualification` + 1 overflow
      `AlumniEmploymentRecord` + overflow phone/email rows), which fights
      that abstraction's one-row-one-model assumption. Plain management
      command instead, safe by default (runs in a transaction that's
      rolled back unless `--commit` is passed), with a report listing every
      unmapped value in the ambiguous columns (Title/Gender/Nationality/
      CurrentCategory/College/Faculty/Course) so mapping-table gaps surface
      before a real run, not after.

      Verified end-to-end against `docs/data/Membership format.xlsx` (a
      2-row structural sample, gitignored -- real PII, never committed;
      full roster still to come). Phone normalization, name/gender/
      nationality mapping, Faculty resolution via
      `docs/uon_faculty_mapping.json` (both direct college-code and
      fuzzy legacy-unit-text paths), graduation year, and Membership
      tier/status/number/dates all resolved correctly on the sample.
      Free-text `Course` values that don't match the seeded `Qualification`
      catalog (e.g. "BDS MPH" is two combined quals) are no longer silently
      lost -- `AlumniProfile.qualification_name_raw` (2026-08-07) mirrors
      `AlumniQualification.course_name_raw`'s fallback for the primary
      slot too. Re-verified against the sample after adding it: both
      unmatched courses land in `qualification_name_raw` correctly.
      **Not yet mapped anywhere:** `Payroll` (no field exists for it).

      Mapping tables (`HONORIFIC_MAP`/`TIER_NAME_MAP`/etc. at the top of
      the file) currently only cover the handful of values seen in the
      2-row sample -- re-run with `--dry-run` (the default) against the
      real full file first and extend them with whatever the report's
      "Unmapped values" section lists before ever using `--commit` on it.
- [x] General-purpose bulk export for "give me a spreadsheet of paid members" --
      `MembershipResource`/`AlumniProfileResource` (`apps/home/admin.py`),
      wired via `ExportMixin` onto `MembershipAdmin`/`AlumniProfileAdmin`.
      Staff/superadmin-only by construction (Django admin's own `is_staff`
      gate at `/2005/`, same as every other screen there) -- no separate
      permission code needed.

### 1.9 Membership analytics dashboard — DONE 2026-08-07
Chart.js, pulling from `Membership`/`AlumniProfile`/`Faculty`. Renders
correctly against zero data today (honest "no records yet" message instead
of broken/empty charts) -- becomes actually useful once the legacy import
(1.8) lands real rows.
- [x] `MembershipAnalyticsView` (`apps/home/views.py`) at
      `/analytics/membership/` -- counts/revenue by tier, by faculty (top 10,
      via `AlumniProfile.faculty`), by status, `subscription_amount` trend by
      month (`TruncMonth` on `started_on`), and `legacy_signed` coverage.
      Gated by the new `StaffOrSuperuserRequiredMixin`
      (`apps/user/mixins.py`) -- anonymous → login redirect, non-staff → 403,
      verified via Django test client + a real authenticated-session
      screenshot. Deliberately separate from 1.2's self-service dashboard:
      this is leadership reporting across *all* members.
- [x] Chart.js chosen over Highcharts.js (2026-08-07) -- free/MIT, no
      licensing conversation needed with the Association.
- [ ] Renewal rate and active-vs-expired trend lines -- straightforward
      additions to the same view once there's real data to make them
      meaningful; not built tonight since they'd be untestable against zero
      rows.

---

## PHASE 2 — Payments (attach to the member core; automate the manual step)

Goal: flip Phase 1's manual approval from *the* path into an *exception* queue.
Everything here plugs into the 1.3 service layer — payments become just another
caller of the same door.

### 2.1 M-Pesa (Daraja)
- [x] **Tier eligibility gate — DONE 2026-08-07** (ahead of the real Daraja
      integration below, same manual-confirmation pattern as everything
      else pre-Phase-2). `MembershipTier.allows_mpesa` = fee <=
      `MPESA_FEE_CEILING` (KES 100,000, matching Gold's fee and M-Pesa's
      real per-transaction limit) -- Diamond/Platinum/Corporate must use
      Bank Transfer. Enforced in both `AlumniRegistrationForm` and
      `MembershipUpdateForm.clean()`, plus a client-side JS nicety
      (disables the option, doesn't rely on it). `Cash`/`Cheque` removed
      from `Payment.PAYMENT_METHODS` entirely -- everything now routes
      through a traceable channel.
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
- [x] **Paying one tier off in installments — DONE 2026-08-07**, ahead of
      the rest of Phase 2 (doesn't need a payment gateway; same manual
      Secretariat confirmation pattern as everything else in Phase 1).
      `Membership.payment_frequency` (already existed, was unused) now
      actually drives something: `amount_paid`/`next_installment_due`
      fields, `balance_due`/`is_installment_plan`/`is_overdue` properties,
      and `record_installment_payment()` accumulate payments against one
      `Membership` row via a new direct `Payment.membership` FK (the old
      lookup-by-tier-and-pending-status broke on a second installment).
      Decisions ratified 2026-08-07: activates on the FIRST payment,
      balance carried as arrears (not held pending until paid in full);
      lapses via `expire_lapsed_installment_plans` (grace period = one
      full billing cycle past the due date -- 60/180/730 days for
      monthly/quarterly/annually, not a flat number). **Note:** `is_lifetime`
      is duration-only (never expires once paid off) and deliberately
      doesn't exempt a Life-tier installment plan from expiring if they
      stop paying -- caught this exact conflation as a bug during testing
      and fixed it in both `balance_due` and the expiry command's filter.
      **Still needs:** a real scheduled-task runner for the expiry command
      -- no Celery/cron wired up yet, same gap Phase 3 already flags.
- [ ] **Installment upgrades** toward the next ladder rung: a payment can be
      *partial toward a target*, but the target is the *next tier up*, not
      the current one -- e.g. paying off Bronze then rolling the excess
      toward Silver automatically. Different from the above (which is
      "pay off Gold in pieces, still Gold throughout"); still deferred.
      Accumulate amount-paid-toward-tier on the `Membership`; upgrade via
      the service layer only when cumulative payments clear the next
      rung's `ladder_rank` price.
      **Decisions ratified 2026-08-08 (not yet built):**
      - Trigger is **automatic**, not member-initiated: every call to
        `record_installment_payment()` checks cumulative `amount_paid`
        against the next `ladder_rank` tier's price; clearing it fires the
        1.3 service layer's tier-bump function with no separate member
        request needed. Uses the same new-row-plus-`SUPERSEDED` mechanics
        as any other 1.3 upgrade.
      - **Analytics:** `MembershipAnalyticsView` gets a new chart — upgrade
        counts broken down **by tier transition** (e.g. Bronze→Silver: 12,
        Silver→Gold: 5), not just a raw total. Needs the old→new
        relationship captured on the row (e.g. a `superseded_membership`
        self-FK) so the query has something to group by.

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
      migrating the remaining hardcoded pages (`history`, `donate`,
      `scholarship`, `contact`, etc.) onto it — the mechanism exists, the
      content migration doesn't.
- [x] **Privacy notice + terms of use pages — DONE 2026-08-07.** Privacy
      Policy, Cookie Policy, and Terms of Service all seeded via
      `seed_legal_pages` (DPA-2019-aligned drafts, NOT lawyer-reviewed --
      Association should have them checked before final). The 1.1 blocker
      is resolved. Privacy + Terms URLs also handed to Google for the
      OAuth consent screen's required links.
- [x] **Sign-in page copy updated — DONE 2026-08-11.** `templates/account/login.html`
      no longer claims access is restricted to `@uonbi.ac.ke` accounts (that
      restriction was removed at the auth layer; the copy had gone stale).
      Now: "Sign in with your Google account to continue." + a "having
      trouble? contact ICT Directorate" helper line, mailto link preserved.
      **Still open:** `templates/staff/staff_login.html` (a separate Staff
      Portal login page) still says "Use your @uonbi.ac.ke Google account" --
      not touched, since it's unclear whether that restriction is still
      intentional for the staff-only portal specifically. Needs a decision.
- [ ] **Google OAuth consent screen -- logo not rendering + "In production"
      publishing blocked (2026-08-11).** Uploaded a UoNAA logo via Google
      Cloud Console (OAuth consent screen → Branding) but it isn't showing
      on the live consent screen -- Google deliberately suppresses custom
      branding on unverified apps (anti-phishing measure), so this won't
      show until the app is verified/published, not a bug in the upload.
      Tried setting publishing status to "In production" and hit: *"restricted
      to projects using HTTPS URLs only... remove non-HTTPS URLs from the
      clients page."* Confirmed this app's production side is already
      HTTPS-only end-to-end (`SECURE_SSL_REDIRECT`, HSTS, `SECURE_PROXY_SSL_HEADER`
      all correctly set in `main/settings.py`) -- the flagged URL is almost
      certainly a leftover local-dev redirect URI (`http://127.0.0.1:8000/...`)
      registered on the same OAuth Client being published.
      **Recommended fix, not yet done:** split into two OAuth 2.0 Clients in
      the same Google Cloud project -- a **production** client (HTTPS-only
      redirect URI, `https://uonalumni.or.ke/accounts/google/login/callback/`,
      this is the one to publish) and a **dev** client (keeps the
      `http://127.0.0.1:8000/...` redirect URI, stays in Testing status, its
      Client ID/Secret swapped into the local `.env` only) -- so publishing
      production doesn't break local Google-login testing. Also needs Google's
      app verification (domain verification via Search Console; Privacy/Terms
      links already provided per the item above) before the logo will actually
      display for real users, separate from the HTTPS fix itself.

### C.3 Editor experience (highest leverage, all small)
- [ ] **Rich text editing.** Every content model has `body = TextField()`, so the
      Association cannot add a heading, a link, or an inline image. Everything
      else here is decoration until this exists.
- [ ] Draft / publish / schedule (rides `is_published` + `published_at` from 0.3b).
- [ ] **Editorial permissions via Django Groups** — a content editor should
      publish articles without holding admin over members, payments and PII.
      Today there is one admin tier over everything.

### C.4 Findability and sharing
- [x] **[DONE 2026-08-18/19]** SEO + Open Graph meta. `templates/base.html`
      now carries a full metadata framework: per-page `meta_description`/
      `canonical_url`/`robots` blocks, `og:*` + Twitter Card tags (falling
      back to `Article.thumbnail`/`event.thumbnail` via `og_image` where a
      page has one), and a sitewide Organization JSON-LD block
      (`apps/home/context_processors.py`'s `seo()`). The title tag itself
      was reworked into a three-way `title_brand`/`title_interior`/
      `title_bare` budget system (60-char cap, see `base.html`'s own
      comment for the full policy) and every template migrated off the
      old single `page_title` block. Favicon package (ico/PNG/apple/
      android/ms icons, manifest.json, browserconfig.xml) tracked and
      wired in the same pass — was sitting in `static/favicon/` entirely
      untracked and unlinked before.
- [ ] Site search. Neon is Postgres, so `SearchVector`/`SearchRank` gives real
      full-text search across articles, publications and events with no extra
      infrastructure.
- [ ] Pagination on every list view.
- [x] **[DONE 2026-08-18]** `sitemap.xml` + `robots.txt` — `main/urls.py`'s
      `sitemap` route (`apps/home/sitemaps.py`), served per-host on
      staff./students. too (both noindex,nofollow site-wide).
- [ ] RSS feed — `django.contrib.syndication` not started.
- [ ] Tags / related content for cross-linking.
- [x] **[DONE 2026-08-18]** Branded 404 / 500 pages — `templates/{400,403,404,500}.html`.
      404/403/400 extend `base.html` (full nav/footer/background, get a real
      RequestContext); 500 is deliberately standalone (Django renders it with
      no request/context at all, so it can't use any of that). Only render via
      Django's own handlers when `DEBUG=False` — verified against a real
      `DEBUG=False` local instance, not just DEBUG=True dev serving, which
      silently bypasses all four in favor of Django's own debug pages.
- [ ] Structured data (schema.org `Article`, `Event`) — **partial.** Sitewide
      Organization JSON-LD exists (above); `walk_detail.html` emits a
      minimal Event block (`name` only, no `startDate`/`location`) via the
      new `json_ld_extra` block. `article_detail.html` has no Article
      JSON-LD at all yet despite already setting `og_type=article`.

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
- [ ] **[NEW 2026-08-20]** "Get Involved" hub — the homepage hero's second-section
      CTA ("See How to Get Involved") has nowhere to point yet. Needs to land
      somewhere that fans out to Donating (page exists, `home:uon_alumni_donate`),
      Volunteering (no page yet), and Mentorship (no page yet — see C.7's
      "Mentorship matching," Phase 4+). CTA href is `#` on the homepage until
      this exists.
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
  0.3b, everything else parallel. The copywriting/data-entry audit is now
  merged into this file as "Content Authoring Backlog" below (2026-08-07,
  reconciled against actual current state) — that is authoring work, not
  dev work.
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

---

## Content Authoring Backlog

Merged in 2026-08-07 from the standalone `content_todo.txt` (previously at
repo root) for cohesiveness — one todo list instead of several scattered
files. Reconciled against actual current state at merge time, not a raw
copy: the original was written before this session's identity rebuild and
nav-wiring pass, so most of its "Controller" (routing) section was already
fixed and has been marked as such below. The "Model" (data-entry) section
is confirmed still accurate — checked real row counts: **every** content
model (Executive, Secretariat, Chapter, Partner, Event, Images, Banner,
CoreValue, Publication, InMemoriam, JobPosting) sits at 0 records; `Article`
has exactly 3 (Privacy/Cookie/Terms — legal pages, not news/content).

This is **authoring work** (copy, photos, data entry via `/2005/` admin),
not dev work — the plumbing to display it now exists for almost everything
listed. Grouped by whether the blocker is "someone needs to write/upload
this" (Data) or "this page has no real content yet" (Copy).

### Data — needs records entered via admin
All of these have a working admin registration now (`/2005/`); this is
purely a data-entry/copywriting task.

1. **Executive Committee** (`Executive` model) — title, position, rank, bio,
   avatar per member. Needed for `/uon-alumni-executive-committee/` to show
   anything.
2. **Secretariat** (`Secretariat` model) — same shape as Executive. Zero
   records.
3. **Mission, Vision & Core Values** — Mission/Vision are still two
   hardcoded strings in `context_processors.py` (not a model, not editable
   without a code change) — decide whether that's fine or worth moving to
   an editable singleton. `CoreValue` model is fully built and admin-
   registered but has zero content.
4. **Chapters** (`Chapter` model) — name, about text, year launched,
   thumbnail, linked Faculty. `uon_alumni_history.html` still brags about
   "17 chapters" that don't exist as records.
5. **Partners** (`Partner` model) — title, relation to UoNAA, thumbnail.
   Now properly admin-registered (was a gap in the original audit, fixed
   during this session's nav-wiring pass).
6. **News / Articles** (`Article` model, `type=news/feature/notice`) —
   the homepage promises "class notes, distinguished alumni profiles,
   obituaries, institutional updates" and has zero of it published.
7. **UoN Alumni Walk** (`Event` model, `event_type=WALK`) — title, body,
   thumbnail. Zero events entered.
8. **Gallery photos** (`Images` model) — attaches to Article/Chapter/
   Event/Publication/InMemoriam. Needed before Gallery is more than an
   empty grid.
9. **Banner imagery** (`Banner` model) — per-banner images + logo + text.
   Zero rows, so the banner snippet is still running on its one hardcoded
   hero image rather than real content.
9b. **[NEW 2026-08-11]** Homepage advert/promo carousel (`Images.show_in_carousel`)
    — snippet + wiring built tonight, renders below the banner and hides
    itself entirely when there are no flagged images (currently zero).
    Needs someone to upload images via `/2005/` (Gallery Image admin) and
    tick "Show in homepage carousel" before it shows anything.
10. **[DONE 2026-08-10/11]** Membership tier benefits copy — `Benefit`/
    `TierBenefit` models built and seeded (25 benefits × 250 tier-benefit
    rows, the 2026-08-10 tier-benefits matrix). Categories & Benefits is
    no longer a standing_page candidate (see #15 below) — it's its own
    `MembershipCategoriesView`, live at `/uon-alumni-membership-categories/`,
    rendering real per-tier benefit copy with incremental "everything in
    X, plus:" diffing.
10b. **[NEW 2026-08-18]** Reconciled `MembershipTier` against the eleven
    UONAA Constitution (Art. 8) membership categories — new flat fields
    (`code`, `holder_type`, `fee_amount`, governance/eligibility flags,
    etc.) added and backfilled via
    `apps/home/management/commands/reconcile_constitutional_categories.py`
    (idempotent, safe to rerun). "Platinum Life Membership" was renamed
    to "Founder" and its 25 existing benefits carried over with it — see
    that command's own module docstring for the full reasoning. Left
    open, still needs a person (not a rerun of the command):
    - **No `TierBenefit` rows for Honorary, Affiliate, or Senior
      Citizen** — all three now exist as real categories with correct
      constitutional provisions, but zero benefits, so none of them
      show on the public Categories & Benefits page yet (same "empty =
      invisible" behavior as everything else in this list).
    - **Affiliate is additionally excluded outright** by
      `tier_type="registered"` (the closest existing legacy value it
      could be given — Affiliate isn't really any of the 6 existing
      `tier_type` choices) regardless of whether it gets benefits.
      Worth revisiting once real benefits exist for it.
    - **"Diamond Life Membership" and "Associate"** (`MembershipTier`
      pk 4 and 11) have no seat in the eleven Constitutional categories
      — flagged explicitly during reconciliation, deliberately left
      untouched per instruction — but they still carry 25 real benefits
      each and are still showing publicly on the Categories & Benefits
      page today. Decide: pull them from the public page, or leave them.
11. **Publications** (`Publication` model) — newsletters, minutes, annual
    reports. Zero rows; Downloads page (built, routed) has nothing to list.

### Copy — pages that exist and route correctly, but have no real content
Unlike the original audit, every one of these now has a working URL,
view, and template (built during this session's C.1 fixes + nav-wiring
pass) — the remaining gap is purely the words on the page.

12. **Donate** — **[rebuilt 2026-08-19]**, so this is narrower now: the
    page has a real structure, `snippets/donate.html`, matching the same
    popout-card pattern as Membership Categories — four preset giving
    amounts (Supporter/Contributor/Champion/Patron), each with a short
    "this supports" blurb and a "Give This Amount" button. **Still not
    real content:** the amounts (KES 1,000/5,000/15,000/50,000) and
    blurbs are placeholder copy, not Association-authored or approved.
    No payment gateway exists yet (Phase 2 below), so each button
    doesn't process anything — it links to Contact Us. Still genuinely
    missing: M-Pesa paybill/bank details, real fund designations, impact
    stories, receipt/tax info — same gaps as before, just now sitting
    inside a real layout instead of a blank paragraph.
13. **Scholarship** — **[application form built 2026-08-11, evaluation +
    analytics pipeline built 2026-08-14/18]**, so this is narrower again:
    the public page has a full `ScholarshipApplicationForm` (personal/
    university/contact/home/school/achievements, cascading Faculty→
    Department dropdowns, file upload). Behind it, staff now have a full
    working pipeline that didn't exist before this session — the two-pane
    evaluation screen (`apps/student/views.py`'s
    `EvaluateApplicationView`: applicant's uploaded PDF alongside the
    interview scoring matrix, Select2 picker), the Applicant Dashboard
    (`ApplicantDashboardView` — faculty/gender/county/evaluation-pipeline/
    parental-status charts, an "Export to Excel" button), and
    `apps/student/analytics.py` backing an 8-sheet `.xlsx` workbook export
    with native charts (query-count-budgeted, verified against real
    Postgres aggregates). None of this is copy/content work — still
    needed on that front: actual copy *around* the public form (which
    programme(s) this is, eligibility criteria, what happens after you
    apply, past-recipient stories). Right now it's just a one-line
    subtitle straight into the form.
14. **In Memoriam** — `<p>In Memoriam page</p>` placeholder. Needs a real
    listing (feeds from the now-built `InMemoriam` model, once #entries
    exist) and a "submit a tribute" path.
15. **AGM, Consultancy & Training, Alumni Card, Corporates, Our Notable
    Alumni, Shop** — all route through the generic `standing_page`
    mechanism now (same one Privacy/Terms/Cookies use) but have no
    `Article(type=page)` row written yet. Shop specifically also needs a
    business decision (is UoNAA actually selling merchandise) before it's
    worth writing. **Categories & Benefits removed from this list** — it's
    not a standing_page, see #10 above.
16. **Homepage "Latest News & Updates" / benefits section** — the
    featured/highlighted-article loops are still `{% comment %}`ed out on
    the homepage, waiting on #6's content to have something to loop over.
17. **[DONE 2026-08-18/19]** SEO / social metadata — see C.4's findability
    section above for the full writeup; was cross-referenced from both
    angles, now closed from both.
18. **Newsletter archive** — `AlumniProfile.receive_newsletter` opt-in
    exists with nothing to actually send yet (ties to Phase 3
    Communications).
19. **Careers (UoNAA's own hiring, not the alumni job board)** — the
    original audit's concern was whether *UoNAA itself* posts job
    openings, distinct from the `JobPosting` alumni job board already
    built and routed. Still an open question for the Association, not a
    dev gap.

**Suggested order** (from the original audit, still holds): the Model
section as a content sprint (photos + bios + copy, publishing each Copy
item as its data lands) is what's actually blocking now — the Controller-
layer gaps that used to sit in front of it are resolved.

---

## Code Review Findings

Merged in 2026-08-07 from the standalone `docs/code_review_todo.txt` for
cohesiveness. Findings from a review of the staff directory filter/search
feature, `profile_update.html`, `forms.py`, `staff_extras.py`, and
`employee_table.html` — unrelated to tonight's Membership/payments/URL
work, still open as originally filed unless marked fixed.

### Bugs / correctness (fix first)
1. **[FIXED 2026-08-11]** Reflected XSS via `track` GET param in Alpine
   `x-data` — `templates/staff/all_uon_staff.html:25`. Fixed both ways
   the finding suggested, not just the minimal patch: `EmployeeListView`
   now allowlists `track` against `Employee.StaffTrack.choices`
   server-side (`_validated_track()`, shared by the queryset filter and
   the template context, so an invalid value never reaches rendering at
   all), and the template passes `selected_track` to Alpine via
   `json_script` instead of raw string interpolation into the JS-string
   context. Verified with the exact payload from the original finding
   (`?track=x',evil:(alert(1),0)`) — neutralized to `""` server-side,
   nothing resembling it reaches the response; legitimate values
   (`teaching`) still round-trip and filter correctly.
2. **[FIXED 2026-08-13]** HTMX self-nesting on every filter/search/
   pagination interaction — `all_uon_staff.html:26-30`,
   `partials/employee_table.html:1,51,69,83`. `hx-target`/`hx-select` both
   resolved to `#staff-table-container`, which the returned partial already
   has on its own root — default innerHTML swap nested a duplicate-id copy
   instead of replacing it. Since the partial's entire content *is* that
   one element, `hx-select` was redundant once swap mode was right — 
   dropped it and added `hx-swap="outerHTML"` in all 5 places (the filter
   form + 4 pagination links). Verified live: `#staff-table-container`
   count stays at exactly 1 through repeated search interactions
   (previously would have compounded to 2, then 3, ...).
3. **[FIXED 2026-08-06]** Navbar/banner/footer commented out on
   `staff/profile_update.html` — uncommented during the nav-wiring pass.
4. **[FIXED 2026-08-13]** Track/unit filter combo isn't cross-validated
   client or server side — a stale URL like `?track=teaching&unit=service:5`
   rendered a disabled-yet-selected option with no indication the combo
   was contradictory. `EmployeeListView._validated_unit()` now
   cross-checks the unit's type prefix against the validated track
   (same allowlist pattern as `_validated_track()`) and returns `""` on
   a mismatch — an invalid combo is simply never selected, both for the
   queryset filter and for what the template renders. Verified live:
   `?track=teaching&unit=service:1` resolves to no unit selected;
   `?track=service&unit=service:1` still resolves correctly.
5. **[FIXED 2026-08-13]** `hx-trigger` override on the filter form
   dropped the implicit `submit` trigger — clicking Apply/pressing Enter
   did a full page reload while typing/select changes stayed AJAX.
   Added `submit` to the explicit trigger list. Verified live: clicking
   Apply now fires a request with `HX-Request: true` and updates via
   pushState, no full navigation.
6. **[MED]** `EmployeeListView`'s own docstring calls it a "Public staff
   directory," but it's `LoginRequiredMixin` and the navbar links to it
   from the unauthenticated branch — confirm which behavior is intended.
7. **[LOW / needs manual test]** Possible event-ordering race between
   Alpine's `x-on:change` cleanup and htmx's own `change from:#id_track`
   trigger on the same event.

### Cleanup
8. `staff_extras.py`'s `cloudinary_download` filter is defined but never
   `{% load %}`ed anywhere — dead code.
9. The `?page=&q=&track=&unit=` query string is hand-duplicated 6x across
   `employee_table.html`'s pagination links.
10. `EmployeeListView.get_context_data` builds Department/ServiceUnit/
    ResearchUnit querysets on every request, including HTMX partial
    requests that never touch those dropdowns.
11. Track-to-unit disabling logic spread across three near-identical
    `x-bind:disabled` expressions plus one imperative handler — could
    consolidate into one Alpine computed getter.
12. `apps/staff/forms.py`'s rounding class changes (`rounded-lg/xl/2xl` →
    `rounded-sm`) only followed through on `profile_update.html`;
    `complete_profile.html` renders the same form with the old rounding.

### Architecture / future work
13. **Shared base model for Employee/AlumniProfile/(future)Student** —
    all three duplicate a large chunk of personal/contact fields
    independently (honorific, names, DOB, national ID, phone, slug,
    is_active, the full_name/display_name property pattern). Proposal: a
    shared abstract `PersonProfile` base. Real migration work, plan as its
    own task.
14. **Friendlier Google OAuth failure page + surfaced diagnostics** —
    allauth's generic `authentication_error.html` swallows the real
    exception; nothing reaches logs or admins. Needs a branded error page
    + `logger.exception()` in `CustomSocialAccountAdapter
    .authentication_error()`, eventually wired to `AdminEmailHandler`/
    Sentry (needs SMTP configured first).
15. **Session/idle timeout re-authentication on data-sensitive alumni
    pages** — `AlumniProfileUpdateView`/`AlumniMembershipUpdateView`/
    `AlumniProfileDeleteView` accept a POST any time the session is alive,
    however long the tab's been open. Proposal: stamp
    `request.session['auth_time']` on login, step-up re-auth via Google if
    stale on POST to these specific views (not staff).

**Suggested order:** ~~#1/#2/#4/#5~~ all fixed 2026-08-13. Left: #6
(needs a decision, not code — is the staff directory meant to require
login?) and #7 (low priority, needs manual test). Then cleanup (#8-12)
as time allows. #13-15 are separate future initiatives.

---

## Infrastructure findings (2026-08-18 session)

Discovered while previewing `DEBUG=False` behavior locally (needed to check
the branded error pages actually render, since `DEBUG=True` dev serving
bypasses them). Unrelated to that task, not fixed, not tracked anywhere else.

1. **`STATICFILES_STORAGE` (WhiteNoise's `CompressedManifestStaticFilesStorage`)
   isn't actually active.** `main/settings.py` sets it via the legacy setting
   name, but `django.contrib.staticfiles.storage.staticfiles_storage` resolves
   to plain `StaticFilesStorage` instead — confirmed directly
   (`type(staticfiles_storage)` in a shell, and `collectstatic` never writes
   the `staticfiles.json` manifest the Manifest storage class requires no
   matter how many times it's rerun). Static files still serve correctly
   either way (`{% static %}` just falls back to plain, unhashed URLs, and
   WhiteNoise serves whatever's actually at that path) — nothing is broken
   for users. What's missing is the compression + cache-busting/immutable-
   caching WhiteNoise's Manifest storage is specifically for. Likely fix:
   Django 4.2+'s `STORAGES` dict setting takes precedence over the legacy
   `STATICFILES_STORAGE`/`DEFAULT_FILE_STORAGE` names when *both* exist in
   the same settings module in certain combinations — `DEFAULT_FILE_STORAGE`
   is also set conditionally nearby (Cloudinary), which may be the actual
   interaction suppressing it. Worth a focused look, not guessed at further
   here.

---

## Production incident — site-wide 500s (2026-08-19)

Reported live by a user hitting `students.uonalumni.or.ke`. Two independent
bugs, both regressions from the 2026-08-18 SEO audit's `main/urls.py`
change (it stopped `include()`-ing `apps.staff.urls`/`apps.student.urls`
directly into `main.urls`, so those subdomains' `staff`/`student` namespaces
no longer exist anywhere main.urls can reverse against — only some call
sites were updated to match). Both fixed and confirmed live via the VPS
gunicorn journal (`journalctl -u uon_alumni`), not just guessed from
reading code.

1. **`templates/{400,403,404}.html`'s "Return Home" link** used
   `{% url 'home:uon_alumni_home' %}`, which resolves against whichever
   urlconf is active for the *current* request. On staff./students. that's
   `apps.staff.urls`/`apps.student.urls`, neither of which has a `home`
   namespace — so rendering any of these three error pages on those
   subdomains raised `NoReverseMatch` mid-render, surfacing as a raw 500
   instead of the intended 400/403/404. Fixed by swapping in `{{ url_home }}`
   (the cross-subdomain-safe context variable these templates already use
   one line below for the Contact button) — the safe pattern was already
   sitting right there, just not applied consistently. (`603504a`)
2. **`contacts()` context processor — the bigger one.** This runs on
   *every* page (it's a global context processor), and for any
   staff/superuser session it called
   `reverse("student:evaluate_application_list", urlconf="main.urls")` to
   build the admin dropdown's "Evaluate Applicants"/"Charts" links. Since
   `apps.student.urls` was removed from `main.urls` in the same 2026-08-18
   audit, `'student'` isn't a registered namespace there at all, so this
   raised `NoReverseMatch` on **every single page** any staff/superuser
   user loaded, sitewide — not just students. Anonymous traffic never hit
   it, which is why it wasn't caught sooner. Fixed the same way QR Admin
   (one line above in the same function) already handled the identical
   staff-namespace problem: a hardcoded path against the subdomain's own
   base URL (`students_base`, newly added alongside the existing
   `base`/`staff_base`) instead of `reverse()` against a urlconf that was
   never going to have that namespace. (`087bced`)

**Lesson, same shape as the 2026-08-10 Neon/staff_faculty incident above:**
a urlconf/routing restructuring needs every cross-subdomain `reverse()`/
`{% url %}` call site audited against it, not just the ones the person
making the change happened to touch. Worth a deliberate grep sweep
(`reverse(` / `{% url ` for `student:`/`staff:`) after any future change
to `main/urls.py`'s subdomain wiring — done once during this incident's
fix (see the two above), not set up as a recurring check.

---

## Other docs in this folder (not merged — different purpose)

- `docs/0.1-identity-decisions.md` / `docs/rebuild-schema.md` — design
  rationale for the identity-model rebuild (field map, tier taxonomy,
  numbered decisions). Reference material explaining *why* this schema
  looks the way it does, not a list of pending work.
- `docs/todo-pre-rebuild-2026-08-05.md` — a frozen snapshot of the todo
  list as it stood immediately before the greenfield rebuild. Historical
  record of the starting point, not live — this file (`todo.md`) is what
  actually got reconciled against it and is the one to keep updated.
- `docs/uon_faculty_mapping.json` — reference data (the 2021 college→
  faculty restructure + constituent colleges), consumed by the seed
  commands. Not a todo list.

---

## Deferred / low priority

- **[DEFERRED 2026-08-18]** Paginated PDF report of the scholarship
  exercise for institutional filing (cover page, executive summary,
  faculty/county/gender distribution, criterion diagnostics, evaluator
  consistency, cutoff simulation, full per-applicant appendix — reading
  from `apps/student/analytics.py`, same data the Excel export already
  uses). Decided against for now: the Excel export already covers
  actually crunching the numbers, and that's what the PDF would have
  been for. Ground truth already gathered, so a future pickup doesn't
  need to redo the investigation:
  - Every number the spec wanted is already returned by
    `apps/student/analytics.py`'s functions (see that module for the
    exact keys) — nothing missing, no gap to ask about.
  - The only existing ReportLab code in this repo is the QR badge PDF
    (`apps/staff/views.py`'s `download_staff_qr_code`) — reusable:
    the `SimpleDocTemplate` → `HttpResponse` pattern, `getSampleStyleSheet()`.
    Not reusable / doesn't exist yet: A4 pagesize (badge uses `letter`),
    any font registration (none anywhere in this codebase), any
    `Table`/`LongTable` usage (badge has zero tables), any page-number/
    footer mechanism (would need a fresh `NumberedCanvas`, the standard
    two-pass ReportLab recipe).
  - `applicant_scores()`'s per-applicant row has 17 columns (identity +
    faculty/gender/county + 8 criteria + total/percentage + evaluator +
    date) — almost certainly too wide for A4 portrait, so the appendix
    would need `NextPageTemplate`/landscape switching, also not
    reusable from anywhere existing.
  - Decided: real names throughout if this gets picked up later (no
    anonymized variant, no application-number substitution) — the
    aggregate sections (everything except the appendix) never had
    individual names in them to begin with, so there was nothing to
    anonymize there regardless.

- **[DEFERRED 2026-08-18]** Q2 Workload 2 — "AlumniProfile creation" as an
  async task (originally next in the Q2 migration sequence after
  transactional email; see the Django Q2 cluster work above/in
  `apps/home/tasks.py`). Decided against for now, moved downstream:
  `AlumniRegisterView.form_valid()` (`apps/home/views.py`) has no genuine
  async target today —
  - `get_success_url()` returns `self.object.get_absolute_url()`, which
    needs a real pk (and slug) before the response is built. Deferring
    the AlumniProfile row itself means there's no page to redirect to
    yet without adding a "processing your registration" interstitial.
  - Membership assignment and Payment creation both reference
    `self.object` directly, so they can't stay synchronous while the
    profile creation that feeds them goes async — the boundary doesn't
    split cleanly into "one workload."
  - Nothing in the current path is actually slow: no external API
    calls, no image generation, no file uploads. `initiate_payment()`
    only reaches `ManualGateway` (a synchronous no-op logger). Every
    write is a fast local Postgres insert — unlike email, there's no
    real latency to hide here.
  - Forward-looking risk: a real payment gateway (M-Pesa STK push,
    Stripe) will likely need to redirect/prompt the user synchronously
    in the same request (see PHASE 2 above) — deferring registration
    onto a queue now would work against that later.
  - Checked whether QR code generation (`apps/qr_manager`'s
    `QRCode.generate_qr()`) was the real deferrable piece hiding inside
    "AlumniProfile creation" — it isn't; it's staff-triggered later from
    Django admin (`QRCodeAdmin.save_model()` etc.), not called from
    self-service registration at all.
  - Revisit if either changes: a real payment gateway forces a redesign
    of this view anyway, or a genuine bottleneck shows up in this path.
  - Q2 sequence continues at Workload 3 (e-newsletter) instead.
