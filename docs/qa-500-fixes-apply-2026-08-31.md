# QA 500 fixes — apply pass

**Date:** 2026-08-31
**Branch:** `feature/qa-500-tests`

Executes [`qa_500_report.md`](../qa_500_report.md): Tier A findings fixed with their reproduction tests flipped from documenting the bug to guarding the fix; Tier B findings planned and left unedited.

Tier B plans: [`qa-500-tierB-plans-2026-08-31.md`](qa-500-tierB-plans-2026-08-31.md) — the per-finding detail is there and is not duplicated here.

---

## Commits

```
d214b2d  Add Tier B fix plans awaiting confirmation (#2-#6, #8)
a1771ea  Gate staff profile views on employee record, not bare login (target 1)
c307f84  Fix navbar staff links reversing bare across hosts (#7)
68bb77c  Fix migrate-from-zero: seed the eight assumed tiers (#1)
ba4d2ba  QA 500 sweep: reproduction tests and report (Phase 0/1)
a127807  WIP baseline: pre-existing working-tree edits
```

The Phase 1 baseline (`ba4d2ba`) and the migration fix (`68bb77c`) were committed **before** this pass began, so each fix lands as an independent, revertable diff rather than tangling with the test and documentation additions.

---

## Fixed

### ✅ Finding 7 — navbar staff links reversed bare across hosts — `c307f84`

**Files:** `templates/snippets/navbar.html`, `apps/staff/tests.py`. Test green.

`navbar.html:34` and `:314` reversed `staff:profile_update` bare, inside a guard that is a substring test (`{% if 'staff' in host %}`, `:17` and `:301`). `ALLOWED_HOSTS` admits a whole wildcard domain while `SUBDOMAIN_URLCONFS` maps only the exact `staff` key, so any host merely *containing* "staff" rendered the block while routing to `main.urls` — where the namespace does not exist. `NoReverseMatch`, i.e. a 500, for any logged-in employee.

Both links now use `{% subdomain_url ... 'staff' %}`, which reverses against `apps.staff.site_urls` whatever host rendered the page. That tag is already loaded at `navbar.html:2` and already used this way at `:218` and `:439`, so the fix is in-pattern rather than new machinery.

**Left alone deliberately:** the substring guard itself. It no longer has a 500 behind it, and tightening it would also implicate the sibling `'staff' not in host` blocks at `:231` and `:452`, which this finding does not cover.

**Test change:** from asserting "not a 500" to asserting the page renders 200 *and* the link is absolute to the staff subdomain.

### ✅ Staff mis-gating cluster (target 1) — `a1771ea`

**Files:** `apps/staff/views.py`, `apps/staff/tests.py`. 13 tests green.

`CompleteProfileView`, `ProfileUpdateView` and `ProfileDeleteView` swapped from `LoginRequiredMixin` to `EmployeeRequiredMixin` — the gate `EmployeeListView` and `EmployeeDetailView` already use. The now-unused `LoginRequiredMixin` import was dropped.

**Behaviour change:** an authenticated non-employee now gets **403** where they got 404. Anonymous still gets 302.

**Verified safe for onboarding before editing:** `apps/user/adapter.py:210` calls `_ensure_employee()`, which `get_or_create`s the Employee row at `:166`, *before* redirecting to `staff:complete_profile` at `:213`. The row therefore always exists by the time `CompleteProfileView` is reached.

**Only three of the four views were changed.** `download_staff_qr_code` keeps `@login_required`: `apps/staff/views.py:409-418` documents that admins who are not employees must be able to fetch any employee's badge — *"admins need to fetch any employee's badge, not just their own"* — so employee-gating it would remove a capability its owner-or-admin check grants on purpose. A test pins that exception.

---

## Two corrections to the brief's premises

**1. The mis-gating cluster was never a 500.** The brief's acceptance criterion assumed it was; Phase 1 had already disconfirmed that. All four views fail *closed* with a 404 via `get_object_or_404`. The fix was applied regardless, because the brief pre-specified the exact intended outcome (403 / 302, gated on employee-record existence) and the change does not broaden who can reach the views — it only makes the refusal honest.

**2. Finding 8 should be re-tiered A → B.** The report tagged `student:` namespace registration Tier A. Reading the call sites shows it should not be auto-fixed:

- **It is latent, not live.** Every real call site already works around it deliberately — `apps/home/views.py:1109` uses the bare name plus `_students_subdomain_url`, and `apps/home/context_processors.py:265-272` hardcodes paths with a comment recording that a `student:` reverse *"crashed this context processor — which runs on every page — for every staff/superuser request site-wide"* (2026-08-19).
- **The obvious in-app fix would create two new 500s**, because `templates/student/applicant_dashboard.html:22` and `templates/student/evaluate_application.html:48` rely on the **bare** names, which namespacing would break.
- **The report's own proposed fix is out of scope** — it needs a `main/settings.py` edit, which this brief forbids.

---

## Suite state

**58 tests, 3 failures + 8 errors.** Down from 12 failures before this pass; nothing regressed.

| Group | Count | Status |
|---|---|---|
| Tier B findings (2, 3, 4, 5, 6, 8) | 7 | Expected — reproductions still red, by design |
| Pre-existing `apps/qr_manager/tests.py` fixture errors | 4 | Untouched, as instructed — out of scope |

---

## Finding status

| # | Finding | Tier | State |
|---|---|---|---|
| 1 | migrate-from-zero | B | ✅ Closed (`68bb77c`) |
| 2 | `current_for()` ignores status | B | 🛑 Planned — recommend its own prompt |
| 3 | `renew_membership()` wrong tier | B | 🛑 Same fix as #2 |
| 4 | Badge scan 500 on missing profile | B | 🛑 Planned — needs a display decision |
| 5 | Profile-less user breaks slug save | B | 🛑 Same root cause as #4 |
| 6 | `AlumniProfileDetailView` ungated | B | 🛑 Planned — needs an intent decision |
| 7 | Navbar substring host guard | A | ✅ Fixed, test green (`c307f84`) |
| 8 | `student:` namespace | A→B | 🛑 Latent; fix needs a settings edit |
| — | Staff mis-gating cluster | B | ✅ Fixed, tests green (`a1771ea`) |

No change to migrations, settings, dependencies, or real data in this pass.

---

## Housekeeping

`uon_alumni_fresh_migrate_check` — the throwaway database created to verify the migration fix — has been dropped with approval. `uon_alumni_II` is the only remaining local database and is untouched, still holding its original 13 tier rows.

---

## Decisions needed

1. **Findings 2/3 (`current_for`)** — confirm the per-call-site mapping in the plans doc, especially sites 1, 3, 5 and 6. Sites 2 (QR badge PDF) and 4 (`renew_membership`) are unambiguous. Corporate onboarding was **not** traced and should be walked before this lands. Recommend a dedicated prompt.
2. **Findings 4/5** — guarantee the `UserProfile` invariant, or guard each read site? And what should a profile-less badge display?
3. **Finding 6** — public directory, members-only, or owner-only?
4. **Finding 8** — may `main/settings.py` be edited? If not, it stays open and its two tests remain red as a documented gap.
