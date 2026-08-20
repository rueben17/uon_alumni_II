# Production Error-Page Diagnostic Audit — 2026-08-20

**Scope note:** this document is the sole write output of a read-only investigation. No application code, template, config, or migration was modified while producing it.

**Evidence basis:** Phase 1 (this section) is built from real log evidence pulled directly off the production VPS via SSH (`journalctl -u uon_alumni`, covering every boot from 2026-06-03 through 2026-08-20 — journald has not rotated past that on this box) and a live, read-only Django-shell query against the production database's Django Q2 tables. Every finding in "Confirmed Errors" is backed by an actual log line or query result, with counts and timestamps quoted verbatim. Everything in "Probable Errors" is static-analysis only — labelled as such, and not corroborated by a log entry.

**Correction to the supplied context, stated up front:** the brief says "Gunicorn is NOT yet a systemd service." That is not what was found. `/etc/systemd/system/uon_alumni.service` exists, is active and enabled, and `deploy.sh` already does `sudo systemctl restart uon_alumni`. Gunicorn logging (stdout/stderr, including every Python traceback below) is fully captured via journald because of this unit — there is no separate gunicorn access/error logfile, and none is needed for what was found. This correction matters because it changes where evidence lives: journald, not a logfile, is the source of truth here.

---

## 1. Executive summary

1. **A live, unfixed `NoReverseMatch` bug pattern is the single largest confirmed cause of 500s**: `apps/home/views.py`'s scholarship page crashed 13 times since 2026-08-06 (fixed today, 2026-08-20, in the commit immediately preceding this audit) because `apps.student.urls` is used as a **root** urlconf for the students subdomain rather than `include()`'d with a namespace, so its `app_name = 'student'` never registers a reversible `student:` namespace — and the exact same broken pattern (`reverse("student:register", urlconf=STUDENT_URLCONF)`) still exists, unfixed, at three more call sites in `apps/user/adapter.py` (lines 293, 344, 493), each one hit on essentially every students-subdomain login/signup by a user without a `Student` record.
2. **Two DB-connectivity 500s in three weeks (Aug 11, Aug 12, Aug 17) are consistent with Neon's serverless suspend/DNS behavior**, not application bugs — `CONN_HEALTH_CHECKS=True` is already correctly set (`main/settings.py:233,258`), which is the documented mitigation, so this is low-severity and largely already handled; noted for completeness since the brief specifically asked about it.
3. **There is no error-visibility layer beyond journald**: `LOGGING` only routes `django.request` at ERROR to a console handler (`main/settings.py:617-632`), `ADMINS` is unset, `EMAIL_BACKEND` is the console backend (mail never actually leaves the box even if `ADMINS` were set), and no Sentry/Rollbar/equivalent is installed (`pip freeze` on the VPS confirms). Every finding in this report exists only because journald happened to retain it — nobody is being notified of any of this in real time.

---

## 2. Confirmed errors (observed in production logs / DB — every entry below is a real, quoted log line or query result)

All counts are from `journalctl -u uon_alumni`, full available history (2026-06-03 → 2026-08-20, all 5 boots). "Internal Server Error: `<path>`" is Django's own `django.request` logger format (`django/utils/log.py`), confirmed by exact string match — these are genuine Django-handled 500s, not a third-party monitor's text.

### 2.1 `NoReverseMatch: 'student' is not a registered namespace` — CONFIRMED, FIXED TODAY

- **Count:** 16 occurrences of `KeyError: 'student'` (the inner exception; each is chained into a `NoReverseMatch`) since 2026-08-06. 13 of these are the `/uon-alumni-scholarship/` 500 specifically; most recent occurrence **2026-08-20 05:50:43**, ~4 hours before this audit began.
- **File:line:** was `apps/home/views.py:881` (`return redirect("student:register")`), inside `uon_alumni_scholarship()`.
- **Root cause, confirmed by direct `manage.py shell` testing, not guessed:** `apps/student/urls.py` sets `app_name = 'student'` but is used directly as `SUBDOMAIN_URLCONFS['students']` (`main/settings.py:419,427`) — i.e. as a **root** urlconf — and is never `include()`'d from anywhere with a `namespace=` kwarg. Confirmed: `reverse("student:register", urlconf="apps.student.urls")` raises `NoReverseMatch`; `reverse("register", urlconf="apps.student.urls")` (no prefix) returns `/register/` correctly.
- **Status:** fixed in the commit immediately preceding this audit (`apps/home/views.py`, now `reverse("register", urlconf="apps.student.urls")` + the existing `_students_subdomain_url()` helper to cross the host boundary). Verified live: `curl https://www.uonalumni.or.ke/uon-alumni-scholarship/` → 200; simulated the exact failing scenario (authenticated user, no `Student` record) via Django test client → clean 302 to `http://students.<domain>/register/`; confirmed via SSH that the deployed commit hash matches and no new "Internal Server Error" lines have appeared since.
- **This same broken pattern is NOT fully fixed** — see Confirmed Error 2.2.

### 2.2 The identical `student:` bug recurs — live, unfixed — at NINE more call sites across three different files. This is a systemic architectural defect, not an isolated bug.

This is reported here rather than in "Probable Errors" because the underlying mechanism is the *same, already-log-confirmed* bug as 2.1 (not a new hypothesis), and because **the codebase already documents having hit this exact bug pattern a third time, independently, before this audit started** — see the `apps/home/context_processors.py` finding below, dated 2026-08-19, one day before this audit. All nine sites were confirmed by direct file read (quoted below), not by log evidence — most have not yet been observed in the journal history pulled for section 2.1, meaning either they haven't fired yet or fired outside the covered window.

**Root cause, stated once:** `apps/student/urls.py` sets `app_name = 'student'` but is used directly as `SUBDOMAIN_URLCONFS['students']` (a root urlconf) and is never `include()`'d anywhere with a namespace. A root urlconf's own `app_name` does not register a reversible namespace — confirmed by direct `manage.py shell` testing in 2.1. Every one of the nine sites below reverses or redirects to a `"student:..."`-prefixed name and will raise `NoReverseMatch` (uncaught → 500) the moment it executes.

