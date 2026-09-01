# QA Audit Report — `uon_alumni_II`

Branch: `qa-audit-2026-08-21` (off `main`, not merged — awaiting review). Produced across four phases, each with its own detail doc in `docs/`:

- `docs/qa-audit-phase0-2026-08-21.md` — app/URL inventory, exact field/URL names
- `docs/qa-audit-phase1-2026-08-21.md` — full route exercise, findings ledger
- `docs/qa-audit-2auth-proposal-2026-08-21.md` — auth gate table + staff-verify disclosure list, pre-code
- `docs/qa-audit-2auth-apply-2026-08-21.md` — first Apply batch (staff_verify page, download owner/admin scoping, all_uon_students, staff_dashboard/staff_detail_fallback)

This report consolidates the final state after the second Apply batch (Employee-record gating on the four remaining staff-subdomain views).

---

## Final route table — auth status

### Apex / `www`

| Route | Auth |
|---|---|
| Public content pages (home, history, gallery, news, walk, chapters, secretariat, etc.) | public |
| `alumni_detail` | public-by-link (deliberate) |
| `alumni_profile_update`, `alumni_membership_update`, `alumni_profile_delete` | owner-only |
| `alumni_qr_download` | `@login_required` + owner-scoped (`get_object_or_404(..., user=request.user)`) |
| `membership_analytics` | `StaffOrSuperuserRequiredMixin` (anon→302, non-admin→403) |
| `qr:verify` (www mount) | public by design — renders `alumni_verify.html`, `noindex` enforced in code |
| `/2005/...`, `/membership-admin/...` | Django/custom admin gates |

### `staff.` subdomain

