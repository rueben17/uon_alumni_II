# QA Audit — 2-AUTH: Apply + Verify

Applied on branch `qa-audit-2026-08-21`. Scope confirmed clean — only `apps/qr_manager/views.py`, `apps/staff/views.py`, `apps/student/views.py`, and the new `templates/qr_manager/staff_verify.html`. No models/migrations/settings/middleware touched.

## Changes applied, in order

1. **`templates/qr_manager/staff_verify.html`** (new) — mirrors `alumni_verify.html`'s structure and disclosure level exactly. Shows: display name, an Active/Inactive status badge (green/red, same styling as alumni's validity badge), Rank/Position, and Unit (only if set).

2. **`_staff_verification_context()`** (`apps/qr_manager/views.py`), parallel to `_alumni_verification_context()`, not unified with it:
   - `rank_or_position`: `employee.get_academic_rank_display()` if `academic_rank` is set, else `employee.position.title` (confirmed **not** `.name` — `Position` model read directly, `apps/staff/models.py:160`) if a `Position` is assigned, else `None`.
   - `unit_name`: whichever of `department` / `service_unit` / `research_unit` is actually set (mutually exclusive by `staff_track`), `.name` on whichever one it is.
   - `status_label`: "Active" / "Inactive" from `employee.is_active`.

3. **`verify_scan()`'s employee branch repointed** — was `return redirect(qr_code.holder.get_absolute_url())`, now:
   ```python
   return _render_noindex(
       request, "qr_manager/staff_verify.html", _staff_verification_context(qr_code.employee)
   )
   ```
   Also extended the initial `QRCode` queryset's `select_related` to cover `employee__user__profile`, `employee__position`, `employee__department`, `employee__service_unit`, `employee__research_unit`, and `alumni_profile__user__profile` — avoiding the same N+1-per-scan pattern already found and fixed elsewhere in this codebase tonight. `redirect` import removed from this file (no longer used anywhere in it).

4. **`download_staff_qr_code`** (`apps/staff/views.py`) — Amendment 1, owner OR admin, not bare `@login_required`:
   ```python
   @login_required
   def download_staff_qr_code(request, staff_slug, pk):
       employee = get_object_or_404(Employee, slug=staff_slug, id=pk)

       if request.user != employee.user and not (request.user.is_staff or request.user.is_superuser):
           return HttpResponse("QR code not found", status=404)

       if not employee.qr_code_image:
           return HttpResponse("QR code not found", status=404)
   ```
   Object fetched unfiltered (not `get_object_or_404(..., user=request.user)` like the alumni sibling) so admins can bypass the owner check; unauthorized requests get `404` (matching `download_alumni_qr_code`'s existence-hiding behavior), not `403`. Predicate is `is_staff or is_superuser` — the same one `StaffOrSuperuserRequiredMixin` / `_is_admin_user` use — inlined rather than importing that private helper across app boundaries into a plain FBV.

5. **`all_uon_students`** (`apps/student/views.py`) — Amendment 2, bare `@login_required` added.

6. **`staff_dashboard`** and **`staff_detail_fallback`** (`apps/staff/views.py`) — bare `@login_required` added, as originally proposed (unaffected by the `staff_detail` pause below).

## Verify results (quoted, not assumed)

| Check | Result |
|---|---|
| Staff badge scan (anon) | `200` on `staff_verify.html`, `X-Robots-Tag: noindex` present, shows display name / "Lecturer" (academic_rank) / "Active" badge — no redirect into full detail |
| Alumni badge scan regression | still `200` on `alumni_verify.html`, unaffected |
| `staff_dashboard` (anon) | `302 → /accounts/login/?next=/dashboard/` |
| `staff_detail_fallback` (anon) | `302 → /accounts/login/?next=/fallback/...` |
| `download_staff_qr_code` (anon) | `302` (login gate fires before ownership check) |
| `download_staff_qr_code` (owner, authenticated) | `200` |
| `download_staff_qr_code` (non-owner, non-admin) | `404` — matches the alumni sibling exactly, not 403 |
| `download_staff_qr_code` (staff/superuser) | `200` — correctly bypasses the owner filter |
| `all_uon_students` (anon) | `302 → /accounts/login/?next=/` |
| `staff_detail` (anon) | still `200` — confirmed **unchanged**, deliberately left ungated |

Test fixtures (synthetic employee/users/QR image) ran inside a rolled-back `transaction.atomic()` savepoint; the one filesystem-level QR image write (`FileField` storage bypasses DB transactions) was explicitly cleaned up afterward. Nothing persisted.

## Still open

`staff_detail` (`EmployeeDetailView`) remains ungated. The pre-apply gate finding stands: `SESSION_COOKIE_DOMAIN = f".{SUBDOMAIN_DOMAIN}"` (`main/settings.py:592`) shares one session across every subdomain, so bare `LoginRequiredMixin` would let any logged-in alumnus through, not just staff. Two options presented, awaiting choice:

- **Option 1** — `StaffOrSuperuserRequiredMixin` (`apps.user.mixins`; `is_authenticated and (is_staff or is_superuser)`). Simple, already imported elsewhere. Caveat: gates on Django *admin* staff status, not "has an Employee record" — would block ordinary (non-admin) employees from the directory too, a regression against `EmployeeListView`'s current looser behavior.
- **Option 2** — an employee-record check (`hasattr(request.user, 'employee')`, the same accessor `EvaluateApplicationView` already relies on via `request.user.employee`). Correctly scopes to "any real UoN employee." Not an existing mixin class — a new one-line `test_func`/dispatch check, same shape as `StaffOrSuperuserRequiredMixin` but a different predicate.

Everything else in this Apply batch is complete; this one gate is the only thing left before this phase closes.
