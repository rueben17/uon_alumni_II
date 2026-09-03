# Finding B fix + `RESTRICT_GOOGLE_LOGIN_DOMAINS` hardening

**Date:** 2026-09-01
**Branch:** `coverage/phase-1`
**Commits:** `26dd281` (the 500 fix), `590f42f` (parse hardening)
**Follows:** [`coverage-phase1-adapter-apply-2026-09-01.md`](coverage-phase1-adapter-apply-2026-09-01.md)

Two separate commits, so the live-500 fix is revertable independently of the settings change. **Suite: 164 tests, all green.**

---

## Commit 1 — the login 500

### Confirmed before editing

| Check | Result |
|---|---|
| Where the `home` namespace lives | `main/urls.py:77` — `path("", include('apps.home.urls', namespace="home"))` |
| What the pinned reverse yields | `reverse('home:uon_alumni_register', urlconf='main.urls')` → `/uon-alumni-register/` |
| The pattern being mirrored | `AlumniProfile.get_absolute_url()` pins its reverses to `urlconf="main.urls"` for the same reason |

### The change

`apps/user/adapter.py`, inside `_admin_onboarding_redirect_url`:

```python
    if not hasattr(user, "alumni_profile"):
        # Pinned to main.urls, same as AlumniProfile.get_absolute_url():
        # this runs for any is_staff login regardless of host, and on the
        # staff subdomain the request urlconf is apps.staff.site_urls,
        # where the `home` namespace does not exist at all -- an
        # unpinned reverse raised NoReverseMatch and 500ed the login.
        return reverse("home:uon_alumni_register", urlconf="main.urls")
```

One kwarg. No refactor of `_admin_onboarding_redirect_url` or of the redirect resolution.

### The test, inverted

`LoginRedirectResolutionTests.test_admin_staff_without_alumni_profile_on_the_staff_host` no longer asserts `NoReverseMatch`; it asserts the resolved URL, and its docstring now reads as a fix-guard rather than a reproduction.

---

## ⚠ Residual — asserted in the test, deliberately not fixed

**The one-kwarg fix stops the crash. It does not fully fix the redirect.**

`reverse(..., urlconf="main.urls")` returns a **path**: `/uon-alumni-register/`. But `_admin_onboarding_redirect_url` runs for *any* `is_staff` login **regardless of host**, so a browser sitting on `staff.uonalumni.or.ke` will request that path from the staff host — where `apps.staff.site_urls` has no such route.

**The user goes from a 500 to a 404.** No longer a crash, and no longer an exception in the logs, but the redirect still points at the wrong host.

The branch four lines above already solves precisely this problem:

```python
        path = reverse("staff:complete_profile", ..., urlconf=STAFF_URLCONF)
        return _staff_subdomain_url(request, path)          # absolute
```

The equivalent here would be an absolute **apex** URL, built the way `get_logout_redirect_url` (`adapter.py:388-398`) already builds one — scheme, `settings.SUBDOMAIN_DOMAIN`, and the dev port preserved.

That is a behaviour change beyond the authorised one-kwarg edit, so this pass stopped short of it. The residual is written into the test's docstring so it cannot be forgotten:

> RESIDUAL, deliberately asserted: the result is a PATH on the apex, so a browser sitting on `staff.<domain>` will request it from the staff host and get a 404.

**Recommended follow-up:** an `_apex_url(request, path)` helper mirroring `_staff_subdomain_url`, used at that one line. Small, and it completes the fix.

---

## Commit 2 — parse hardening

`main/settings.py`, previously a strict string comparison:

```python
RESTRICT_GOOGLE_LOGIN_DOMAINS = os.getenv('RESTRICT_GOOGLE_LOGIN_DOMAINS', 'True') == 'True'
```

now tolerant, matching `DJANGO_DEBUG` at `settings.py:44`:

```python
RESTRICT_GOOGLE_LOGIN_DOMAINS = os.getenv(
    'RESTRICT_GOOGLE_LOGIN_DOMAINS', 'True'
).strip().lower() in ('true', '1', 'yes')
```

The old form meant `true`, `TRUE`, `1` and `yes` all silently **disabled** the staff/students domain restriction — a security control failing open on a casing typo, while the convenience flag beside it was the forgiving one.

### Verified

```
'True' 'true' 'TRUE' ' True ' '1' 'yes'   -> True
'False' 'false' '0' 'no' ''               -> False

settings.RESTRICT_GOOGLE_LOGIN_DOMAINS = False
adapter module global                  = False      (unchanged)
```

**No behaviour change today.** `.env` sets `False` deliberately, exactly as `settings.py:532-534` documents for development, and both the setting and the adapter's module-level copy still resolve to `False`. The five domain-restriction tests patch the module attribute directly, so their path is unaffected.

---

## Scope

`git status` showed only `apps/user/adapter.py`, `apps/user/tests.py` and `main/settings.py`, split across the two commits as specified. No other adapter logic, no domain-constant values, no migrations, no requirements, no real data.

---

## Where things stand

| | |
|---|---|
| Suite | **164 tests, all green** |
| `adapter.py` coverage | 86% |
| Overall coverage | 63% |
| Findings from the adapter pass | B fixed (with residual), A and C retracted |

### Outstanding

1. **The residual wrong-host redirect** — add `_apex_url()` and use it at `adapter.py:220`. My recommendation: do it, it is the other half of this fix.
2. **Coverage priority 4** — `apps/home/payments.py` at 55%, the branches and failure paths. Money movement, and the next item in the Phase 0 ranking.
