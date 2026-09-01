# QA Audit — 2-AUTH: Read First + Propose

Produced 2026-08-21, on branch `qa-audit-2026-08-21`, before any view/template code was written. Everything below is quoted or directly derived from source — nothing guessed.

---

## Read First (quoted from source)

**1. Alumni scan path (the pattern being mirrored)**

`verify_scan()` (`apps/qr_manager/views.py:134-137`):
```python
if qr_code.alumni_profile_id:
    return _render_noindex(
        request, "qr_manager/alumni_verify.html", _alumni_verification_context(qr_code.alumni_profile)
    )
```
`_render_noindex()` (lines 28-39) wraps `render()` and unconditionally sets `response["X-Robots-Tag"] = "noindex"` — enforced in code, not just the template's `<meta name="robots" content="noindex">`.

`_alumni_verification_context()` (lines 42-95) discloses exactly: `display_name` (`alumni_profile.user.profile.display_name`), `tier_category` (coarse `MembershipTier.tier_type` display, e.g. "Life Member" — deliberately *not* the specific named tier, since that would reveal what was paid), `validity_label` ("Valid" / "Life member" / "Expired on {date}" / "Not currently valid"), `member_since` (month/year only), `duration` (humanized). Membership is looked up as `Membership.objects.filter(user=..., status=ACTIVE).order_by("-created_at").first()` — today's own fix, not `current_for()`.

`templates/qr_manager/alumni_verify.html`: standalone document (no site chrome, no navbar/footer), a single card showing name (h1), a colored validity badge, and a membership/since/duration block. Nothing else.

**2. Employee branch — the line being replaced**

`verify_scan()` (`apps/qr_manager/views.py:139`):
```python
    return redirect(qr_code.holder.get_absolute_url())
```
This is the last line of the function, reached whenever `qr_code.alumni_profile_id` is falsy — i.e. every employee-linked badge, unconditionally, straight to `EmployeeDetailView` via `get_absolute_url()`.

**3. Real `Employee` fields (`apps/staff/models.py`)** — correcting a Phase 0 gap: **`Position` does exist** (line 151), it was simply missed in that earlier pass. Confirmed now by direct read:
- `academic_rank` — `CharField(choices=AcademicRank.choices, blank=True, default="")`, e.g. "Senior Lecturer", "Professor" (line 236-243)
- `position` — `ForeignKey(Position, ...)`, and **`Position.title`** (line 160) is the display field — confirmed **not** `.name`, the exact trap named in the brief
- `department` / `service_unit` / `research_unit` — three mutually-exclusive `ForeignKey`s (`SET_NULL`, nullable) depending on `staff_track`
- `is_active` — `BooleanField(default=True)` (line 313)
- `qr_code_image` (line 318) — confirmed `qr_code_image`, not `qr_image`, the other named trap
- Personal identity is **not** on `Employee` at all — per its own docstring (line 184-188): "Personal data (name, honorific, DOB, photo, national ID, contact) lives on UserProfile ... access it through `self.user.profile.*`." So name/honorific/photo come from `UserProfile`: `honorific`, `given_name`, `middle_name`, `family_name`, `photo` (`ImageField`), `display_name` (property), `display_photo_url` (property) — same fields `_alumni_verification_context()` already reads via `.user.profile.*`.

**4. Existing auth mixins to reuse**

- `EmployeeListView(LoginRequiredMixin, ListView)` (`apps/staff/views.py:111`) — the sibling pattern for `staff_detail`/`staff_dashboard`/`staff_detail_fallback`.
- `download_alumni_qr_code` (`apps/home/views.py:647-648`): `@login_required` decorator on a plain function — the sibling pattern for `download_staff_qr_code` (also an FBV).

---

## Propose

### A. Gate table

| Endpoint | Current | Proposed gate | Mirrors | Owner-scoping wanted? |
|---|---|---|---|---|
| `staff_detail` (`EmployeeDetailView`) | none | `LoginRequiredMixin` | `EmployeeListView` | No — any signed-in user (matches the directory it's linked from, which is already just login-gated, not owner-only) |
| `staff_dashboard` (FBV) | none | `@login_required` | same pattern as `alumni_qr_download` | No |
| `staff_detail_fallback` (FBV) | none | `@login_required` | same | No |
| `download_staff_qr_code` (FBV) | none | `@login_required` | `alumni_qr_download` exactly | **Flagged:** `alumni_qr_download` is owner-scoped in addition to `@login_required` (`get_object_or_404(..., user=request.user)`) — this download currently takes no such check. Recommend the same tightening (any signed-in staff can currently download *any* employee's badge PDF once login-gated, not just their own). Needs confirmation before applying — one line more than a bare decorator copy. |
| `all_uon_students` (FBV) | none | none — **no gate proposed** | — | The view queries and renders nothing (`context={}`); gating it would only change who can see an already-empty page. Recommend leaving public unless the template itself has content worth restricting (not audited this pass). |

Public, unchanged, not gated: `qr:verify`, `robots.txt`, `staff_login`/`staff_logout`, the two subdomain-redirect views, `sitemap.xml`.

### B. Minimal staff-verify disclosure list

Mirroring `alumni_verify.html`'s level exactly (identity + affiliation + a status word — no contact info, no dates beyond what's already coarse):

- **Name** — `employee.user.profile.display_name`
- **Rank / Position** — `employee.academic_rank` display if set, else `employee.position.title` if set, else omitted (mirrors alumni's `tier_category|default:"..."` pattern)
- **Unit** — whichever of `department` / `service_unit` / `research_unit` is set (by `staff_track`), name only
- **Status badge** — "Active" / "Inactive" from `employee.is_active`, styled the same green/red as alumni's validity badge

**Not shown** (matches alumni's exclusion of exact tier/payment amount): `staff_id`, `employment_type`, `employed_on`, any contact field, `national_id`, DOB — none of these are on `Employee` for personal data anyway (they're on `UserProfile`, which this page won't touch beyond `display_name`).

---

Awaiting sign-off on A and B before any view/template code is written.
