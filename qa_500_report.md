# QA 500 sweep — Phase 1 report

**Date:** 2026-08-31
**Branch:** `feature/qa-500-tests` (off `qa-audit-2026-08-21`)
**Baseline commit:** `a127807` — *WIP baseline: pre-existing working-tree edits*, committing the four already-modified source files as-is, contents unchanged.

Phase 1 reproduces and diagnoses only. **No source, settings, migration, dependency or real-data change was made.** The only files written are the four apps' existing `tests.py` (appended to, not restructured) and this report.

## How to run

```
manage.py test apps --settings=nomig_settings --noinput
```

with the throwaway `nomig_settings.py` on `PYTHONPATH` — see [Finding 1](#finding-1--migrate-from-zero-fails-so-the-test-database-cannot-be-built), which is why that shim is needed at all. It lives in the session scratchpad, **outside the repo**, and does nothing but `from main.settings import *` plus a `MIGRATION_MODULES` stub. Local Postgres throughout; Neon is unreachable from this configuration.

Current tally: **56 tests, 3 failures + 9 errors.** Eight of those twelve are the reproductions below. Four are pre-existing breakage in `apps/qr_manager/tests.py` — see [Pre-existing test debt](#pre-existing-test-debt).

Every request-level test names an explicit `HTTP_HOST` from the `lvh.me` family, because `SUBDOMAIN_DOMAIN` is `lvh.me` under test and the client default `testserver` would route everything to `main.urls`.

---

## Findings

| # | Finding | Route / trigger | Auth | Host | Tier |
|---|---|---|---|---|---|
| 1 | `migrate` from zero fails | any fresh DB | — | — | B |
| 2 | `current_for()` ignores status | 6 call sites | — | — | B |
| 3 | `renew_membership()` renews the wrong tier | `services.py:108` | — | — | B |
| 4 | Badge scan 500s when the holder's profile row is gone | `qr/<uuid>/` | anonymous | staff + public | B |
| 5 | Cannot attach an `AlumniProfile`/`Employee` to a profile-less user | admin add form | superuser | any | B |
| 6 | `AlumniProfileDetailView` is ungated | `uon-alumni-profile/<slug>/<uuid>/` | anonymous | public | B |
| 7 | Navbar's host guard is a substring test | `/` | employee | `*staff*.lvh.me` | A |
| 8 | `student:` namespace is never registered | `{% subdomain_url %}` | — | any | A |

---

### Finding 1 — `migrate` from zero fails, so the test database cannot be built

**Trigger:** any fresh database — the test runner, a new deployment, a new developer checkout.
**Test:** none. A migration failure cannot be captured by a test that itself needs the database. Evidence is the runner output below.

```
File "apps/home/migrations/0016_seed_tier_benefits.py", line 123, in seed
    raise RuntimeError(f"Expected MembershipTier rows missing, aborting seed: {missing}")
RuntimeError: Expected MembershipTier rows missing, aborting seed:
{'Gold Life Member', 'Bronze Life Member', 'Silver Life Member',
 'Diamond Life Membership', 'Student Annual Membership',
 'Platinum Life Membership', 'Full Annual Member', 'Corporate Membership'}
```

**Root cause.** `apps/home/migrations/0016_seed_tier_benefits.py:120-123`:

```python
    tiers_by_name = {t.name: t for t in MembershipTier.objects.filter(name__in=TIER_ORDER)}
    missing = set(TIER_ORDER) - set(tiers_by_name)
    if missing:
        raise RuntimeError(f"Expected MembershipTier rows missing, aborting seed: {missing}")
```

`TIER_ORDER` (migration lines 1-5 of its own definition) lists ten tier names. The migration `get_or_create`s only two of them — `Associate` and `Registered`. **No migration anywhere creates the other eight.** `apps/home/migrations/0001_initial.py:111` only does `CreateModel` for `MembershipTier`. Those eight rows exist in production because somebody created them by hand, so the migration graph has never actually been run from zero against an empty database.

**Tier B.** **Proposed fix:** make `0016` self-sufficient by `get_or_create`-ing all ten `TIER_ORDER` names with their real fee/type/duration values, rather than assuming eight of them. The `if missing: raise` guard can then stay as a genuine assertion instead of a tripwire that always fires. This is a behaviour change to a shipped migration, so it needs a deliberate decision about whether to edit `0016` in place or add a new migration ahead of it.

> **Note on scope.** Because this blocks the sanctioned test strategy outright, it was raised before proceeding, and the agreed workaround was a throwaway no-migrations settings module in the scratchpad, outside the repo. That workaround means data migrations do **not** run under test, so any 500 that depends on migration-seeded data would not reproduce here. None of the findings below depend on seeded data.

---

### Finding 2 — `current_for()` returns the newest row regardless of status

**Trigger:** a member with a valid `ACTIVE` membership who has since raised a renewal or upgrade request (a newer `PENDING` row) — the ordinary renewal flow.
**Tests:** `apps.home.tests.CurrentForStatusTests.test_current_for_prefers_the_active_membership` — **fails**:

```
AssertionError: <Membership: member@example.com - Student Annual Membership (Pending)>
            != <Membership: member@example.com - Gold Life Member (Active)>
```

**Root cause.** `apps/home/models.py:1373-1381`:

```python
class MembershipManager(models.Manager):
    def current_for(self, user):
        """Most recent membership row for a user, active or otherwise -- ..."""
        return self.filter(user=user).first()
```

with `apps/home/models.py:1500-1501`:

```python
    class Meta:
        ordering = ["-created_at"]
```

No status filter. The docstring is candid about this, but six of the seven call sites read it as "the membership this person currently holds".

**All call sites:**

| Site | Expression | Consequence |
|---|---|---|
| `apps/home/views.py:538` | `current_membership = Membership.objects.current_for(self.object.user)` | Profile page shows a pending renewal as the current standing |
| `apps/home/views.py:683` | `current_membership = Membership.objects.current_for(alumni.user)` | **Wrong tier and validity printed onto the QR badge PDF** — a physical artefact |
| `apps/home/views.py:839` | `current_membership = Membership.objects.current_for(request.user)` | Membership-update flow reads the wrong starting tier |
| `apps/home/services.py:114` | `current = Membership.objects.current_for(user)` | See [Finding 3](#finding-3--renew_membership-renews-at-the-wrong-tier) |
| `apps/home/admin.py:92` | `membership = Membership.objects.current_for(obj.user)` | Export column misreports standing |
| `apps/home/admin.py:560` | `membership = Membership.objects.current_for(obj.user)` | Admin list column misreports standing |

**Already correct, and pinned so a fix cannot weaken it** — `apps/qr_manager/views.py:64-66`:

```python
    membership = Membership.objects.filter(
        user=alumni_profile.user, status=Membership.Status.ACTIVE
    ).order_by("-created_at").first()
```

covered by `apps.home.tests.CurrentForStatusTests.test_qr_manager_status_filtered_lookup_stays_correct`, which **passes**.

**Tier B.** **Proposed fix:** give the manager two explicit methods rather than overloading one — `current_for(user)` filtered to `status=ACTIVE` (what five of the six call sites actually mean), and a separately named `latest_request_for(user)` preserving today's unfiltered behaviour for the one place that wants "is there a renewal in flight". Then update each call site deliberately. Not a one-line change: `views.py:839`'s membership-update flow may genuinely want the pending row.

---

### Finding 3 — `renew_membership()` renews at the wrong tier

**Trigger:** as Finding 2 — an `ACTIVE` Gold Life membership with a newer `PENDING` Student Annual row.
**Test:** `apps.home.tests.RenewMembershipTierTests.test_renewal_uses_the_active_tier` — **fails**:

```
AssertionError: <MembershipTier: Student Annual Membership - KES 500.00>
            != <MembershipTier: Gold Life Member - KES 100000>
```

**Root cause.** `apps/home/services.py:114-117`:

```python
    current = Membership.objects.current_for(user)
    if current is None:
        raise ValueError("No current membership to renew -- use assign_membership_tier() for a first-time grant.")
    return assign_membership_tier(user, current.tier, payment_frequency=payment_frequency)
```

A Gold Life Member (KES 100,000) who asks to renew is silently renewed as a Student Annual Member (KES 500). This is a financial correctness bug, not merely a display one, and it is the sharpest reason to treat Finding 2 as more than cosmetic.

**Tier B.** **Proposed fix:** covered by Finding 2's fix — this call site wants the `ACTIVE` row specifically.

---

### Finding 4 — anonymous badge scan 500s when the holder's `UserProfile` row is gone

**Route:** `qr/<uuid:qr_id>/?t=<token>` — mounted on both `main.urls` and `apps.staff.site_urls`.
**Auth:** anonymous. **Host:** `staff.lvh.me` (and the public host for alumni badges).
**Test:** `apps.qr_manager.tests.VerifyScanMissingProfileTests.test_scan_survives_a_holder_whose_profile_row_is_gone` — **errors**:

```
File "apps/qr_manager/views.py", line 133, in _staff_verification_context
    "display_name": employee.user.profile.display_name,
apps.user.models.User.profile.RelatedObjectDoesNotExist: User has no profile.
```

**Root cause.** `apps/qr_manager/views.py:133`, and its alumni twin at `views.py:90`:

```python
        "display_name": employee.user.profile.display_name,
```
```python
        "display_name": alumni_profile.user.profile.display_name,
```

Both build a plain Python dict, so `RelatedObjectDoesNotExist` propagates and becomes a 500. Note the asymmetry that makes this easy to miss: the same attribute read *inside a template* is silenced, because `ObjectDoesNotExist` sets `silent_variable_failure = True`. Pages that render `user.profile.*` in markup degrade to blank; these two, which read it in Python, do not.

Nothing guarantees a `UserProfile` exists. It is created in exactly two places — `apps/user/adapter.py:111` (`UserProfile.objects.get_or_create(user=user, defaults=defaults)`, social login) and `apps/home/management/commands/import_legacy_memberships.py:214`. `UserManager.create_user`/`create_superuser` (`apps/user/models.py:25-47`) do not. Several admin call sites already defend against exactly this, e.g. `apps/home/admin.py:80`:

```python
        return obj.user.profile.display_name if hasattr(obj.user, 'profile') else ''
```

**Reachability.** Because of [Finding 5](#finding-5--an-employeealumniprofile-cannot-be-attached-to-a-profile-less-user), a holder record cannot be *created* for a profile-less user, so this is reached when the `UserProfile` is removed *after* the badge was minted — an admin deleting the profile row, or a cascade. The printed badge keeps resolving regardless. Narrower than "any profile-less user", but it is a public, unauthenticated 500 on a URL printed onto physical passes.

**Tier B.** **Proposed fix:** guard both context builders and decide what a badge should show for a holder with no profile — most likely fall back to `employee.user.email` or the QR's own `label`, rather than 500ing or leaking a blank card. A decision about disclosure, hence Tier B rather than A.

The happy path is pinned by `test_scan_works_while_the_profile_exists`, which **passes** and also asserts `X-Robots-Tag: noindex` still holds.

---

### Finding 5 — an `AlumniProfile`/`Employee` cannot be attached to a profile-less user

**Trigger:** Django admin's *add AlumniProfile* (or *add Employee*) form, choosing a user created by `manage.py createsuperuser` or by hand in the admin.
**Auth:** superuser. **Host:** any.
**Test:** `apps.home.tests.MissingUserProfileTests.test_alumni_profile_can_be_created_for_a_profileless_user` — **errors**:

```
File "apps/home/models.py", line 1091, in get_alumni_profile_slug
    profile = instance.user.profile
apps.user.models.User.profile.RelatedObjectDoesNotExist: User has no profile.
```

**Root cause.** `apps/home/models.py:1089-1092`:

```python
def get_alumni_profile_slug(instance):
    """Reads through UserProfile, same pattern as apps/staff/models.py's
    get_employee_slug -- AlumniProfile no longer holds name data itself
    (docs/rebuild-schema.md)."""
    profile = instance.user.profile
```

and the identical shape at `apps/staff/models.py:28`:

```python
    profile = instance.user.profile
```

Both are `populate_from` callables for an `AutoSlugField`, so the unguarded read happens inside `save()`. The exception surfaces as a 500 on the admin form, not a validation error.

Two supporting tests **pass** and document the precondition: `test_created_superuser_has_no_profile` (a `createsuperuser` account genuinely has none) and `test_profile_access_raises_object_does_not_exist` (pinning the exception type that every unguarded `user.profile` read propagates — `apps/home/views.py:672` and `:697`, `apps/staff/views.py:424` and `:436`, `apps/qr_manager/views.py:90` and `:133`).

**Tier B.** **Proposed fix:** the durable one is to guarantee the invariant — create `UserProfile` in `UserManager.create_user`, or via a `post_save` signal on `User`, so "every User has a profile" becomes true rather than merely usual. That retires Findings 4 and 5 together and lets the `hasattr` guards scattered through the admin go. A narrower alternative is to make the two slug helpers tolerate a missing profile, but that leaves the other six unguarded read sites live.

---

### Finding 6 — `AlumniProfileDetailView` is ungated

**Route:** `uon-alumni-profile/<slug>/<uuid>/` (`home:alumni_detail`).
**Auth:** anonymous. **Host:** `lvh.me`.
**Test:** `apps.home.tests.AlumniProfileDetailAccessTests.test_anonymous_visitor_cannot_read_a_members_profile` — **fails**:

```
AssertionError: 200 == 200 : AlumniProfileDetailView served a member's profile,
including membership standing and alternate e-mail, to an anonymous visitor.
```

**Root cause.** `apps/home/views.py:515`:

```python
class AlumniProfileDetailView(DetailView):
```

No `LoginRequiredMixin`, no owner check — compare the sibling views at `views.py:780`, `:803` and `:905`, all of which carry `LoginRequiredMixin`. `get_context_data` (`views.py:537-540`) then attaches:

```python
        current_membership = Membership.objects.current_for(self.object.user)
        context["current_membership"] = current_membership
        context["alt_email"] = EmailAddress.objects.filter(user=self.object.user, primary=False).first()
```

so an anonymous visitor with a profile URL gets the member's tier and standing plus their non-primary e-mail address, and the template carries payment history. Not a 500 — a disclosure. It is reported here because the sweep was explicitly across the auth × host matrix, and this is the matrix cell that misbehaves.

Note the docstring at `views.py:517` calls it a "Public alumni profile page", so *some* public exposure may be intended. What is almost certainly not intended is the alternate e-mail address and payment history.

**Tier B.** **Proposed fix:** decide the intended audience first. If it is genuinely public, strip `alt_email` and payment history from the context and template and keep the page. If not, add `LoginRequiredMixin` plus an owner-or-employee check, matching the sibling views. Either way it is a behaviour decision, not a mechanical fix.

---

### Finding 7 — the navbar's host guard is a substring test

**Route:** `/` (and every page including the navbar).
**Auth:** employee. **Host:** any allowed host containing the substring `staff` that is not the `staff` subdomain — e.g. `mystaff.lvh.me`, or `mystaff.uonalumni.or.ke` in production.
**Test:** `apps.staff.tests.NavbarStaffHostGuardTests.test_staff_lookalike_host_does_not_500_for_an_employee` — **errors**:

```
File "django/template/defaulttags.py", line 480, in render
    url = reverse(view_name, args=args, kwargs=kwargs, current_app=current_app)
django.urls.exceptions.NoReverseMatch: 'staff' is not a registered namespace
```

**Root cause.** `templates/snippets/navbar.html:34` (and identically at `:314`):

```
<a href="{% url 'staff:profile_update' %}"
```

a bare reverse of the `staff:` namespace, nested inside (`navbar.html:4`, `:17`, `:21`, `:29`):

```
{% with host=request.get_host %}
  {% if 'staff' in host %}
    {% if request.user.is_authenticated %}
      {% if request.user.employee %}
```

`'staff' in host` is a **substring** test, not a subdomain test. `ALLOWED_HOSTS` admits the whole `.lvh.me` wildcard in development and `.uonalumni.or.ke` in production (`settings.py:77-81`), whereas `SUBDOMAIN_URLCONFS` maps only the exact keys `staff` and `students` (`settings.py:423-428`). So a host like `mystaff.uonalumni.or.ke` passes the template guard while `SubdomainRoutingMiddleware` routes the request to `main.urls`, where the `staff:` namespace no longer exists — the 2026-08-18 SEO audit replaced `include('apps.staff.urls')` with a redirect at `main/urls.py:82`.

**Correction on record.** An earlier reading of this during the session claimed the navbar 500s for any employee browsing the ordinary public site. That was wrong — the `{% if 'staff' in host %}` guard prevents it, and `AuthHostMatrixSweepTests` sweeps an employee across every public route with no 5xx. Three pins record the safe cases: `test_public_host_is_unaffected_for_an_employee`, `test_staff_host_is_unaffected_for_an_employee`, and the three `StaffNamespaceReverseTests` — all **passing**.

**Tier A.** **Proposed fix:** use the cross-subdomain tag that this same file already loads at `navbar.html:2` and already uses correctly at `:218` and `:439`:

```
{% subdomain_url 'staff:profile_update' 'staff' %}
```

That resolves against `apps.staff.site_urls` regardless of which host rendered the page, and makes the fragile host guard unnecessary for these two links. Worth tightening `{% if 'staff' in host %}` to `{% if request.subdomain == 'staff' %}` at the same time — the middleware already sets `request.subdomain` (`main/middleware.py:22`) and that is an exact test.

---

### Finding 8 — the `student:` namespace is never registered

**Trigger:** any `{% subdomain_url 'student:…' 'students' %}` in a template; equivalently `reverse('student:…', urlconf='apps.student.urls')`.
**Host:** any — the reverse fails on whichever host renders the link.
**Tests:** `apps.student.tests.StudentNamespaceReverseTests.test_student_namespace_reverses_under_its_own_urlconf` and `apps.student.tests.SubdomainUrlTagStudentTests.test_tag_builds_a_students_subdomain_link` — both **error**:

```
File "apps/home/templatetags/subdomain_urls.py", line 27, in subdomain_url
    path = reverse(view_name, urlconf=urlconf, args=args, kwargs=kwargs)
django.urls.exceptions.NoReverseMatch: 'student' is not a registered namespace
```

**Root cause.** `apps/student/urls.py:5` declares:

```python
app_name = 'student'
```

but `apps.student.urls` is mounted as the **root** URLconf for the students subdomain (`settings.py:427`), not via `include()`. A root URLconf's module-level `app_name` registers nothing — only `include()` creates a namespace. So the declaration is inert.

The contrast is instructive and is pinned in the tests: `apps.staff.urls` carries the same `app_name` but is reached through `include()` at `apps/staff/site_urls.py:13`, so `staff:` *is* registered and `reverse('staff:profile_update', urlconf='apps.staff.site_urls')` resolves to `/profile/edit/`. `test_bare_name_reverses_but_namespaced_one_does_not` **passes**, showing the URLconf is loaded and the pattern present — only the namespace is missing.

**Tier A.** **Proposed fix:** mirror the staff arrangement — add an `apps/student/site_urls.py` that does `path('', include('apps.student.urls'))` and point `SUBDOMAIN_URLCONFS['students']` at it. That registers `student:` without touching any existing pattern or view. (The settings edit is out of Phase 1 scope; flagged for Phase 2.)

---

## Targets that did not reproduce

Reported per the acceptance criteria, with the source that proves why.

### Target 1 — the staff mis-gating cluster does **not** 500

The hypothesis was that `CompleteProfileView`, `ProfileUpdateView`, `ProfileDeleteView` and `download_staff_qr_code` resolve `request.user.employee` and therefore 500 for an authenticated non-employee whose session crossed subdomains. Every one of them fails **closed with a 404** instead:

- `apps/staff/views.py:258` — `return Employee.objects.filter(user=self.request.user)` → empty queryset → `UpdateView.get_object()` raises `Http404`
- `apps/staff/views.py:281` — `return get_object_or_404(Employee, user=self.request.user)`
- `apps/staff/views.py:303` and `:307` — `employee = get_object_or_404(Employee, user=request.user)`
- `apps/staff/views.py:407` — `employee = get_object_or_404(Employee, slug=staff_slug, id=pk)`, followed by an explicit owner-or-admin check that also returns 404

`apps.staff.tests.StaffMisGatingDoesNotLeakTests` pins all of this and **passes** (five tests).

The gating is still wrong in *kind*: these four carry `LoginRequiredMixin`/`@login_required` where the employee-record gate belongs, so a non-employee gets a 404 rather than the 403 that `EmployeeRequiredMixin` and `employee_required` produce (pinned for contrast by `test_employee_only_directory_still_403s_a_non_employee`). That is a consistency and auditability defect, **Tier B**, not a 500. Proposed fix: swap the four to `EmployeeRequiredMixin`/`@employee_required`, accepting that the response changes from 404 to 403.

### Target 6 — the Postgres-specific paths are sound

- **`LIKE` case-sensitivity: disconfirmed by reading.** `apps/home/views.py:1225-1226` already uses `email__iexact`, which Django compiles to `UPPER(...) LIKE UPPER(...)` on Postgres, so the claim flow is case-insensitive on either backend. Phone lookups use an exact match against the canonical E.164 string `apps/user/phone.py` guarantees.
- **Aggregate/empty-dataset paths: exercised and clean.** `apps.student.tests.ScholarshipAnalyticsEmptyDatasetTests` drives the applicant dashboard, the XLSX export and the evaluation list as a superuser on `students.lvh.me` with zero `ScholarshipApplication` rows — the state of every fresh deployment and of the gap between intake rounds. All three **pass**, including the `PercentileCont` ordered-set aggregate at `apps/student/analytics.py:168`.

### The auth × host matrix is otherwise clean

`apps.home.tests.AuthHostMatrixSweepTests` walks every argument-free route on all three hosts under all four auth states — anonymous, authenticated non-employee, employee, superuser — using `subTest` so one run reports every broken cell. 21 public paths, 5 staff paths, 5 student paths. **No 5xx anywhere.** This suite is what caught the incorrect navbar claim recorded under Finding 7.

---

## Pre-existing test debt (not introduced here, not fixed here)

Four classes in `apps/qr_manager/tests.py` error in `setUpClass`:

```
TypeError: Employee() got unexpected keyword arguments: 'given_name', 'family_name'
```

`Employee` no longer holds name data — it moved to `UserProfile` per `docs/rebuild-schema.md`, as `apps/staff/models.py:186` notes. The tests were not updated with it. Affected: `QRCodeAdminScopingTests`, `QRCodeAdminPermissionMethodTests`, `QRSupervisorSiteTests`, `ScanLogAdminScopingTests`. Left untouched, since Scope forbids restructuring that file. **Tier A**, fix: drop the two kwargs and create a `UserProfile` alongside each user, as the new tests in that file do.

## Also noted, not reproduced

`AdminRedirectMixin` and `redirect_admins_to_admin` (`apps/user/mixins.py:76-79`, `:88-89`) both call `redirect(reverse("admin:index"))`. On the staff subdomain that does **not** raise — it resolves to `/qr-admin/`, because `qr_admin_site` is an `AdminSite` and claims the `admin` namespace there. Neither helper is currently applied to any enumerated route, so this is latent rather than live; worth knowing before either is ever used.

---

## Acceptance criteria

- [x] Every route exercised across the full auth × host matrix, every test carrying an explicit `lvh.me`-family `HTTP_HOST`
- [x] All six targets addressed — four reproduced with failing tests, two (targets 1 and 6) disconfirmed with the source quoted
- [x] Every finding cites exact `file:line`, quotes the offending expression, is tagged Tier A/B and carries a proposed fix
- [x] All six `current_for()` call sites listed; `qr_manager/views.py:64-66` asserted still correct by a passing test
- [x] No source / settings / migration / dependency / real-data change; tests appended to the existing `tests.py` files on `feature/qa-500-tests`; report at repo root

## Open decisions for Phase 2

1. **Finding 1 is a prerequisite for everything else.** Until `migrate` works from zero, the suite needs the out-of-repo shim and no fresh environment can be built. Fix it first.
2. **Finding 2's fix needs a call per call site** — particularly `views.py:839`, which may legitimately want the pending row.
3. **Finding 6 needs an intent decision** — is the alumni profile page meant to be public at all?
4. **Finding 5 has a narrow fix and a durable one.** The durable one (guarantee a `UserProfile` per `User`) retires Finding 4 as well.