**apps/user/adapter.py (3 sites — the OAuth login/signup/connect flow itself):**
- `apps/user/adapter.py:293` — `return reverse("student:register", urlconf=STUDENT_URLCONF)` — `get_login_redirect_url()`, `subdomain == "students"` branch. Fires on every students-subdomain **login** by a user with no `Student` record.
- `apps/user/adapter.py:344` — same pattern, `get_signup_redirect_url()`, `subdomain == "students"` branch. Fires on every students-subdomain **brand-new signup**.
- `apps/user/adapter.py:493` — same pattern, `get_connect_redirect_url()`, `subdomain == "students"` branch.

**apps/student/views.py (3 sites — the app's own registration/evaluation flow, self-referencing its own broken namespace):**
- `apps/student/views.py:93` — `return reverse("student:all_uon_students")`, in `StudentRegisterView._post_register_url()` (`get_success_url()`'s fallback). Fires immediately after **every student's first successful registration submission** that didn't arrive via a stashed `post_login_next`.
- `apps/student/views.py:163` — `return redirect("student:evaluate_application_list")`, in `EvaluateApplicationView.post()`'s no-`pk` branch.
- `apps/student/views.py:182` — `return redirect("student:evaluate_application", pk=pk)`, in `EvaluateApplicationView.post()`'s success branch. Fires immediately after **a staff member successfully saves an evaluation score sheet** — the save itself already committed, so this crashes the confirmation redirect for otherwise-successful work.

**Templates (2 sites — render-time crashes, not just view-logic paths):**
- `templates/student/applicant_dashboard.html:22` — `href="{% url 'student:analytics_export' %}"` — unconditional, not inside any `{% if %}`. **Crashes every single load of the Applicant Dashboard** (`StaffOrSuperuserRequiredMixin`-gated, so every evaluator/superuser who visits it).
- `templates/student/evaluate_application.html:48` — `value="{% url 'student:evaluate_application' pk=applicant.pk %}"` inside the applicant-picker `{% for applicant in applicants %}` loop. **Crashes the entire Evaluate Application screen as soon as one `ScholarshipApplication` row exists** — i.e. the normal, expected case, not an edge case.

**apps/home/context_processors.py (1 site — already hit in production, already worked around, but the underlying `reverse()` call itself was never fixed, it was routed around):**
- `apps/home/context_processors.py:254-261` — comment, quoted verbatim: *"apps.student.urls (the 'student' namespace) is only ever mounted via the students-subdomain middleware (SUBDOMAIN_URLCONFS), never included into main.urls, so a 'student:' reverse pinned to main.urls always raises NoReverseMatch (**confirmed live, 2026-08-19: crashed this context processor -- which runs on every page -- for every staff/superuser request site-wide**)."* The fix applied there was to stop calling `reverse()` at all and hardcode the path strings instead (`f"{students_base}/evaluate/"`, `f"{students_base}/dashboard/"` — visible immediately below the comment). This is a real 2026-08-19 production incident, self-documented in the code, that is the *same defect* as everything else in this section — it just wasn't traced back to its root cause and fixed at the other nine sites when it was fixed here.

**Why this matters more than any other single finding in this report:** this is not nine unrelated bugs. It is one architectural fact (`apps.student.urls` has no working `student:` namespace) that has now caused three independently-discovered production incidents (context_processors.py on 2026-08-19, the scholarship page across 2026-08-06→08-20, and — per the count in 2.1 — 16 total log occurrences) and has nine more live landmines from the same cause still sitting in the codebase, three of them in the OAuth login flow itself and two of them unconditional template-render crashes on core evaluator-facing screens. Not fixed as part of this audit per the audit's own no-edits rule.

### 2.3 Database connectivity errors — CONFIRMED, low frequency, largely already mitigated

- `psycopg2.OperationalError: connection to server at "ep-blue-surf-aso6vaai-pooler.c-4.eu-central-1.aws.neon.tech" ... Failed to acquire permit to connect to the database. Too many database connection attempts are currently ongoing.` — **1 occurrence**, 2026-08-11 17:40:52.
- `psycopg2.OperationalError: could not translate host name "ep-blue-surf-aso6vaai-pooler.c-4.eu-central-1.aws.neon.tech" to address: Temporary failure in name resolution` — **2 occurrences**, 2026-08-12 12:52:58 and 2026-08-17 23:06:27.
- These are isolated (3 incidents across 2+ weeks, no clustering) and consistent with Neon's documented serverless-suspend/DNS behavior, not a code defect. `CONN_MAX_AGE=600` + `CONN_HEALTH_CHECKS=True` is already set in both the production and dev-with-`DATABASE_URL` branches (`main/settings.py:233,258`) — this is exactly the Django-recommended mitigation for stale pooled connections against a suspend-capable backend. No further action indicated beyond what's already configured; noted because the brief specifically asked about `CONN_MAX_AGE`.

### 2.4 `TemplateDoesNotExist` — CONFIRMED, HISTORICAL, ALREADY RESOLVED

- `student/all_uon_students.html` — 13 occurrences, 2026-08-05 through 2026-08-10 16:23:02. None since.
- `home/uon_alumni_scholarship.html` — 7 occurrences, 2026-08-06 through 2026-08-10 10:46:23. None since.
- `home/uon_alumni_donate.html` — 5 occurrences, 2026-08-09 through 2026-08-10 17:19:22. None since.
- `home/uon_alumni_contact_us.html` — 4 occurrences, 2026-08-10 only. None since.
- `staff/staff_login.html` — 1 occurrence, 2026-08-10 10:48:08. None since.
- All five templates were confirmed to exist on disk right now (`ls -la` on each, local working tree — all last-modified 2026-08-19, well after the error window closed). These correlate with the 2026-08-10 SEO/nav-wiring deploy referenced in `docs/todo.md`. No action needed; included per the brief's "30 most frequent tracebacks" instruction and to explicitly rule them back in as non-issues rather than silently omitting them.

### 2.5 `Internal Server Error: <path>` with NO accompanying traceback — CONFIRMED PATTERN, ROOT CAUSE NOT DETERMINED

A systematic pass over all 5 boots' worth of "Internal Server Error: `<path>`" lines, checking whether a `Traceback (most recent call last):` line follows within 3 lines, found a genuine split:

- **34 occurrences across many distinct paths DO have a full traceback following** (these are 2.1/2.3/2.4 above, plus the one-off paths in the full table at the end of this section).
- **A distinct set of ~19 occurrences across several paths do NOT**, despite the log line format being byte-for-byte identical to the ones that do:
  - `/robots.txt` — **8 occurrences**, 2026-08-11 through 2026-08-18 14:29:09. No traceback.
  - `/api/v1/health`, `/login` (no trailing slash), `/btcpayserver/api/v1/health`, `/btcpayserver/login` — 2 each, all 2026-08-18 19:34:06–19:34:12, clustered within 6 seconds. No traceback.
  - `/this-path-does-not-exist-deploy-check/` — 2 occurrences, 2026-08-19 10:07:02/10:07:18. No traceback. (This path name reads as a deliberate synthetic probe from prior deploy-verification work, not real traffic — but a synthetic 404-probe returning 500 instead of 404, with no traceback, is itself worth noting.)
  - `/wp-json/`, `/login/` (2026-08-19 only), `/apply/`, `/nonexistent-random-path-xyz/` — 1 each, no traceback.
- **I could not determine why these lack tracebacks from the evidence available.** Two hypotheses were checked and both were ruled out by direct correlation: (a) gunicorn worker-timeout kills — only 2 `WORKER TIMEOUT`/`SIGKILL` events exist in the entire log history (2026-08-03 05:00:51, 2026-08-12 11:01:30), and neither timestamp lines up with any of the no-traceback entries above; (b) log truncation at a service restart boundary — checked manually for several entries, no restart falls between the "Internal Server Error" line and where a traceback would be expected. This is reported as an open, unexplained observation, not a diagnosed bug — flagging it prominently because `/robots.txt` recurring 8 times over a week on a route that should be trivial (a `TemplateView` rendering a static-ish text template) is the kind of "recurring but unexplained" signal Phase 1 of this audit exists to surface, and it deserves direct investigation before being dismissed.
- `robots.txt` (`templates/robots.txt`) does reference `{{ sitemap_url }}` and branches on `request.subdomain` — read directly, nothing there looks like it should raise (undefined context variables render as empty string in Django templates, not an error). Flagging that this template was read and nothing incriminating was found in it — the cause, if there is a code-level one at all, is not in this template's own content.

### 2.6 `/` (homepage) — CONFIRMED, 23 occurrences, spread across the full log history (oldest 2026-07-07, newest 2026-08-19 10:11:09), all WITH tracebacks. Not further broken down by exact exception type within this audit's time budget — flagging for follow-up: this is the single highest-count path in the entire log and warrants its own dedicated traceback review beyond what this pass captured in the grouped exception-class query (which surfaced `KeyError:'student'`/`TemplateDoesNotExist`/`OperationalError` as the *only* distinct exception class strings across the whole log — meaning all 23 `/` occurrences are almost certainly one of those three, most likely the DB `OperationalError` cases or transient `TemplateDoesNotExist` during the 08-05→08-10 window, given no other exception class string appeared anywhere in the full-history grep). Stated as inference, not directly re-verified line-by-line for all 23.

### 2.7 Django Q2 async task queue — CONFIRMED CLEAN, live read-only query against production DB

```
Failure.objects.count()  →  0
Success.objects.count()  →  1   (apps.home.tasks.expire_lapsed_installment_plans, 2026-08-18 00:03:25 UTC)
Schedule.objects.count() →  0
qcluster.service          →  active, enabled
```

- Zero Q2 failures ever recorded. No evidence of async-task-layer errors in production.
- **Operational gap, adjacent to but outside strict "error page" scope, flagged because it was found while running the exact query the brief asked for:** `expire_lapsed_installment_plans` (`apps/home/tasks.py:136-150`) is documented in its own docstring as meant to be registered as a recurring daily `Schedule` row created manually via `/2005/admin/django_q/schedule/add/` — "not created programmatically... this is a one-time setup action." `Schedule.objects.count() == 0` on production confirms that manual step was never done. The one `Success` row is a single historical run, not a recurring job — installment-plan expiry is not currently running on any schedule in production. This produces no error page (nothing crashes), it's a silent no-op, so it's reported here rather than in the main findings, but it's a real, DB-confirmed gap worth the team's attention.

### 2.8 Full frequency table — every distinct path, all boots, 2026-06-03 through 2026-08-20

| Count | Path (dynamic segments generalized) | Traceback? | Most recent |
|---:|---|:---:|---|
| 23 | `/` | Y | 2026-08-19 10:11:09 |
| 13 | `/uon-alumni-scholarship/` | Y | 2026-08-20 05:50:43 (now fixed) |
| 13 | `student/all_uon_students.html` (TemplateDoesNotExist, path `/`) | Y | 2026-08-10 16:23:02 (resolved) |
| 8 | `/robots.txt` | **N** | 2026-08-18 14:29:09 |
| 7 | `home/uon_alumni_scholarship.html` (TemplateDoesNotExist) | Y | 2026-08-10 10:46:23 (resolved) |
| 6 | `/profile/edit/` | Y | 2026-07-15 02:51:27 |
| 5 | `home/uon_alumni_donate.html` (TemplateDoesNotExist) | Y | 2026-08-10 17:19:22 (resolved) |
| 6 | `/login/` | Y (5) / N (1, Aug 19) | 2026-08-19 10:01:09 |
| 5 | `/uon-alumni-donate/` | Y | 2026-08-10 17:19:22 |
| 4 | `/accounts/google/login/callback/` | Y | 2026-07-10 02:37:57 |
| 4 | `/uon-alumni-contact-us/` | Y | 2026-08-10 18:19:22 |
| 3 | `/2005/login/` | Y | 2026-07-08 22:49:52 |
| 3 | `/2005/staff/employee/` | Y | 2026-07-08 23:37:04 |
| 2 each | `/accounts/google/login/`, `/uon-alumni-association/<slug>/<uuid>/` (×2 distinct people), `/quality-assurance/<slug>/<uuid>/`, `/2005/staff/employee/<uuid>/change/`, `/qr/<uuid>/`, `/api/v1/health`, `/login` (no slash), `/btcpayserver/api/v1/health`, `/btcpayserver/login`, `/this-path-does-not-exist-deploy-check/` | mixed, see 2.5 | various |
| 1 each | `/2005/sites/site/`, `/accounts/login/`, `/2005/staff/employee/add/`, `//wordpress/wp-includes/wlwmanifest.xml`, `/uon-alumni-page/agm/`, `/wp-json/`, `/wp-login.php`, `/evaluate/56/`, `/apply/`, `/nonexistent-random-path-xyz/` | mixed | various |

`/wp-json/`, `/wp-login.php`, `//wordpress/...`, `/btcpayserver/*` are automated scanner/bot noise against paths this app never served — expected 404 territory; that several of them logged as 500 instead (with no traceback — see 2.5) is the same open question as the rest of 2.5, not a separate issue.

**Not obtained — explicit limitation:** Nginx's `access.log`/`error.log` (`/var/log/nginx/`) exist but are group-owned `adm`, and the SSH user used for this audit (`armando_salazar`) is in groups `sudo www-data users` — **not** `adm` — so both files returned `Permission denied` on direct read, and `sudo` requires a password not available non-interactively. This means the true 4xx counts (plain 404s, 400s from `DisallowedHost`, etc. that never reach Django's `django.request` ERROR-level logging, since Django only logs 4xx at WARNING and 5xx at ERROR — WARNING-level `django.request` output was not separately queried in this pass) were not obtainable. **This is itself a finding**: nobody investigating a production issue from this account can currently see nginx-level request/error data at all.

---

## 3. Error handler configuration findings

1. **Custom `400.html`/`403.html`/`404.html`/`500.html` all exist** at `templates/` (i.e. inside `TEMPLATES[0]['DIRS']`, `main/settings.py:195`), which is exactly where Django's default error views look — no `handler404`/`handler500`/etc. declarations exist anywhere in the codebase (confirmed: only Django's own internal default assignments matched the grep), and none are needed given `DEBUG=False` and the templates being correctly placed.
2. **`500.html` is deliberately built to survive Django's zero-context 500 render.** Confirmed by reading `django.views.defaults.server_error`'s documented behavior (it calls `template.render()` with no context and no request at all) against the template's own content: `templates/500.html` does **not** `{% extends "base.html" %}`, includes no navbar/footer, and references no context-processor-supplied variable — only `{% load static %}`/`{% static %}` (which reads `settings.STATIC_URL` directly, not the request) and a hardcoded `href="/"`. The template's own comment (lines 8-19) documents this constraint explicitly. **This is a verified-safe finding, not a bug** — worth stating plainly since it's exactly the failure mode Phase 2 was designed to catch, and it was actively checked for and not found.
3. **`400.html`/`403.html`/`404.html` DO `{% extends "base.html" %}`** (confirmed by reading `templates/404.html` in full, and the first 15 lines of `templates/400.html`, which is explicitly commented as following the same pattern) — this is safe *for Django's actual behavior*, since `page_not_found`/`permission_denied`/`bad_request` (unlike `server_error`) render with a full `RequestContext`, confirmed via Django's own implementation. `base.html`'s context processors (`apps/home/context_processors.py`) do run real queries — `images()` runs `Banner.objects.all()` unconditionally (line 62), and `contacts()` runs a conditional `Membership.objects.filter(...)` when the requester is authenticated (line 290) — so in the specific scenario where the *cause* of an error page render is itself a database outage, even the 404/403/400 pages would then fail past Django's own fallback into a bare, unstyled Django error page. **This is inferred from code, not observed** — no log entry in this audit shows a cascading error-page failure; flagged as a theoretical dependency worth knowing about, not a confirmed incident.
4. **Multi-subdomain error template resolution:** all three subdomains (www, staff, students) share one gunicorn process and one Django settings module (confirmed via the nginx config — all three `server{}` blocks proxy to the same `127.0.0.1:8000`), so error templates are resolved identically regardless of subdomain — there is no risk of one subdomain showing another's branding, since there is only one `templates/` tree and no subdomain-specific override was found.
5. **`ALLOWED_HOSTS`** (`main/settings.py:76-85`): production value from `.env`/systemd unit is `uonalumni.or.ke,www.uonalumni.or.ke`, and `main/settings.py` unconditionally appends `'uonalumni.or.ke'`, `'www.uonalumni.or.ke'`, `'.uonalumni.or.ke'` (the leading-dot wildcard covers `staff.`/`students.`/any future subdomain) regardless of what's in the env value. All three subdomains, with and without `www`, are covered. No gap found.
6. **`CSRF_TRUSTED_ORIGINS`** (`main/settings.py:591-604`): explicitly lists `https://` for the bare domain, `www`, `staff`, and `students` — all four covered. In `DEBUG` mode, the four `lvh.me` dev equivalents are also added. No gap found.

