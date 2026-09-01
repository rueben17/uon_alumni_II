# QA Audit — Phase 0: Read & Report

Produced 2026-08-21, before any code execution or writes. Every fact below is quoted or directly derived from source (`grep`, direct file reads, `manage.py show_urls`, and targeted shell checks against the local dev DB) — nothing guessed.

---

## 1. `INSTALLED_APPS` (verbatim, `main/settings.py:92-131`)

Django contrib: `admin`, `auth`, `contenttypes`, `sessions`, `messages`, `staticfiles`, `sitemaps`, `redirects`, `sites`.
Third-party: `allauth` (+`account`, `socialaccount`, `socialaccount.providers.google`), `corsheaders`, `crispy_forms`, `crispy_tailwind`, `widget_tweaks`, `django_htmx`, `cloudinary_storage`, `django_extensions`, `phonenumber_field`, `import_export`, `django_q`.
Project apps: **`apps.home`, `apps.user`, `apps.staff`, `apps.student`, `apps.qr_manager`** — five, not the longer list implied by "membership/scholarship/staff badges/employee-HR" as separate apps; those are all features living inside `apps.home` (membership), `apps.student` (scholarship), and `apps.staff` (employee/HR/badges) respectively.

**Correction to context supplied:** `django-subdomains2==4.1.2` is in `requirements.txt` but is **not used anywhere** — confirmed by grepping every `.py` file for `subdomains2`/`import subdomains`: zero hits. The actual mechanism is the project's own `main.middleware.SubdomainRoutingMiddleware` (`MIDDLEWARE` list, `main/settings.py:167`), which sets `request.urlconf`/`request.subdomain` by reading `HTTP_HOST` directly. `ROOT_URLCONF = 'main.urls'`; `SUBDOMAIN_URLCONFS` (`main/settings.py`) maps `None`/`'www'` → `main.urls`, `'staff'` → `apps.staff.site_urls`, `'students'` → `apps.student.urls`.

---

## 2. URL inventory

### Apex / `www` (`main.urls`, also the default when Host has no recognized subdomain)