| Route | Before this audit | After |
|---|---|---|
| `staff_detail` (`EmployeeDetailView`) | **none** | `EmployeeRequiredMixin` — anon→302, non-employee→403, employee→200 |
| `all_uon_staff` (`EmployeeListView`) | `LoginRequiredMixin` (any authenticated user, including alumni — cross-subdomain session sharing) | `EmployeeRequiredMixin`, same contract as above |
| `staff_dashboard` | **none** | `@employee_required`, same contract |
| `staff_detail_fallback` | **none** | `@employee_required`, same contract |
| `download_staff_qr_code` | **none** | `@login_required` + owner-OR-admin (fetch-then-authorize; non-owner/non-admin → 404, matching `download_alumni_qr_code`'s existence-hiding) |
| `qr:verify` (staff mount) | redirected to `staff_detail` (full HR detail, then-ungated) | renders `staff_verify.html` directly — minimal disclosure, `noindex` enforced, never touches the gated detail view |
| `staff_login`/`staff_logout`, `robots.txt` | public | unchanged |
| `qr-admin/...` | separate `AdminSite`, `Supervisor`-scoped | unchanged |

### `students.` subdomain

| Route | Before | After |
|---|---|---|
| `all_uon_students` | **none** (inert — empty context, no query) | `@login_required` (per explicit amendment; left un-employee-scoped since the view exposes nothing today) |
| `student_register` | `LoginRequiredMixin` | unchanged |
| `evaluate_application_list`/`evaluate_application`, `applicant_dashboard`, `analytics_export` | `StaffOrSuperuserRequiredMixin` | unchanged, confirmed live (anon→302, non-admin→403) |

---

## Findings ledger — final status

| # | Finding | Root cause | Status |
|---|---|---|---|
| 1 | `staff_dashboard` — no auth gate | CODE | **Fixed** — `@employee_required` |
| 2 | `EmployeeDetailView` (`staff_detail`) — no auth gate, full HR detail public | CODE | **Fixed** — `EmployeeRequiredMixin` |
| 3 | `download_staff_qr_code` — no auth gate | CODE | **Fixed** — `@login_required` + owner-or-admin |
| 4 | `staff_detail_fallback` — no auth gate | CODE | **Fixed** — `@employee_required` |
| 5 | Staff QR scan resolved to the ungated `staff_detail` instead of a minimal page | CODE | **Fixed** — new `staff_verify.html` + `_staff_verification_context()`, mirroring the alumni pattern, not unified with it |
| 6 | `all_uon_students` — no auth gate | CODE, but inert (empty context) | **Fixed** — `@login_required` (deliberately not employee/student-scoped; nothing to protect today, gated defensively) |
| 7 | Badge page: multi-line `{# #}` comment leak | CODE | Already fixed prior session (`0eb1728`), re-confirmed present |
| 8 | Badge page: duplicated surname | DATA | Already fixed prior session, re-confirmed present |
| 9 | Badge page: membership-validity check | CODE | Already fixed prior session — root-caused fresh per this audit's override (not attributed to the two closed `MembershipTier` bugs, which were confirmed stale/already-resolved in Phase 0) |
| 10 | Badge page: unenforced `noindex` | CODE | Already fixed prior session, re-confirmed present |
| 11 | Membership payment banner | DATA-shape, not a bug | Confirmed correct in Phase 0 — template guards on real object state, not a count |
| 12 | `EmployeeListView`'s `LoginRequiredMixin` let any authenticated user (including alumni, via shared session cookie domain) into the staff directory | CODE, discovered during 2-AUTH investigation | **Fixed** — replaced with `EmployeeRequiredMixin` |

All fixes verified live against the test client, not assumed from source reading alone (see per-fix Verify sections in the `docs/qa-audit-*` files and below).

---

## 2-AUTH — what was built

- **`apps/user/mixins.py`** (new additions, same module as the existing `StaffOrSuperuserRequiredMixin`): `user_is_employee(user)` predicate (`is_authenticated and hasattr(user, "employee")`), `EmployeeRequiredMixin` (CBV), `employee_required` (FBV decorator) — both anon→302, authenticated-non-employee→403, matching `StaffOrSuperuserRequiredMixin`'s real (live-tested) behavior contract, not its docstring's inaccurate claim that anonymous also gets 403.
- **`templates/qr_manager/staff_verify.html`** (new) + **`_staff_verification_context()`** (`apps/qr_manager/views.py`) — parallel to the alumni verification page, not unified with it. Discloses: name, Active/Inactive status, rank/position (`academic_rank` display or `Position.title` — confirmed not `.name`), unit name. Nothing else.
- **`verify_scan()`'s employee branch** repointed from `redirect(qr_code.holder.get_absolute_url())` to rendering `staff_verify.html` through the same `_render_noindex()` wrapper the alumni branch uses. `QRCode` queryset's `select_related` extended to cover the new lookups, avoiding an N+1 pattern on this page (the same bug class found and fixed elsewhere in this codebase).
- **`download_staff_qr_code`** — owner OR admin, not bare login: fetches unfiltered, authorizes against `request.user == employee.user or request.user.is_staff or request.user.is_superuser`, returns 404 (not 403) to a non-owner/non-admin to match `download_alumni_qr_code`'s existence-hiding behavior.
- **Four views regated** to `EmployeeRequiredMixin`/`employee_required`: `staff_detail`, `all_uon_staff` (replacing its former `LoginRequiredMixin`), `staff_dashboard`, `staff_detail_fallback`.

**Verify, quoted:**

| Check | anon | authenticated alumnus, no Employee | authenticated employee |
|---|---|---|---|
| `staff_detail` | 302 | 403 | 200 |
| `all_uon_staff` | 302 | 403 | 200 |
| `staff_dashboard` | 302 | 403 | 200 |
| `staff_detail_fallback` | 302 | 403 | 200 |

Dual-role user (has both `AlumniProfile` and `Employee`): 200 on all four — not blocked. `qr:verify` staff scan (anon): 200 on `staff_verify.html`, `X-Robots-Tag: noindex`. `qr:verify` alumni scan (anon): 200 on `alumni_verify.html`, unaffected. All test fixtures ran inside a rolled-back `transaction.atomic()` savepoint; the one filesystem QR-image write was explicitly deleted afterward. Nothing persisted to the dev DB or disk.

---

## Residual backlog (not fixed, flagged for awareness)

- **`Membership.objects.current_for(user)`** — returns the most-recently-created row regardless of status. Already worked around at the one call site that needed it (the badge verification page, tonight). Every *other* call site using `current_for()` for "the member's current standing" (profile page badges, membership-update flow, admin displays) inherits the same latent ambiguity — a member with a still-valid ACTIVE membership who starts a renewal will show the newer PENDING row everywhere else too, not just on the badge page. Not touched this audit (out of scope — view/template layer only, and this is a manager-method semantic question with several legitimate call sites, not a single-file fix).
- **`all_uon_students`** — now login-gated, but the view itself is still inert (`context = {}`, zero queries, unaudited template). Gating it closes the "could leak data later" concern without knowing whether the template currently hardcodes anything worth checking — worth a quick manual look before this view is ever built out further.
- **Phase 0 correction on record:** `Position` model does exist (`apps/staff/models.py:151`, field `title`) — Phase 0 initially reported it as unverified; corrected during the 2-AUTH read-first pass, now used correctly in `_staff_verification_context()`.

---

## Summary for review before merge

**Done and verified live:**
- Full route/auth inventory (Phase 0), full route exercise with no unhandled 500s (Phase 1)
- Staff QR badge scan no longer exposes ungated full HR detail — the actual highest-severity finding of this audit
- Four staff views properly employee-scoped (not just login-scoped) via a new, minimal, DRY predicate/mixin/decorator trio mirroring the existing admin-gate pattern
- `download_staff_qr_code` tightened to owner-or-admin with existence-hiding behavior matching its alumni sibling
- `all_uon_students` gated defensively
- All four previously-known badge-page issues + the payment banner re-confirmed (not re-broken, not newly discovered)

**Still open, needs your call:**
- The `current_for()` latent ambiguity at other call sites (listed above) — no fix proposed, flagged only
- `all_uon_students`'s template not manually reviewed for hardcoded content

**Not merged.** Branch `qa-audit-2026-08-21` is ready for your review; merge is your call, not mine.