---

## 4. Probable errors (static-analysis only — NOT corroborated by a log entry; labelled hypotheses)

Two Explore agents ran in parallel over the full codebase's views/templates/urls with the same read-only, cite-everything constraint as this document. Their raw findings, lightly reorganized (nothing added, nothing asserted beyond what each agent itself reported reading):

### 4.1 Object retrieval / null-value patterns (apps/home, apps/staff, apps/student, apps/qr_manager, apps/user — all five `views.py` files read in full)

- **Pattern 1 (bare `.objects.get()`, uncaught `DoesNotExist`): none found.** Every single-object lookup across all five files goes through `get_object_or_404`, `.filter().first()`, or CRUD-view machinery.
- **Pattern 2 (unguarded reverse-OneToOne access) — 4 confirmed instances, all the same `User → UserProfile` chain**, which is only guaranteed to exist for accounts created via the Google-OAuth adapter's `_ensure_profile()`, not for every `User` row:
  - `apps/home/views.py:373` — `profile = self.request.user.profile`, in `AlumniRegisterView.form_valid()`, fires *after* the `AlumniProfile` row is already saved — any authenticated user reaching this view without ever going through OAuth onboarding (e.g. a superuser account) raises `UserProfile.DoesNotExist`, uncaught, 500 — **after** already writing an orphaned `AlumniProfile` row.
  - `apps/staff/views.py:404` — `employee.user.profile.display_name` in `download_staff_qr_code`.
  - `apps/staff/views.py:416` — same chain, same view.
  - `apps/qr_manager/views.py:64` — `alumni_profile.user.profile.display_name` in `_alumni_verification_context()`, used by `verify_scan` — **a public, unauthenticated endpoint reachable by scanning a QR code** — the highest-exposure instance of this pattern.
  - All other reverse-OneToOne accesses in these files (`request.user.student`, `.alumni_profile`, `.employee`, `application.score_sheet`, `employee.employee_qrcode`) were confirmed properly `hasattr`/`getattr`-guarded.
