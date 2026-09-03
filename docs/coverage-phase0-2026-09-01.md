# Coverage baseline and risk-ranked priority — Phase 0

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests` (measured here; see [Branch](#branch) below)
**Measured against:** commit `397635d` — **113 tests, 0 errors, 0 failures**
**Status:** 🛑 measure-and-propose only. **No test written, no source changed.**

---

## How this was measured

```
alumni/Scripts/python.exe -m coverage run \
    --source=apps --omit="*/migrations/*,*/tests.py,*/__pycache__/*" \
    manage.py test apps --noinput
alumni/Scripts/python.exe -m coverage report -m
```

Local Postgres, not SQLite. The suite stayed green under instrumentation — **113 tests, OK** — so every number below is a reading, not a floor.

**coverage.py is not a project dependency.** It was installed into the `alumni/` virtualenv only; `requirements.txt` and `requirements-dev.txt` are untouched. If you want it kept, the line to add to **`requirements-dev.txt`** is `coverage==7.16.0`. There is no `.coveragerc` — the flags above are the whole configuration, and are worth committing as one if this becomes routine.

**Observed during the run, harmless:** django-autoslug prints `Failed to populate slug Employee.slug` several times. That is its `__debug__` notice when a populated value is empty — the blank-named employee fixtures added during the QA-500 sweep — and it falls back to the model name as designed. Noise, not a failure.

---

## Overall

| Scope | Statements | Missed | Cover |
|---|---:|---:|---:|
| **All apps** | 5,438 | 2,212 | **59%** |

| App | Cover |
|---|---:|
| `apps.student` | 77% |
| `apps.qr_manager` | 76% |
| `apps.staff` | 61% |
| `apps.user` | 57% |
| `apps.home` | 52% |

`apps.home` being lowest matters more than the number suggests: it holds the membership, payment and profile logic, and it is by far the largest app.

---

## Read the percentages sceptically

Raw statement coverage overstates how much is genuinely *tested* here, in a way worth naming before anyone treats these figures as a scoreboard.

**Inflated by incidental execution.** `apps/home/models.py` at 83% and `apps/student/models.py` at 92% are largely field declarations, `__str__`, and properties executed while fixtures are built — executed, never asserted against. A `__str__` that runs during `setUpTestData` counts identically to one with a test. The model *behaviour* that matters — `Membership.activate()`, `record_installment_payment()`, `is_valid`, expiry arithmetic — is far less covered than 83% implies.

**Genuinely tested, and it shows.** `apps/user/signals.py` (100%), `apps/user/phone.py` (100%), `apps/qr_manager/utils.py` (100%) and `apps/qr_manager/views.py` (74%) are backed by dedicated behavioural tests, most of them written during the QA-500 sweep. `apps/home/context_processors.py` at 93% is a genuine result of the auth × host matrix sweep exercising every page.

So: the low numbers are real, and some of the high ones are not. Ranking work by percentage would send us to exactly the wrong places.

---

## Entirely untested modules (0%)

| Module | Stmts | What it does |
|---|---:|---|
| `apps/home/tasks.py` | 55 | **All django-q2 async work** — registration confirmation, newsletter, claim OTP e-mail, SMS dispatch, instalment expiry |
| `apps/student/tasks.py` | 21 | Evaluation receipt e-mail |
| `apps/home/sms.py` | 20 | SMS gateway |
| `apps/home/management/commands/import_legacy_memberships.py` | 214 | Legacy data import — writes users, profiles, memberships |
| `apps/home/management/commands/generate_demo_data.py` | 165 | Demo data |
| `apps/home/management/commands/reconcile_constitutional_categories.py` | 76 | Rewrites membership tier categories |
| `apps/home/management/commands/seed_core_content.py` | 57 | Content seeding |
| `apps/home/management/commands/seed_program_areas.py` | 34 | |
| `apps/home/management/commands/seed_qualifications.py` | 24 | |
| `apps/home/management/commands/seed_legal_pages.py` | 19 | |
| `apps/home/management/commands/expire_lapsed_installment_plans.py` | 14 | **Cron wrapper that lapses memberships** |
| `apps/home/management/commands/seed_membership_tiers.py` | 13 | |
| `apps/home/factories.py` | 41 | Test factories — **nothing imports them** |
| `apps/user/views.py` | 1 | Stub |

`apps/home/factories.py` is worth a decision of its own: 41 statements of test-factory code that no test uses. Either adopt it in the coverage build or delete it.

---

## High-risk untested surfaces, by function

### 1. Membership activation and supersession — `apps/home/services.py`, 36%

**This is the most serious gap in the codebase.**

| Function | Line | Covered |
|---|---:|---|
| `_supersede_prior_active` | 29 | ✗ 37-44 |
| `_close_out` | 47 | ✗ 48-50 |
| `activate_membership` | 53 | ✗ 71-76 |
| `record_installment_payment` | 79 | ✗ 88-93 |
| `assign_membership_tier` | 96 | ✓ |
| `renew_membership` | 108 | partial — happy path only, raise at 116 uncovered |
| `upgrade_to_lifetime` | 120 | ✗ 125-127 |

Only the row-*creating* door is exercised. **Everything that activates a membership, supersedes the previous one, carries the membership number forward, or records an instalment is untested.**

That matters beyond the usual reasons. The `current_active_for` fix delivered in `01630c2` is correct *because* the service layer guarantees at most one ACTIVE row per user — `services.py:37-50`. **That invariant is precisely the code with no test.** We built on a foundation nothing verifies.

### 2. Membership expiry — `expire_lapsed_installment_plans`, 0%

`apps/home/tasks.py:168` plus its management-command wrapper, both 0%. A scheduled job that **mutates membership status** on live data, entirely unexercised.

### 3. Payments — `apps/home/payments.py`, 55%

Missing 26, 29, 39-43, 46, 57-58, 63-64 — the branches, i.e. the method dispatch and failure handling. `initiate_payment` is reached but its alternatives are not. Money movement.

### 4. Authentication — `apps/user/adapter.py`, 24%

The single largest behavioural gap by volume: 160 of 210 statements uncovered, including `pre_social_login`, the domain restriction, `_ensure_employee`, and the whole post-login redirect resolution across subdomains (412-491, 501-547).

**Google OAuth is the only authentication method in the system.** A regression here locks every user out, or admits the wrong ones. The QA-500 sweep tested the *gates*; it never tested the *door*.

### 5. QR badge generation — `apps/qr_manager/models.py`, 58%

`generate_qr` (224-301) and `_qr_watermark_image` (20-60) are entirely uncovered — the badge-minting path, including watermarking and image writes. Also uncovered: `rotate_token` (195-196), `revoke` (199-200), `delete` (309-312), and most of `Supervisor` (397-421).

Badges are **physical artefacts**; a defect here is reprinted, not redeployed. Scan *verification* is now reasonably covered (`views.py` 74%) thanks to the sweep — generation is not.

### 6. Forms — `apps/home/forms.py` 34%, `apps/staff/forms.py` 51%

`home/forms.py` misses 161 of 243 statements. These are the registration and membership-request forms: the validation that decides what reaches the database.

### 7. Views — `apps/home/views.py` 51%, `apps/staff/views.py` 50%

The auth × host matrix sweep proved these *do not 500*. It did not prove they do the right thing. Roughly half of each remains unexercised, concentrated in POST handling and the branches the sweep's GET-only matrix could not reach.

### 8. Scholarship flow — better placed than the rest

`student/views.py` 68%, `student/models.py` 92%, `student/analytics.py` 84%, `student/forms.py` 73%. The best-covered feature area, largely because the sweep exercised the analytics and export paths against an empty dataset.

### 9. Import/export — `import_legacy_memberships`, 0%

214 statements that create users, profiles and memberships from legacy data. One-off by nature, but destructive if wrong, and one of only two places that creates a `UserProfile` outside the new signal.

---

## Proposed priority order — risk × exposure, not percentage

**Recommendation: do not target a coverage percentage.** 59% → 80% can be bought cheaply with `__str__` and property tests while every item below stays untested. The order is by what breaks, how quietly, and how expensive it is to discover late.

| # | Area | Now | Why first |
|---|---|---:|---|
| **1** | `services.py` activation / supersession / instalments | 36% | Money, and the one-ACTIVE-row invariant that the shipped `current_active_for` fix depends on is itself untested |
| **2** | `expire_lapsed_installment_plans` + its command | 0% | A scheduled job that silently mutates membership status on live data |
| **3** | `adapter.py` login, domain restriction, subdomain redirects | 24% | The only way into the system; failure is total, and the sweep tested gates but never the door |
| **4** | `payments.py` branches and failure paths | 55% | Money movement; the happy path is reached, the failures are not |
| **5** | `home/forms.py` registration and membership validation | 34% | Decides what reaches the database at all |
| **6** | `qr_manager` `generate_qr` and watermarking | 58% | Badges are physical artefacts — a defect is reprinted, not redeployed |
| **7** | `home/views.py` / `staff/views.py` POST handling | ~50% | The sweep proved no 500s; correctness of the write paths is unproven |
| **8** | `Membership` model behaviour — `activate`, `is_valid`, expiry arithmetic | inflated by 83% | The 83% is mostly declarations; the arithmetic that decides validity is not asserted |
| **9** | `tasks.py` e-mail and SMS | 0% | Real, but the failure mode is a message not sent rather than data corrupted |
| **10** | `import_legacy_memberships` | 0% | Destructive but one-off and human-supervised |
| — | Seed/demo management commands | 0% | Lowest value; deterministic, re-runnable, and their output is visible immediately |

**Items 1 and 2 together are one coherent first pass:** the membership lifecycle end to end — assign → activate → supersede → instalment → lapse. They share fixtures and are the same risk story.

---

## Testing hazards each build pass must handle

| Area | Hazard |
|---|---|
| QR / PDF | Writes real files. Use the module-level temp `MEDIA_ROOT` pattern from `apps/qr_manager/tests.py`, which the sweep also applied class-scoped in `apps/home/tests.py` |
| PDF assertions | ReportLab compresses content streams (`/ASCII85Decode` then `/FlateDecode`). **A raw-byte search passes or fails for the wrong reason** — decode, as `_pdf_text()` in `apps/home/tests.py` does |
| Staff / student surfaces | Must carry `HTTP_HOST` from `lvh.me`, `staff.lvh.me`, `students.lvh.me`. The client default `testserver` silently routes to `main.urls` and proves nothing |
| Cloudinary | External storage. `generate_qr` writes through the storage backend; needs `MEDIA_ROOT` override or mocking, never live calls |
| SMS gateway | `apps/home/sms.py` makes outbound calls — mock at the boundary |
| django-q2 | ORM broker. Tasks are ordinary callables; **test the function directly rather than through the cluster**, exactly as the backfill migration's tests call `backfill()` directly |
| `UserProfile` | The signal auto-creates one, so `UserProfile.objects.create()` in a fixture raises `IntegrityError` — its pk *is* the user's pk. Fill the auto-created row; to build a profile-less user, delete it explicitly |
| Postgres | Keep it. SQLite masks aborted-transaction poisoning, varchar overflow and `LIKE` case-sensitivity — all live in these paths |
| Membership fixtures | Ordering is load-bearing. `Meta.ordering = ["-created_at"]` plus same-microsecond creation can make "newest" ambiguous; set `created_at` explicitly where a test depends on order |

---

## Branch

This was measured on `feature/qa-500-tests`, since it changes nothing. **A fresh branch is recommended before any test-writing pass** — `coverage/phase-1` off `feature/qa-500-tests` — so the coverage build stays separable from the bug-fix sweep.

**I have not created it.** Say the word.

---

## Decisions needed

1. **Approve the priority order**, or reorder it. My strong recommendation is items 1 and 2 as a single first pass — the membership lifecycle end to end.
2. **Branch:** create `coverage/phase-1` off `feature/qa-500-tests`?
3. **Keep coverage.py?** If so, add `coverage==7.16.0` to `requirements-dev.txt` and commit a `.coveragerc` carrying the `--source`/`--omit` flags used above.
4. **`apps/home/factories.py`** — 41 statements no test imports. Adopt it in the build, or delete it?

🛑 Baseline + proposed order complete — awaiting sign-off on priority.
