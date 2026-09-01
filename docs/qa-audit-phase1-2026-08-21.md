# QA Audit — Phase 1: Audit Ledger

Run on branch `qa-audit-2026-08-21`, local dev DB, read-only — every mutation-capable code path was exercised inside `transaction.atomic()` with a savepoint rolled back at the end; nothing written persisted. Local test fixtures created for the rollback (Article, Event, Chapter, a synthetic Employee+User+UserProfile) existed only inside that same rolled-back transaction. No real alumni/member/production data was touched.

Every route below was hit with Django's test client using the correct `HTTP_HOST` for its subdomain (`lvh.me` / `staff.lvh.me` / `students.lvh.me`), both anonymous and (where relevant) authenticated as the one real local alumni account.

## Route table

| Route | Host | Client | Status | Classification |
|---|---|---|---|---|
| `/` (home) | www | anon | 200 | pass |
| `/uon-alumni-history/` | www | anon | 200 | pass |
| `/uon-alumni-executive-committee/` | www | anon | 200 | pass |
| `/uon-alumni-gallery/` | www | anon | 200 | pass |
| `/uon-alumni-register/` | www | anon | 302 | pass — signed-out visitor sent to login, expected |
| `alumni_detail` | www | owner | 200 | pass |
| `alumni_detail` | www | anon | 200 | pass (public-by-link, by design) |
| `alumni_profile_update` | www | owner | 200 | pass |
| `alumni_profile_update` | www | anon | 302 | pass — login required |
| `alumni_membership_update` | www | owner | 302 | **DATA** — this account's membership is currently `pending`; `AlumniMembershipUpdateView.dispatch()` redirects with "still pending confirmation" for that state by design. Not exercised in the 200 (active-membership) path — no local fixture in that state. Not a defect, a fixture gap.
| `alumni_profile_delete` | www | owner | 200 | pass (GET renders confirm page) |
| `alumni_qr_download` | www | owner | 404 | **DATA** — this alumni has no `qr_code_image` generated; view's own "QR code not found" branch. Fixture gap, not a code defect. |
| `alumni_qr_download` | www | anon | 302 | pass — `@login_required` |
| `membership_analytics` | www | anon | 302 | pass |
| `membership_analytics` | www | signed-in, non-staff | 403 | pass — real gate confirmed live |
| `membership_categories` | www | anon | 200 | pass |
| `uon_alumni_donate` | www | anon | 200 | pass |
| `uon_alumni_scholarship` | www | anon | 200 | pass |
| `uon_alumni_in_memoriam` | www | anon | 200 | pass |
| `uon_alumni_contact_us` | www | anon | 200 | pass |
| `uon_alumni_claim_search` | www | anon | 200 | pass |
| `uon_alumni_claim_verify` | www | anon (no session state) | 302 | pass — no claim in progress, redirects back to search by design |
| `uon_alumni_claim_continue` | www | anon (no session state) | 302 | pass — same as above |
| `uon_alumni_article_list` | www | anon | 200 | pass |
| `uon_alumni_article_detail` | www | anon | 200 | pass |
| `uon_alumni_walk_list` | www | anon | 200 | pass |
| `uon_alumni_walk_detail` | www | anon | 200 | pass |
| `uon_alumni_chapter_list` | www | anon | 200 | pass |
| `uon_alumni_chapter_detail` (no-faculty variant) | www | anon | 200 | pass — faculty-qualified variant not separately exercised (same view, same name, low risk) |
| `uon_alumni_secretariat` | www | anon | 200 | pass |
| `uon_alumni_partners` | www | anon | 200 | pass |
| `uon_alumni_mission_vision` | www | anon | 200 | pass |
| `uon_alumni_downloads` | www | anon | 200 | pass |
| `uon_alumni_careers` | www | anon | 200 | pass |
| `standing_page` (`digital-id`) | www | anon | 200 | pass |
| `alumni_digital_id_apply` | www | owner | 200 | pass |
| `alumni_digital_id_apply` | www | anon | 302 | pass — login required |
| `standing_page` (`alumni-card`, bare, legacy) | www | anon | 301 | pass — permanent redirect, tonight's fix confirmed live in-process |
| `alumni_digital_id_apply_legacy` (slugged, legacy) | www | anon | 301 | pass — same |
| `standing_page` (`corporates`) | www | anon | 200 | pass |
| `sitemap` | www | anon | 200 | pass |
| `robots_txt` | www | anon | 200 | pass |
| `admin:index` | www | anon | 302 | pass — Django's own gate |
| `admin:index` | www | signed-in, non-staff | 302 | pass — Django's own gate (no `is_staff`) |
| `qr:verify` (alumni-linked code, www mount) | www | anon | 200 | pass — lands on minimal `alumni_verify.html`, confirms alumni scan path is correctly scoped |
| `robots_txt` | staff | anon | 200 | pass |
| `staff_login` | staff | anon | 302 | pass (redirects to Google OAuth) |
| `staff_dashboard` | staff | anon | **200** | **CODE — confirmed live.** No auth gate; returns the dashboard to an anonymous request. |
| `all_uon_staff` | staff | anon | 302 | pass — `LoginRequiredMixin` working |
| `staff_detail` (`EmployeeDetailView`) | staff | anon | **200** | **CODE — confirmed live.** Full employee HR detail page served with zero auth. |
| `download_staff_qr_pdf` | staff | anon | 404 | **DATA** — synthetic test employee has no `qr_code_image`; view's own not-found branch. Auth-gate absence is separately confirmed by source read (Phase 0) — a fixture *with* an image would return 200, not proof of a gate. |
| `qr:verify` (employee-linked code, staff mount) | staff | anon | **302 → `staff_detail`** | **CODE — this is the central finding for 2-AUTH.** A scanned staff badge does **not** land on a minimal verification view the way an alumni badge does — `verify_scan()`'s employee branch is `return redirect(qr_code.holder.get_absolute_url())`, i.e. straight to the full, ungated `EmployeeDetailView`. Anyone who scans (or guesses) a staff badge URL reaches complete HR detail with no auth step at all. |
| `robots_txt` | students | anon | 200 | pass |
| `all_uon_students` | students | anon | **200** | **CODE — confirmed live, but inert.** No auth gate; `all_uon_students` view body is `render(request, "student/all_uon_students.html", {})` — empty context, zero DB queries. Ungated, but currently exposes no actual student data (template content not audited for hardcoded PII — recommend a quick manual check, out of scope for this pass). |
| `student_register` | students | anon | 302 | pass — `LoginRequiredMixin` |
| `evaluate_application_list` | students | anon | 302 | pass |
| `evaluate_application_list` | students | signed-in, non-staff | 403 | pass — `StaffOrSuperuserRequiredMixin` confirmed live |
| `applicant_dashboard` | students | anon | 302 | pass |
| `analytics_export` | students | anon | 302 | pass |