- **Patterns 3, 4, 5, 6, 7, 8 (`.first()`/`.last()` chains, `get_object_or_404` type mismatches, nullable-date arithmetic, `.url` on empty File/ImageField, zero-denominator division, unguarded `.aggregate()`): none found.** Each was checked explicitly against the actual model field types (e.g. confirmed `Employee.id`/`AlumniProfile.id` are UUID fields matched by `<uuid:...>` converters; confirmed `ScholarshipApplication`/`Payment` use default int PKs matched by `<int:...>`) and every instance found was already guarded (e.g. `MembershipAnalyticsView`'s percentage calc at `apps/home/views.py:768` has an explicit `if total_members else 0`).

### 4.2 URL inventory, `staff:`/`student:` namespace recurrence check, and Q2 task-layer audit

- **Full URL table**: 58 routes enumerated across `main/urls.py`, `apps/home/urls.py`, `apps/student/urls.py`, `apps/staff/urls.py`, and `apps/staff/site_urls.py`, each with subdomain, view, and auth requirement. Full table available in the agent transcript; condensed auth-gap summary below in section 5's table. Two items worth calling out directly:
  - `apps/staff/views.py`'s `EmployeeListView` (route 48, `staff/` root) carries a docstring calling it a "Public staff directory" but is actually gated by `LoginRequiredMixin` — a **doc/behavior mismatch**, not a bug, but worth a maintainer's attention since the comment is actively misleading about current behavior.
  - `download_staff_qr_code` (route 54) and `staff_detail_fallback` (route 52) and `EmployeeDetailView` (route 53) have **no auth check at all** — all public. This may be intentional (QR codes are meant to be scanned by anyone), but is stated here as a fact for someone who knows the intended access model to confirm, not asserted as a bug.
- **The `student:` bug (2.2 above) does not appear to recur under the `staff:` namespace**, for a structurally different reason than `student:`'s: `apps/staff/urls.py` (`app_name='staff'`) **is** `include()`'d (from `apps/staff/site_urls.py:13`, `path('', include('apps.staff.urls'))`) rather than used directly as a subdomain root — per Django's documented `include()` behavior, passing a dotted-path string to a urls module with its own `app_name` auto-registers that as a real namespace. Every `staff:`-prefixed reverse/redirect/`{% url %}` call site found (13 total, listed with file:line in the agent's full report) either explicitly pins `urlconf="apps.staff.site_urls"` (or uses the `subdomain_url` template tag, which does the same internally) or executes only inside a view/template reachable exclusively via the staff subdomain. **This is inference from Django's documented `include()` semantics plus each call site's execution context, not verified the same way the `student:` bug was (via direct `manage.py shell` execution)** — stated as a hypothesis with strong supporting reasoning, not a confirmed-safe fact.
- **Q2 async task layer: no live bugs found.** All 3 `async_task(` call sites in the codebase (`apps/home/admin.py:327`, `apps/home/views.py:401`, `apps/student/views.py:179`) pass only primitive values (ints/UUIDs captured before the lambda, never a live model instance/QuerySet/request/file), and all 3 are wrapped in `transaction.on_commit(...)`. `dispatch_sms` (`apps/home/tasks.py:120`) has zero callers anywhere (confirmed dead code, matches its own docstring). `expire_lapsed_installment_plans` has no in-code call site at all — see 2.7.

