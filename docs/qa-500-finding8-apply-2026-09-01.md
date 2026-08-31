# Finding 8 — `student:` namespace — apply pass

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Closes:** [`qa_500_report.md`](../qa_500_report.md) finding 8
**Executes:** [`qa-500-finding8-step1-2026-09-01.md`](qa-500-finding8-step1-2026-09-01.md) — the Step 1 work order, all three decisions approved

**Commit:** `bab912d`

---

## What changed

| Task | File | Change |
|---|---|---|
| 1 | `apps/student/site_urls.py` | **New.** `path('', include('apps.student.urls'))` plus the dev-only `static()` block. No `robots.txt` line. |
| 2 | `main/settings.py` | `SUBDOMAIN_URLCONFS['students']` → `'apps.student.site_urls'`, in **both** `if DEBUG:` branches. Nothing else. |
| 3 | `templates/student/applicant_dashboard.html:22` | `{% url 'analytics_export' %}` → `{% url 'student:analytics_export' %}` |
| 4 | `templates/student/evaluate_application.html:48` | `{% url 'evaluate_application' pk=applicant.pk %}` → `{% url 'student:evaluate_application' pk=applicant.pk %}` |
| 5 | `apps/student/views.py:95` | `reverse("all_uon_students")` → `reverse("student:all_uon_students")` |
| 6 | `apps/student/tests.py` | Finding 8's tests flipped from asserting `NoReverseMatch` to asserting resolution |

`apps/student/urls.py` was **not** edited — `app_name = 'student'` was already at line 5, and the include is what activates it.

### The settings diff, in full

```diff
@@ -416,7 +416,7 @@ if DEBUG:
         'staff':    'apps.staff.site_urls',
-        'students': 'apps.student.urls',
+        'students': 'apps.student.site_urls',
@@ -424,7 +424,7 @@ else:
         'staff':    'apps.staff.site_urls',
-        'students': 'apps.student.urls',
+        'students': 'apps.student.site_urls',
```

One logical line, two textual edits, as approved. No other line of `main/settings.py` touched.

### Why `apps/student/views.py:95` mattered

`StudentRegisterView.get_success_url()` reverses with **no `urlconf=`**, so it resolves against `request.urlconf` — which the middleware sets from `SUBDOMAIN_URLCONFS['students']`. The moment that became a namespaced include, the bare name would have raised `NoReverseMatch` on the **registration success redirect**: a live 500 immediately after a student signs up. Without this one-line fix, namespacing would have traded a latent bug for a live one.

---

## Verification

```
adapter STUDENT_URLCONF = apps.student.urls
  reverse(register, adapter pin)      -> /register/
  reverse(register, home/views pin)   -> /register/
  SUBDOMAIN_URLCONFS[students]        -> apps.student.site_urls
  reverse(student:all_uon_students)   -> /
  robots.txt via include              -> /robots.txt
```

- **The five non-breaking sites still resolve** and were not touched: `apps/user/adapter.py:333`, `:384`, `:545` and `apps/home/views.py:1120` all pin `STUDENT_URLCONF = "apps.student.urls"` — the inner module by name — so their bare reverses are unaffected. `apps/home/context_processors.py:270-271` hardcodes paths and never reverses, so the site-wide-crash risk recorded there could not be reached.
- **`robots.txt` still serves at `/robots.txt`** through the namespaced include, as `student:robots_txt`. No duplicate route was needed, and nothing reverses that name anywhere.
- **Both templates render** on `students.lvh.me` without `NoReverseMatch` — covered by `ScholarshipAnalyticsEmptyDatasetTests`, which drives `/dashboard/` and `/evaluate/` on that host.

### Tests

| Test | State |
|---|---|
| `student:` resolves via the subdomain urlconf | new, green |
| All five student routes reverse namespaced | new, green |
| Bare names still reverse against the inner module | new, green — **see below** |
| `subdomain_url` builds register and dashboard links | flipped, green |
| Registration success URL resolves under the subdomain urlconf | new, green |

---

## One addition beyond the strict work order

A **test**, not a code change: `test_bare_names_still_reverse_against_the_inner_module` pins that `reverse("register", urlconf="apps.student.urls")` still resolves.

That is the single non-obvious fact keeping four live call sites alive. They survive namespacing only because `apps/user/adapter.py:36` names the inner module rather than reading `SUBDOMAIN_URLCONFS`. Anyone later "tidying" those four to use the settings mapping would silently reintroduce the break, on a path that includes social login. A comment alone seemed too weak a guard.

---

## Suite state

**66 tests, 7 failures.** Down from 9 — finding 8's two errors are gone. Nothing else moved.

| Group | Count |
|---|---|
| Pre-existing `apps/qr_manager/tests.py` fixture errors — untouched | 4 |
| Finding 4 — badge scan, missing `UserProfile` | 1 |
| Finding 5 — profile-less user breaks slug save | 1 |
| Finding 6 — `AlumniProfileDetailView` ungated | 1 |

---

## Scope

`git status` showed only the in-scope files plus the new `apps/student/site_urls.py`. No migration, dependency or real-data change; `apps/student/urls.py`, `apps/home/*`, `apps/user/adapter.py`, `context_processors.py` and `apps/qr_manager/tests.py` all untouched.

---

## Finding status

| # | Finding | Tier | State |
|---|---|---|---|
| 1 | migrate-from-zero | B | ✅ Closed (`68bb77c`) |
| 2 | `current_for()` ignores status | B | ✅ Closed (`01630c2`, `81ee434`) |
| 3 | `renew_membership()` wrong tier | B | ✅ Closed (same) |
| 4 | Badge scan 500 on missing profile | B | 🛑 Open — needs a display decision |
| 5 | Profile-less user breaks slug save | B | 🛑 Open — same root cause as #4 |
| 6 | `AlumniProfileDetailView` ungated | B | 🛑 Open — needs an intent decision |
| 7 | Navbar substring host guard | A | ✅ Closed (`c307f84`) |
| 8 | `student:` namespace | A→B | ✅ **Closed** (`bab912d`) |
| — | Staff mis-gating cluster | B | ✅ Closed (`a1771ea`) |

**Six of the nine closed.** The three remaining are blocked on decisions rather than work:

1. **Findings 4 and 5** — guarantee the `UserProfile` invariant (create it in `UserManager`/a signal) or guard each read site, and decide what a profile-less badge should display. The invariant option also wants a backfill, which is a separate approved data migration.
2. **Finding 6** — is the alumni profile page a public directory, members-only, or owner-only?