No unhandled 500s / tracebacks on any route exercised.

## Findings ledger

| # | Finding | Root cause | Severity | Status |
|---|---|---|---|---|
| 1 | `staff_dashboard` has no auth gate | CODE | Medium — dashboard content not yet inventoried for sensitivity, but principle-of-least-privilege violation regardless | For 2-AUTH decision table |
| 2 | `EmployeeDetailView` (`staff_detail`) has no auth gate | CODE | **High** — full HR detail (confirmed by Phase 0 read: name, unit, contact, employment fields) served to anyone | For 2-AUTH decision table |
| 3 | `download_staff_qr_code` has no auth gate | CODE | Medium-High — downloadable badge PDF, same exposure class as #2 | For 2-AUTH decision table |
| 4 | `staff_detail_fallback` has no auth gate | CODE | Not live-exercised this pass (no incomplete-profile fixture) — confirmed by Phase 0 source read only | For 2-AUTH decision table |
| 5 | **Staff QR scan resolves to the ungated `staff_detail`, not a minimal verification view** | CODE | **High** — this is the actual public/private boundary question from the override, now answered: alumni badges are safely scoped (#`qr:verify`'s own template), staff badges are not (they redirect into finding #2) | For 2-AUTH decision table — likely the highest-priority fix |
| 6 | `all_uon_students` has no auth gate | CODE | Low — confirmed live, but view queries/exposes nothing; only a defense-in-depth concern unless the template itself hardcodes data (not checked) | For 2-AUTH decision table |
| 7 | Badge verification page: multi-line `{# #}` comment | CODE | Low | **Already fixed** (commit `0eb1728`, prior session) — re-confirmed absent from current source, not re-broken |
| 8 | Badge verification page: duplicated surname | DATA | Low, cosmetic | **Already fixed** (commit `0eb1728`) — dedup logic added to `UserProfile.full_name`, re-confirmed present |
| 9 | Badge verification page: membership-validity check | CODE | Was High | **Already fixed** (commit `0eb1728`) — `_alumni_verification_context()` now queries `status=ACTIVE` directly instead of `current_for()`'s most-recent-any-status; re-confirmed present in current source, root-caused fresh per the Override (not attributed to the two closed `MembershipTier` bugs) |
| 10 | Badge verification page: unenforced `noindex` | CODE | Low | **Already fixed** (commit `0eb1728`) — `X-Robots-Tag: noindex` set in `verify_scan()`'s `_render_noindex()` wrapper, re-confirmed present |
| 11 | Membership payment banner (installment box) | DATA-shape, not a bug | — | Confirmed in Phase 0: template correctly guards on `is_installment_plan and balance_due > 0` (real object state), not a count. No action needed. |

Findings 7–11 were already resolved in the prior session (all confirmed present in current source during this pass, not re-discovered as new) — carried forward per the brief's instruction not to treat them as newly discovered, and re-verified rather than assumed.

## Answer to the 2-AUTH investigation's central question

> Confirm exactly what URL a scanned badge resolves to — whether the public scan path lands on `qr:verify` (minimal verification view) or on `staff_detail`.

**Both, depending on holder type** — confirmed by reading `verify_scan()` (`apps/qr_manager/views.py`) and live-exercising both cases:
- **Alumni-linked QR** → renders `qr_manager/alumni_verify.html` directly (the minimal, dedicated page, `noindex`-enforced). Confirmed 200, correct template, no redirect.
- **Employee-linked QR** → `return redirect(qr_code.holder.get_absolute_url())`, i.e. **the full `staff_detail` page** (`EmployeeDetailView`, no auth gate — finding #2). Confirmed live: 302 straight to `staff_detail`.

This is the load-bearing fact for the whole 2-AUTH decision: gating `staff_detail` is not optional or independent of the QR feature — it **is** the actual public surface a staff badge scan lands on.

---

Ledger complete. Stopping here per Phase 1 instructions — no fixes applied. Ready for the 2-AUTH decision table next, on your word.