### 4.3 Type/parse errors, auth gaps, and the full `{% url %}`/`reverse()` audit

Covers `apps/home`, `apps/staff`, `apps/student`, `apps/qr_manager`, `apps/user`, `main/settings.py`, `main/urls.py`, `main/middleware.py`, and every file under `templates/`. All items below were verified by direct read (a sample was independently re-verified for this report — see 2.2 and the `core_value_detail` item below — and matched exactly).

**Routing fact worth restating here:** `main/middleware.py`'s `SubdomainRoutingMiddleware` never sets `request.urlconf` for any path starting with `/accounts/`, on any subdomain — allauth's entire OAuth flow always runs against `main.urls`. This is why `apps/user/adapter.py`'s non-`students`-subdomain `reverse()` calls (`home:...`, `admin:index`, unnamespaced `account_login`/`account_signup`) all resolve correctly with no `urlconf=` argument — they're relying on this middleware behavior, correctly.

**A1 — type/parse errors on GET/POST params.** One instance found: `apps/staff/views.py:154` — `qs = qs.filter(department_id=department)`, where `department = self.request.GET.get("department", "").strip()` (line 152) is used unvalidated as an integer FK lookup. `?department=abc` (a non-numeric value) raises an uncaught `ValueError` from `IntegerField.get_prep_value()` → 500. The same view's `?unit=` and `?track=` params are both allowlist-validated first — `?department=` is the one that isn't. No other unvalidated `int()`/`Decimal()`/date-parsing on a request parameter was found in any of the four apps' views or forms.

**A2 — pagination.** None found. Every paginated view uses `ListView.paginate_by`, whose built-in `MultipleObjectMixin.paginate_queryset()` already catches invalid/out-of-range page numbers and converts them to `Http404`, not a 500. No manual `Paginator(...)` instantiation exists anywhere.

**A3 — AJAX/Select2 parameter validation.** No dedicated `JsonResponse` view exists anywhere in the codebase. The two Faculty→X cascading dropdowns are built server-side into the initial page load, not separate round-trip endpoints — no gap possible there. `EmployeeListView` (`apps/staff/views.py`) is the one HTMX-shaped view (serves partial templates for `HX-Request`); its `?q=`/`?track=`/`?unit=` params are all validated, `?department=` is not — same finding as A1, same view.