| Path | Name | View | Methods | Auth |
|---|---|---|---|---|
| `/2005/...` | `admin:*` | Django admin site | GET/POST | staff/superuser (Django's own gate) |
| `/membership-admin/...` | `membership_admin:*` | `apps.home.membership_admin_site` (separate `AdminSite`) | GET/POST | staff/superuser |
| `/accounts/...` | allauth URLs | django-allauth | GET/POST | mixed (allauth's own) |
| `/` + all `uon-alumni-*` paths, `/qr/<uuid:qr_id>/`, `/uon-alumni-page/...`, `/uon-alumni-claim-profile/...` | `home:*` | `include('apps.home.urls', namespace='home')` | GET/POST per view | mixed, mostly public; owner-only gates on profile edit/delete/membership/QR-download |
| `/staff/<rest>`, `/students/<rest>` | `staff_subdomain_redirect`, `students_subdomain_redirect` | `redirect_to_staff_subdomain`/`_students_subdomain` | GET | public (301 redirect only) |
| `/sitemap.xml` | `sitemap` | `django.contrib.sitemaps.views.sitemap` | GET | public |
| `/robots.txt` | `robots_txt` | `TemplateView` (`templates/robots.txt`) | GET | public |
| Admin CRUD (`/2005/<app>/<model>/...`) | `admin:<app>_<model>_*` | Django's generated changelist/add/change/delete/history per registered model | GET/POST | staff/superuser |

Django admin alone generates ~300 near-identical mechanical routes across every registered model — full raw dump available via `manage.py show_urls` if needed; summarized here since it's boilerplate, not hand-written routing.

### `staff.` subdomain (`apps.staff.site_urls` → includes `apps.staff.urls`)

| Path | Name | View | Auth (quoted from class/decorator) |
|---|---|---|---|
| `/robots.txt` | `robots_txt` | `TemplateView` | public |
| `/login/`, `/logout/` | `staff_login`, `staff_logout` | `StaffLoginView`, `staff_logout` | public (login gate itself) |
| `/dashboard/` | `staff_dashboard` | plain function, **no decorator** | **public — no auth gate** |
| `/` | `all_uon_staff` | `EmployeeListView(LoginRequiredMixin, ListView)` | login required |
| `/complete-profile/<uuid:uuid>/` | `complete_profile` | `CompleteProfileView(LoginRequiredMixin, UpdateView)` | login required |
| `/profile/edit/`, `/profile/delete/` | `profile_update`, `profile_delete` | `ProfileUpdateView`/`ProfileDeleteView` (`LoginRequiredMixin`) | login required |
| `/fallback/<uuid:uuid>/` | `staff_detail_fallback` | plain function, **no decorator** | **public — no auth gate** |
| `/<slug:unit_slug>/<slug:name_slug>/<uuid:uuid>/` | `staff_detail` | `EmployeeDetailView(DetailView)` — **no mixin at all** | **public — no auth gate** |
| `/<slug:staff_slug>/<uuid:pk>/download-qr/` | `download_staff_qr_pdf` | `download_staff_qr_code`, plain function, **no decorator** | **public — no auth gate** |
| `/qr/<uuid:qr_id>/` | `qr:verify` | `apps.qr_manager.views.verify_scan` | public by design (badge scan) |
| `/qr-admin/...` | `qr_admin_site:*` | separate `AdminSite`, scoped by `Supervisor` rows | staff, scope-checked |

Confirms the prior production-audit finding verbatim, still true: `EmployeeDetailView`, `staff_detail_fallback`, and `download_staff_qr_code` carry **zero** auth gate — full HR detail and the downloadable badge PDF are publicly reachable by anyone who has/guesses the URL.

### `students.` subdomain (`apps.student.urls`)

| Path | Name | View | Auth |
|---|---|---|---|
| `/robots.txt` | `robots_txt` | `TemplateView` | public |
| `/` | `all_uon_students` | `all_uon_students` (function) | *(not yet confirmed — not checked this pass)* |
| `/register/` | `register` | `StudentRegisterView(LoginRequiredMixin, CreateView)` | login required |
| `/evaluate/`, `/evaluate/<int:pk>/` | `evaluate_application_list`, `evaluate_application` | `EvaluateApplicationView(StaffOrSuperuserRequiredMixin, View)` | staff/superuser |
| `/dashboard/` | `applicant_dashboard` | `ApplicantDashboardView(StaffOrSuperuserRequiredMixin, TemplateView)` | staff/superuser |
| `/dashboard/export/` | `analytics_export` | `ScholarshipAnalyticsExportView(StaffOrSuperuserRequiredMixin, View)` | staff/superuser |

---

## 3. Exact field/URL names — QR, Membership, Scholarship

**QR (`apps.qr_manager.models.QRCode`):** `id` (UUID pk), `employee` (O2O→`Employee`, null), `alumni_profile` (O2O→`home.AlumniProfile`, null), `label`, `token`, `qr_type`, `issued_at`, `expires_at`, `is_active`. Properties: `holder`, `is_expired`, `is_valid`, `status`, `scan_url`. Field is **`qr_code_image`** on the holder (`Employee.qr_code_image` / `AlumniProfile.qr_code_image`) — confirmed **not** `qr_image`, matching the stated trap. URL name: `qr:verify` (`apps/qr_manager/urls.py`), param `qr_id`, query param `t` (not `token` — confirmed from `verify_scan`'s `request.GET.get("t", "")`).

**Membership (`apps.home.models.Membership`):** `id` (UUID pk), `user` (FK), `tier` (FK→`MembershipTier`), `status` (`pending`/`active`/`expired`/`cancelled`/`superseded`), `started_on`, `expires_on` (null = lifetime), `is_lifetime`, `amount_paid`, `next_installment_due`, `payment_frequency`, `membership_number`, `created_at`. Properties: `is_valid`, `is_installment_plan`, `balance_due`, `is_overdue`. Manager: `Membership.objects.current_for(user)` → most-recently-**created** row regardless of status (not "current active" — this exact semantic already caused, and was fixed for, the QR badge false-"Not currently valid" bug).

**Payment banner data-driven finding, confirmed structurally:** the installment-plan status box in `templates/home/alumni_detail.html` is gated on `current_membership.is_installment_plan and current_membership.balance_due > 0` — both computed from real object state (`payment_frequency`, `tier.fee`, `amount_paid`), not a count. A one-off payment membership has `is_installment_plan = False` by construction (`payment_frequency != ONCE`), so it correctly never shows that box — this is DATA-shape, not a template-count bug, matching the framing given. A `Membership.status == 'pending'` box was also already added, so a pending, non-installment membership gets its own status box instead of showing nothing.

**Scholarship — correction:** no model named `Evaluation` exists anywhere in the codebase (confirmed via grep across `apps/`). The real model is **`apps.student.models.ScholarshipApplication`**, which does have `student = models.OneToOneField("Student", on_delete=models.PROTECT, null=True, blank=True, related_name="applicant")` — the "OneToOne to Student" detail is correct, just attached to the wrong model name in the original brief. `county_of_residence = models.CharField(max_length=100, choices=County.choices)` — confirmed **47** choices (`apps.student.models.County`). Position field-name trap (`Position.name` vs `.title`) not yet located — no `Position` model found under that name in `apps.staff` or `apps.student`; flagged as **not verified**, to be confirmed before touching anything that depends on it rather than guessed.

---

## Addendum — MembershipTier "model-level" bugs: both already fixed, not current

The brief's two "likely root of the badge-page validity fault" bugs were checked directly against `apps/home/models.py` and the live DB, and **neither reproduces today**. Both trace to `docs/0.1-identity-decisions.md`, an earlier planning doc — the brief is quoting that doc's snapshot-in-time findings, not the current codebase.

1. **`get_expiry_date()` 30-days-per-month drift — fixed, dated in the code itself.** Current source (`apps/home/models.py:1009-1027`):
   ```python
   def get_expiry_date(self, start_date=None):
       """Calculate expiry date based on tier duration.

       Uses relativedelta, not timedelta(days=months*30) -- the old
       30-days-per-month approximation turned "12 months" into 360 days,
       so every renewal landed ~5-6 days earlier than the true calendar
       anniversary and the drift compounded release over release
       (todo.md 0.3, fixed 2026-08-10). ...
       """
       ...
       return start_date + relativedelta(months=self.duration_months)
   ```
   This already uses `dateutil.relativedelta`, not `timedelta(days=duration_months*30)` — the docstring documents the fix by name and date (2026-08-10, eleven days before this audit). The brief's claimed line number (`models.py:583`) also no longer corresponds to this method — line drift from the same-dated refactor.

2. **`duration_months=0` making Honorary/Corporate accidentally permanent — not true of current data.** Queried directly against the local dev DB:
   ```
   Honorary Member    | tier_type: honorary  | duration_months: 12 | is_lifetime(): False
   Corporate Membership | tier_type: corporate | duration_months: 12 | is_lifetime(): False
   ```
   `docs/0.1-identity-decisions.md:214` records Corporate's `duration_months` as `0` **at the time that doc was written** — it is `12` now. The `is_lifetime()` logic itself (`tier_type == 'life' or duration_months == 0`) is unchanged and is a deliberate, documented contract (the field's own `help_text="0 = lifetime"`), not a code bug — the only thing that was ever wrong was the seeded *data* for these two tiers, and that data has since been corrected.

**Consequence for Phase 1:** if the badge-page validity check misbehaves during the audit, it will **not** be traceable to either of these two causes — both are closed. Any real validity-check issue found should be root-caused fresh against current `Membership`/`MembershipTier` state, not attributed to this stale doc's findings by default.

## Open items before Phase 1

- Full raw `manage.py show_urls` admin-route dump available on request if you want it itemized model-by-model rather than summarized.
- `all_uon_students` view's auth requirement not yet confirmed.
- `Position` model/field trap not yet located — needs confirming before any related fix.
