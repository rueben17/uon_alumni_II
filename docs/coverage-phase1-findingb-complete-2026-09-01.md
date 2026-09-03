# Finding B completed — redirect lands on the right host

**Date:** 2026-09-01
**Branch:** `coverage/phase-1`
**Commit:** `6763ba1`
**Completes:** [`coverage-phase1-findingb-fix-2026-09-01.md`](coverage-phase1-findingb-fix-2026-09-01.md), which closed the crash and documented this residual

**Suite: 164 tests, all green.** `git status` showed only `apps/user/adapter.py` and `apps/user/tests.py`.

---

## Finding B took two commits, fixing two different things

Worth keeping distinct, because the first looked like a complete fix and was not:

| Commit | Fixed | Effect |
|---|---|---|
| `26dd281` | Which **urlconf** resolves the name | 500 → 404 |
| `6763ba1` | Which **host** serves the result | 404 → correct redirect |

Pinning `reverse(..., urlconf="main.urls")` stopped the `NoReverseMatch`. But `reverse` returns a **path**, and `_admin_onboarding_redirect_url` runs for *any* `is_staff` login regardless of host — so a browser on `staff.<domain>` requested `/uon-alumni-register/` from the staff urlconf, which has no `home:` routes at all, and got a 404.

An exception in the logs became a silent dead end. Arguably worse to diagnose, which is why the residual was asserted in the test docstring rather than left to memory.

---

## The convention, confirmed before writing

Both existing builders use an identical construction — `_staff_subdomain_url` (`adapter.py:176-189`) and `get_logout_redirect_url` (`:393-402`):

```python
    base = settings.SUBDOMAIN_DOMAIN
    host = request.get_host()
    port = f":{host.split(':')[1]}" if ":" in host else ""
    scheme = "https" if request.is_secure() else "http"
```

Two details that matter, and that a fresh helper could easily have got wrong:

- **Scheme comes from `request.is_secure()`**, not from `DEBUG`.
- **The port is preserved whenever the host carries one**, also not gated on `DEBUG`.

`_apex_url` follows both exactly. Only the host differs:

```python
    return f"{scheme}://{base}{port}{path}"      # _apex_url
    return f"{scheme}://staff.{domain}{port}{path}"   # _staff_subdomain_url
```

### On sharing the four lines

`get_logout_redirect_url` is effectively `_apex_url(request, "/")`. Collapsing it would be tidier, but that is a redirect this pass was not authorised to change, so the construction is **duplicated deliberately** and the cleanup noted in the commit message. Both helpers were verified untouched: the only diff lines naming them are inside the new docstring.

---

## The change

`apps/user/adapter.py` — new helper, placed directly after `_staff_subdomain_url` so the pair reads together:

```python
def _apex_url(request, path):
    """
    Build an absolute URL on the apex (no subdomain), preserving the dev
    port -- the mirror of _staff_subdomain_url above ...

    Needed for the same reason: a bare path returned to a browser sitting
    on staff.<domain> is requested from the STAFF urlconf, which has no
    home: routes at all, so it 404s. Pinning the reverse to main.urls
    fixes which urlconf resolves the name; this fixes which host serves
    the result.
    """
```

and the call site:

```python
    if not hasattr(user, "alumni_profile"):
        return _apex_url(
            request, reverse("home:uon_alumni_register", urlconf="main.urls")
        )
```

The branch four lines above already did exactly this for its own redirect. The sibling is now in line with it.

`apps/user/tests.py` — the fix-guard test asserts the absolute apex URL, and its `RESIDUAL` note is gone.

---

## Outcome

An `is_staff` non-superuser with a complete Employee record and **no** `AlumniProfile`, logging in on the staff subdomain, is now redirected to the apex register page — no 500, no 404, correct host.

| | |
|---|---|
| Suite | 164 tests, all green |
| `adapter.py` coverage | 86% |
| Overall coverage | 63% |
| `_staff_subdomain_url` / `get_logout_redirect_url` | unchanged in behaviour |

---

## Outstanding

1. **Optional cleanup:** have `get_logout_redirect_url` call `_apex_url(request, "/")` instead of rebuilding the URL inline. Pure tidying, no behaviour change, deliberately not done here.
2. **Coverage priority 4:** `apps/home/payments.py` at 55% — the branches and failure paths. Money movement, and next in the Phase 0 ranking.