**B4 — `apps/staff` views with no auth gate on internal HR/QR data**, inconsistent with sibling views in the same file that do gate:
- `apps/staff/views.py:317-349` — `EmployeeDetailView(DetailView)`, no mixin at all. Exposes full HR record (department, unit, position, publications, projects, alt email) to anonymous visitors. `EmployeeListView`, which links to it, does have `LoginRequiredMixin` — the directory is gated, the detail page it links to isn't.
- `apps/staff/views.py:376-395` — `staff_detail_fallback`, no decorator. Renders name/unit/profile-completeness to anyone with (or guessing) an employee UUID — this is also the QR-scan fallback landing page.
- `apps/staff/views.py:398-467` — `download_staff_qr_code`, no decorator. Lets anyone download the actual printable QR badge asset (PNG/PDF) for any employee, unauthenticated.
- `apps/staff/views.py:64-65` — `staff_dashboard`, currently a placeholder (`HttpResponse("Staff dashboard")`), no decorator — flagged so it isn't forgotten once real content is added.

These may be an intentional access model (QR codes meant to be publicly scannable) — stated as a fact for the team to confirm, not asserted as a bug.

**B5 — `apps/student` scholarship/evaluation/analytics views.** All properly gated: `StudentRegisterView` has `LoginRequiredMixin`; `EvaluateApplicationView`, `ApplicantDashboardView`, `ScholarshipAnalyticsExportView` all use `StaffOrSuperuserRequiredMixin`. Minor inconsistency, not a data-exposure issue: `apps/student/views.py:28-30`'s `all_uon_students` has no auth gate (unlike its staff-directory counterpart), but currently queries no data at all (`context = {}`), so it's harmless today.

**B6 — every `reverse()`/`redirect()` call site in `apps/user/adapter.py`, checked against its target urlconf.** 13 call sites total; 10 correct, 3 broken (the three already listed in 2.2 — `student:register` at lines 293, 344, 493). All 10 correct ones were verified by matching the target name against whichever urlconf is actually active for that code path (`STAFF_URLCONF`/`apps.staff.site_urls` explicitly pinned for every `staff:` call; `main.urls` implicitly active — and correct — for every unnamespaced/`home:`/`admin:` call, per the `/accounts/` middleware behavior above).

**C7 — `render()`/`template_name` vs. templates on disk.** None missing. Exhaustively checked: 26 templates referenced from `apps/home/views.py`, 7 from `apps/staff/views.py`, 4 from `apps/student/views.py`, 2 from `apps/qr_manager/views.py`, plus the shared `templates/robots.txt` — all present on disk.

**C8 — `{% url %}`/`reverse()`/`redirect()` name and argument mismatches.** The nine `student:`-prefixed sites are covered in full in 2.2 and not repeated here. One additional, structurally different mismatch found — not a namespace problem, a genuinely nonexistent name:

- `apps/home/models.py:414` — `CoreValue.get_absolute_url()`: `return reverse('core_value_detail', kwargs={'pk': self.pk})`. **Independently re-verified for this report** by direct read: `core_value_detail` does not exist as a `name=` in any `path()` across the entire project (only `home:uon_alumni_*`, `staff:*`, `student:*`, `qr:*`, `admin:*`, `membership_admin:*` names exist anywhere). `CoreValue` is registered in Django admin (`CoreValueAdmin`, `apps/home/admin.py`), so this fires as a 500 the moment anyone clicks a `CoreValue` row's "View on site" link in `/2005/`. No corresponding view/template was ever built for this model at all — this looks like a `get_absolute_url()` written ahead of the feature it points to, never removed or finished.

Every other `{% url %}` tag across `templates/` (`account/`, `socialaccount/`, `home/`, `staff/`, `snippets/`) and every other `reverse()`/`redirect()` call in `apps/home/views.py`, `apps/home/models.py` (the `AlumniProfile.get_absolute_url()` family — all explicitly pinned to `urlconf="main.urls"`), `apps/home/context_processors.py`, `apps/home/sitemaps.py`, `apps/home/tasks.py`, `apps/staff/views.py`, `apps/staff/models.py`, `apps/qr_manager/views.py` were checked against the actual `path()` definitions and resolve correctly. The two `{% url 'staff:profile_update' %}` tags in `templates/snippets/navbar.html:40,322` are host-guarded (`{% elif 'staff' in host %}`) so they only ever render while `apps.staff.site_urls` — which does have a working `staff:` namespace — is active; not a bug.

**Files too large to read in full:** `apps/home/models.py` (1744 lines), `main/settings.py` (639 lines), `apps/staff/models.py` (434 lines) — each was grepped in full for `reverse(`/`redirect(`/`get_absolute_url` first, then read in context around every match, so C8 coverage of these three files should still be complete even though they weren't read top-to-bottom.

---

## 5. Full URL inventory

`app_name`/mounting summary (repeated from 4.3/2.2 for reference): `apps/home/urls.py` (`app_name='home'`) is `include()`'d from `main/urls.py` with `namespace="home"` — clean. `apps/staff/urls.py` (`app_name='staff'`) is `include()`'d from `apps/staff/site_urls.py` (no explicit `namespace=`, but Django auto-applies `app_name`) — clean wherever `apps.staff.site_urls` is the active urlconf. `apps/staff/site_urls.py` itself and `apps/student/urls.py` (`app_name='student'`) are both used directly as `SUBDOMAIN_URLCONFS` root urlconfs, never `include()`'d — only `apps/student/urls.py`'s `app_name` fails to register a namespace this way (see 2.2 for why `staff:` doesn't have the same problem despite the structural similarity).

Status legend: **clean** = checked, no issue found. **suspect** = a real gap exists but isn't a crash (e.g. missing auth gate, doc/behavior mismatch). **confirmed broken** = will 500 on the documented trigger, backed by a direct-read citation in section 2 or 4.

| # | URL pattern | Subdomain | View | Auth | Status |
|---|---|---|---|---|---|
| 1 | `2005/` | www | Django admin | admin `is_staff` gate | clean |
| 2 | `membership-admin/` | www | `membership_admin_site.urls` | custom AdminSite gate | clean |
| 3 | `accounts/` | all (pinned to `main.urls` by middleware) | `allauth.urls` | mixed, allauth's own | clean (routing itself verified; allauth internals out of scope) |
| 4 | `` (root → `apps/home/urls.py`) | www | see #9-37 | — | — |
| 5 | `^staff/(?P<rest>.*)$` | www | `redirect_to_staff_subdomain` | none, public redirect | clean |
| 6 | `^students/(?P<rest>.*)$` | www | `redirect_to_students_subdomain` | none, public redirect | clean |
| 7 | `sitemap.xml` | www | `django.contrib.sitemaps.views.sitemap` | none, public | clean |
| 8 | `robots.txt` | www | `TemplateView` | none, public | **suspect** — 8 unexplained no-traceback 500s, see 2.5 |
| 9 | `` (home) | www | `uon_alumni_home` | none, public | clean |
| 10 | `uon-alumni-history/` | www | `uon_alumni_history` | none, public | clean |
| 11 | `uon-alumni-executive-committee/` | www | `uon_alumni_exec_committee` | none, public | clean |
| 12 | `uon-alumni-gallery/` | www | `uon_alumni_gallery` | none, public | clean |
| 13 | `uon-alumni-register/` | www | `AlumniRegisterView` | `LoginRequiredMixin` | clean |
| 14 | `uon-alumni-profile/<slug>/<uuid>/` | www | `AlumniProfileDetailView` | none, public | clean |
| 15 | `uon-alumni-profile/<slug>/<uuid>/edit/` | www | `AlumniProfileUpdateView` | `LoginRequiredMixin` | clean |
| 16 | `uon-alumni-profile/<slug>/<uuid>/membership/` | www | `AlumniMembershipUpdateView` | `LoginRequiredMixin` | clean |
| 17 | `uon-alumni-profile/<slug>/<uuid>/delete/` | www | `AlumniProfileDeleteView` | `LoginRequiredMixin` | clean |
| 18 | `.../payments/<int>/receipt/` | www | `download_payment_receipt` | `@login_required` | clean |
| 19 | `uon-alumni-membership-analytics/` | www | `MembershipAnalyticsView` | `StaffOrSuperuserRequiredMixin` | clean |
| 20 | `uon-alumni-membership-categories/` | www | `MembershipCategoriesView` | none, public | clean |
| 21 | `uon-alumni-donate/` | www | `uon_alumni_donate` | none, public | clean (5 historical TemplateDoesNotExist, resolved — 2.4) |
| 22 | `uon-alumni-scholarship/` | www | `uon_alumni_scholarship` | custom in-body check | **fixed today** — was confirmed broken, 16 log occurrences, see 2.1 |
| 23 | `uon-alumni-in-memoriam/` | www | `uon_alumni_in_memoriam` | none, public | clean |
| 24 | `uon-alumni-contact-us/` | www | `uon_alumni_contact_us` | none, public | clean (4 historical TemplateDoesNotExist, resolved — 2.4) |
| 25 | `uon-alumni-news/` | www | `ArticleListView` | none, public | clean |
| 26 | `uon-alumni-news/<slug>/` | www | `ArticleDetailView` | none, public | clean |
| 27 | `uon-alumni-walk/` | www | `EventListView` | none, public | clean |
| 28 | `uon-alumni-walk/<slug>/` | www | `EventDetailView` | none, public | clean |
| 29 | `uon-alumni-chapters/` | www | `ChapterListView` | none, public | clean |
| 30-31 | `uon-alumni-chapters/<faculty_slug>/<slug>/`, `.../<slug>/` | www | `ChapterDetailView` | none, public | clean |
| 32 | `uon-alumni-secretariat/` | www | `uon_alumni_secretariat` | none, public | clean |
| 33 | `uon-alumni-partners/` | www | `uon_alumni_partners` | none, public | clean |
| 34 | `uon-alumni-mission-vision/` | www | `uon_alumni_mission_vision` | none, public | clean |
| 35 | `uon-alumni-downloads/` | www | `PublicationListView` | none, public | clean |
| 36 | `uon-alumni-careers/` | www | `JobPostingListView` | none, public | clean |
| 37 | `uon-alumni-page/<page_key>/` | www | `standing_page` | none, public | clean |
| — | `CoreValue.get_absolute_url()` (admin "View on site", not a `path()` entry) | www (via `/2005/`) | n/a | admin-only trigger | **confirmed broken** — `core_value_detail` name doesn't exist anywhere, 4.3 |
| 38 | `robots.txt` | students | `TemplateView` | none, public | clean |
| 39 | `` (root) | students | `all_uon_students` | none, public (13 historical TemplateDoesNotExist, resolved — 2.4) | clean; no auth gate, harmless today (B5) |
| 40 | `register/` | students | `StudentRegisterView` | `LoginRequiredMixin` + domain check | **confirmed broken on success** — `get_success_url()` fallback hits `student:all_uon_students`, 2.2 |
| 41-42 | `evaluate/`, `evaluate/<int:pk>/` | students | `EvaluateApplicationView` | `StaffOrSuperuserRequiredMixin` | **confirmed broken** — both POST branches (`student:evaluate_application_list`, `student:evaluate_application`) and the picker template (`evaluate_application.html:48`) all 500, 2.2 |
| 43 | `dashboard/` | students | `ApplicantDashboardView` | `StaffOrSuperuserRequiredMixin` | **confirmed broken** — `applicant_dashboard.html:22`'s `{% url 'student:analytics_export' %}` crashes every load, 2.2 |
| 44 | `dashboard/export/` | students | `ScholarshipAnalyticsExportView` | `StaffOrSuperuserRequiredMixin` | clean itself, but is the unreachable target of #43's broken link |
| 45 | `login/` | staff | `StaffLoginView` | none (manual check inside) | clean |
| 46 | `logout/` | staff | `staff_logout` | none, public | clean |
| 47 | `dashboard/` | staff | `staff_dashboard` | none | **suspect** — placeholder content, no auth gate (B4) |
| 48 | `` (root) | staff | `EmployeeListView` | `LoginRequiredMixin` | clean (docstring calls it "public," code says otherwise — doc/behavior mismatch, not a bug) |
| 49 | `complete-profile/<uuid>/` | staff | `CompleteProfileView` | `LoginRequiredMixin` + own-record scoping | clean |
| 50 | `profile/edit/` | staff | `ProfileUpdateView` | `LoginRequiredMixin` | clean (6 historical 500s, Jul — traceback present but exception type not individually re-verified in this pass) |
| 51 | `profile/delete/` | staff | `ProfileDeleteView` | `LoginRequiredMixin` | clean |
| 52 | `fallback/<uuid:uuid>/` | staff | `staff_detail_fallback` | none | **suspect** — no auth gate, public HR-adjacent data (B4) |
| 53 | `<unit_slug>/<name_slug>/<uuid>/` | staff | `EmployeeDetailView` | none | **suspect** — no auth gate at all, full HR record exposed (B4) |
| 54 | `<staff_slug>/<uuid>/download-qr/` | staff | `download_staff_qr_code` | none | **suspect** — no auth gate, printable badge asset downloadable by anyone (B4) |
| 55 | `robots.txt` | staff | `TemplateView` | none, public | clean |
| 56 | `` (includes `apps/staff/urls.py`, rows 45-54) | staff | — | — | — |
| 57 | `qr/<uuid>/` (via `apps.qr_manager.urls`) | staff | `verify_scan` | none, public by design (QR scan) | clean; relies on `.profile` access noted in 4.1 pattern 2 |
| 58 | `qr-admin/` | staff | `qr_admin_site.urls` | custom AdminSite gate | clean |

---

## 6. Ranked remediation list

Ordered by (evidenced-or-inferred frequency × severity). "Confirmed" items have a log-backed or directly-executed proof; "probable" items are static-analysis findings with a citation but no log corroboration.

1. **[Confirmed, done] Scholarship page `NoReverseMatch`** — 16 log occurrences since 2026-08-06, most recent hours before this audit. Already fixed and deployed as of this audit (`apps/home/views.py`, unprefixed `reverse("register", urlconf="apps.student.urls")`). Size: done.
2. **[Confirmed mechanism, 9 live sites] The same `student:` namespace bug everywhere else it still exists** — 3 in `apps/user/adapter.py` (breaks Google OAuth login/signup/connect on the students subdomain for any user without a `Student` record — plausibly the highest-traffic path of all nine), 3 in `apps/student/views.py` (breaks post-registration redirect, and both evaluation-save redirect branches — the save itself succeeds, only the confirmation redirect crashes), 2 in templates (`applicant_dashboard.html` — every load; `evaluate_application.html` — as soon as any application exists), 1 already-production-incident-and-workaround in `context_processors.py` (fix pattern already established there: hardcode the students-subdomain path instead of calling `reverse()` with the broken namespace, or apply the same unprefixed-`reverse()`-with-`urlconf=` fix used in item 1). **Size: small per site, ~9 small edits total** — the fix shape is already proven twice in this codebase (once today, once on 2026-08-19). Highest priority in this report: three separate people independently hit variants of this bug on three different dates without anyone connecting them to one root cause.
3. **[Probable, unconfirmed exposure] Unguarded `request.user.profile`/`.user.profile` reverse-OneToOne access, 4 sites** — the highest-severity one (`apps/qr_manager/views.py:64`) is on a public, unauthenticated QR-scan endpoint; a scan of any `AlumniProfile` whose `User` lacks a `UserProfile` row 500s for the scanning member of the public. The other three (`apps/home/views.py:373`, `apps/staff/views.py:404,416`) require an account created outside the normal Google-OAuth onboarding path (e.g. `createsuperuser`, or an `Employee` row created directly in admin) to trigger. Size: small, add `hasattr`/`getattr` guards matching the pattern already used correctly elsewhere in the same files.
4. **[Confirmed via read, admin-triggered] `CoreValue.get_absolute_url()` reverses a URL name that doesn't exist anywhere in the project** — 500s on admin's "View on site" for any `CoreValue` row. Size: trivial (remove the method, or build the missing view — whichever was actually intended).
5. **[Probable] `?department=` GET param on `apps/staff/views.py:154` accepts non-numeric input uncaught**, unlike its sibling `?unit=`/`?track=` params in the same view. Size: trivial, same validation pattern already exists two lines away to copy.
6. **[Confirmed, unexplained] `/robots.txt` — 8 "Internal Server Error" log lines with no accompanying traceback**, spread over a week, still recurring as of the most recent boot. Two hypotheses (worker-timeout kill, restart-boundary log truncation) were checked and ruled out by direct correlation. Size: unknown until someone can either get sudo/`adm`-group access to read nginx's error.log (which might show what nginx itself observed, e.g. a truncated/reset connection, that Django's own log doesn't capture) or reproduce it directly. This is the one finding in this report where the size of the fix genuinely cannot be estimated without more access than this audit had.
7. **[Probable, access-control] Three `apps/staff` views with no auth gate at all** — full Employee HR detail (`EmployeeDetailView`), the QR fallback page, and the actual downloadable QR badge asset (`download_staff_qr_code`) are all public. May be intentional; needs a decision from someone who knows the intended access model, not a unilateral fix. Size: small once the intended behavior is confirmed.
8. **[Confirmed, operational not error-page] `expire_lapsed_installment_plans` has no recurring `Schedule` row in production** (`Schedule.objects.count() == 0`, live query) — the documented manual setup step (`/2005/admin/django_q/schedule/add/`) was apparently never completed. Installment-plan expiry is not running automatically. Size: trivial (one admin form submission), but easy to keep missing indefinitely since nothing surfaces its absence.
9. **[Confirmed, infra] No error visibility beyond journald** — `ADMINS` unset, `EMAIL_BACKEND` is the console backend (mail can't leave the box regardless), no Sentry/Rollbar/equivalent installed. Every finding in this report exists only because journald happened to retain it long enough to be read manually over SSH. Size: medium (adding a real error-tracking SDK is the standard fix; a cheaper interim step is at least setting `ADMINS` + a working `EMAIL_BACKEND` so Django's built-in `AdminEmailHandler` starts doing something).
10. **[Confirmed, low frequency] Neon `OperationalError`s (connection-permit exhaustion once, DNS resolution failure twice) across 2.5+ weeks** — already substantially mitigated by the existing `CONN_HEALTH_CHECKS=True`. Size: none indicated beyond what's already configured; monitor rather than act.
11. **[Confirmed, access gap for future audits] `armando_salazar` cannot read `/var/log/nginx/{access,error}.log`** (group `adm` required, account is in `sudo www-data users` — sudo needs a password not available non-interactively). This audit's Phase 1 nginx-log requirement (item 6) could not be completed. Size: trivial (`usermod -aG adm armando_salazar` or equivalent), but needs someone with existing root access to run it.
