# Coverage priority 3 — `apps/user/adapter.py` characterisation

**Date:** 2026-09-01
**Branch:** `coverage/phase-1`
**Baseline:** 24% (160 of 210 statements uncovered)
**Status:** 🛑 **Read-and-report only — no test written, no source touched.**

Google OAuth is the only authentication method in the system. The QA-500 sweep tested the gates thoroughly; this file is the door.

---

## Three candidate findings

Noted, **not fixed**, per the characterise-don't-fix rule. None is confirmed — each is a reading of the source that the Step 2 tests would settle.

### A. `get_connect_redirect_url` can return `None` (adapter.py:523-546)

```python
    def get_connect_redirect_url(self, request, socialaccount):
        ...
        if subdomain == "staff":
            ...
            return employee.get_absolute_url()

        if subdomain == "students" and not hasattr(user, "student"):
            return reverse("register", urlconf=STUDENT_URLCONF)
```

The method **ends there** — line 546 is blank. There is no final `return`, and no `super()` call. So connecting an additional social account on the **apex/www** host, or on `students` when the user *already has* a Student record, falls off the end and returns `None`.

`DefaultSocialAccountAdapter.get_connect_redirect_url` returns `reverse("socialaccount_connections")`. A `None` handed to a redirect is not a URL.

**Likely severity:** low reach — it fires only when an already-logged-in user connects a second social account, which may be unreachable in the current UI. Worth a test either way.

### B. A bare `home:` reverse that runs on the staff subdomain (adapter.py:220)

```python
def _admin_onboarding_redirect_url(user, request):
    employee = _ensure_employee(user)
    if not employee.profile_is_complete:
        path = reverse("staff:complete_profile", ..., urlconf=STAFF_URLCONF)
        return _staff_subdomain_url(request, path)          # absolute — correct

    if not hasattr(user, "alumni_profile"):
        return reverse("home:uon_alumni_register")          # BARE — line 220
```

Note the asymmetry: the Employee branch builds an **absolute** staff URL precisely because the user may be on another host, while the AlumniProfile branch immediately below returns a **bare** reverse with no `urlconf=`.

`reverse()` with no `urlconf` resolves against the *current request's* urlconf, which `SubdomainRoutingMiddleware` sets from the host. On `staff.uonalumni.or.ke` that is `apps.staff.site_urls`, where the `home` namespace **is not registered** — the same class of defect as QA-500 finding 7.

**Reached when:** an `is_staff` non-superuser, with a complete Employee record but no `AlumniProfile`, logs in **on the staff subdomain**. Expected result: `NoReverseMatch` → 500 on login.

Lines 329 and 379 make the same bare call, but both sit inside `subdomain in (None, "www")` branches where `home:` does resolve. Those are fine.

### C. The domain restriction fails **open** on a casing typo (settings.py:535)

```python
RESTRICT_GOOGLE_LOGIN_DOMAINS = os.getenv('RESTRICT_GOOGLE_LOGIN_DOMAINS', 'True') == 'True'
```

An exact string comparison. `true`, `TRUE`, `1` and `yes` all evaluate to `False` and **silently disable the domain restriction** on the staff and students subdomains.

Compare `DJANGO_DEBUG` at settings.py:44, which is tolerant: `.lower() in ("true", "1", "yes")`. The security-relevant flag is the strict one; the convenience flag is the lenient one.

`.env` sets this variable explicitly, so the live value should be checked. A fail-open security control is worth knowing about regardless of whether it is currently mis-set.

---

## Base classes and overridden methods

| Class | Base | Overrides |
|---|---|---|
| `CustomAccountAdapter` (:253) | `allauth.account.adapter.DefaultAccountAdapter` | `is_safe_url` (:270), `get_login_redirect_url` (:289), `get_signup_redirect_url` (:348), `get_logout_redirect_url` (:388) |
| `CustomSocialAccountAdapter` (:404) | `allauth.socialaccount.adapter.DefaultSocialAccountAdapter` | `pre_social_login` (:411), `save_user` (:494), `is_auto_signup_allowed` (:520), `get_connect_redirect_url` (:523) |

Eight module-level helpers: `_connect_verified_claim` (:43), `_ensure_profile` (:83), `_sync_google_account_fields` (:129), `_ensure_employee` (:148), `_staff_subdomain_url` (:176), `_admin_onboarding_redirect_url` (:191), `_employee_exists_for_email` (:225).

---

## The domain restriction, precisely

`pre_social_login` (:411-434), first branch:

```python
        role_domains = {"staff": ALLOWED_GOOGLE_LOGIN_DOMAINS, "students": ALLOWED_STUDENT_LOGIN_DOMAINS}
        if subdomain in role_domains and RESTRICT_GOOGLE_LOGIN_DOMAINS:
            email = sociallogin.account.extra_data.get("email", "")
            domain = email.split("@")[-1].lower()
            if domain not in role_domains[subdomain]:
                messages.error(request, "Please sign in using your University of Nairobi email.")
                raise ImmediateHttpResponse(redirect("account_login"))
```

| Host | Admitted | Source |
|---|---|---|
| `staff` | `uonbi.ac.ke`, `unes.uonbi.ac.ke`, `alumni.uonbi.ac.ke` | settings.py:520-521 |
| `students` | `students.uonbi.ac.ke` | settings.py:527-528 |
| apex / `www` | **Any Google account** | not in `role_domains`, so the branch is skipped |

**Rejection behaviour:** an error message plus `ImmediateHttpResponse(redirect("account_login"))` — a hard redirect raised as an exception, not a silent failure.

**The apex is deliberately unrestricted.** The comment at :417-424 explains why: most alumni lose `@uonbi.ac.ke` access at graduation, and restricting the public site "just silently blocked ordinary alumni from ever registering".

Note the adapter's own `getattr` fallbacks (`["uonbi.ac.ke"]` at :17-21) are **dead defaults** — `settings.py` always defines both names.

### The staff login-versus-signup gate (:436-457)

Distinct from the domain rule, and only on `staff`:

- `process == "login"` with **no** Employee for that e-mail → warning, redirect to `account_signup`
- `process == "signup"` **with** an existing Employee → warning, redirect to `account_login`

Students have no equivalent, deliberately (:453-457): every student's first sign-in *is* their signup.

---

## Post-login redirect resolution

`get_login_redirect_url` (:289-346), evaluated in this order:

| # | Condition | Returns |
|---:|---|---|
| 1 | not authenticated | `super()` |
| 2 | `is_superuser` | `admin:index` — bypasses the staff gate entirely (:299-305) |
| 3 | `is_staff` (non-super) | `_admin_onboarding_redirect_url(...)` or `admin:index` — **see finding B** |
| 4 | `subdomain == "staff"` | Employee incomplete → `staff:complete_profile` path via `STAFF_URLCONF`; complete → `employee.get_absolute_url()` |
| 5 | `subdomain in (None, "www")` | no `alumni_profile` → `home:uon_alumni_register` |
| 6 | `subdomain == "students"` | no `student` → `reverse("register", urlconf=STUDENT_URLCONF)`; else pop `post_login_next` from the session if `is_safe_url` |
| 7 | fallthrough | `super()` |

**Cross-subdomain URL building.** Only `_staff_subdomain_url` (:176-189) produces absolute URLs, and only `_admin_onboarding_redirect_url` calls it. Branches 4-6 return **paths**, which is correct because they only fire when the user is already on that host.

**The `STUDENT_URLCONF` pin.** Branch 6 uses `reverse("register", urlconf=STUDENT_URLCONF)` — the *bare* name against `apps.student.urls`, the inner module. This is exactly the fragile pin that QA-500 finding 8's `test_bare_names_still_reverse_against_the_inner_module` guards: it survives namespacing only because `STUDENT_URLCONF` names the inner module rather than reading `SUBDOMAIN_URLCONFS`. Three call sites depend on it — :341, :379, :545.

**`post_login_next`** is read from the session rather than a `next` GET param, and the comment at :371-377 explains why: allauth's own next-param handling takes priority over this method entirely and would bypass the "no Student record yet" branch above it.

`get_signup_redirect_url` (:348-386) is the same shape, minus the Student existence check (a brand-new signup cannot have one) and minus `post_login_next`.

`get_logout_redirect_url` (:388-398) always returns an absolute apex URL, port preserved, from any host.

`is_safe_url` (:270-287) enumerates `SUBDOMAIN_DOMAIN` plus each truthy key of `SUBDOMAIN_URLCONFS` — the `None` key is filtered out — adding `:8000` variants under `DEBUG`, and requires HTTPS when not in `DEBUG`. The docstring notes that `url_has_allowed_host_and_scheme` does **exact** host matching, so a leading-dot wildcard would never match.

---

## Adapter ↔ signal interaction on first social login

**No double creation.** `_ensure_profile` (:100-104) opens with:

```python
    profile = getattr(user, "profile", None)
    if profile is None:
        ...
        profile, created = UserProfile.objects.get_or_create(user=user, defaults=defaults)
```

On a brand-new signup the sequence is: `super().save_user()` saves the `User` → the `post_save` receiver in `apps/user/signals.py` creates a blank-named `UserProfile` → `_ensure_profile(user, extra)` then finds it via `getattr`, skips creation, and **falls through to the `if extra_data:` block at :117-123**, which populates `given_name`, `family_name`, `google_photo_url` and `locale` from Google and saves.

So the signal wins the race, and the adapter still populates the names. Both the `getattr` guard and the `get_or_create` are individually sufficient; together they are belt and braces. **This is worth an explicit test** — it is the interaction the QA-500 invariant work created, and nothing currently verifies it.

`_ensure_profile` is also called with **no** `extra_data` as a safety net (`_ensure_employee` at :162) precisely because `Employee`'s `AutoSlugField` reads `instance.user.profile`; the docstring at :92-97 says a no-`extra_data` call "never overwrites real data with blanks".

---

## Mocking boundary

**Good news: nothing here needs a live OAuth call.** The token exchange happens in allauth's provider views, upstream of this file. Both adapters only ever see an already-constructed `SocialLogin`, so the entire surface is reachable with hand-built objects.

| Thing | Approach |
|---|---|
| `sociallogin` | Build `SocialLogin(user=User(...), account=SocialAccount(provider="google", uid="...", extra_data={...}))` directly. Prefer allauth's own classes over a stub, so the `is_existing` / `state` / `connect()` semantics stay real. |
| `sociallogin.state` | A plain dict — set `{"process": "login"}` or `{"process": "signup"}` for the staff gate. |
| `sociallogin.is_existing` | Derived by allauth, not settable. **Verify its exact definition from the installed allauth before relying on it** — construct the two states via real objects rather than forcing the attribute. |
| `extra_data` | A dict: `email`, `sub`, `email_verified`, `given_name`, `family_name`, `picture`, `locale`. |
| `request` | `RequestFactory()`, then set `.subdomain` by hand (the middleware normally does it), attach a session, and attach message storage — `messages.error()` requires `request._messages`, so use `django.contrib.messages.storage.default_storage` or `FallbackStorage`. |
| `ImmediateHttpResponse` | Assert with `assertRaises`, then inspect `exc.response["Location"]`. |
| Domain settings | `override_settings` will **not** work: the three constants are read into module globals at import (:17-33). Patch `apps.user.adapter.RESTRICT_GOOGLE_LOGIN_DOMAINS` etc. directly, or use `unittest.mock.patch`. **This is a real constraint on the test design.** |
| Redirect resolution needing a host urlconf | For finding B, the urlconf must actually be the staff one. Either drive it through the test client with `HTTP_HOST="staff.lvh.me"`, or wrap the direct call in `django.urls.set_urlconf` as the backfill-migration tests already do. |

**Nothing is flagged untestable.** The one genuine constraint is the module-global settings capture, which rules out `override_settings` for the domain rule.

---

## Proposed test list — 26 tests

Marked ⌂ where an `lvh.me`-family `HTTP_HOST` (or an explicit urlconf) is required.

### `pre_social_login` — domain restriction (5)

1. A `uonbi.ac.ke` address is admitted on `staff`. ⌂
2. A `gmail.com` address is rejected on `staff` — `ImmediateHttpResponse`, redirect to `account_login`, error message queued. ⌂
3. A `students.uonbi.ac.ke` address is admitted on `students`; a `uonbi.ac.ke` address is **not**. ⌂
4. Any domain is admitted on the apex — the deliberate public-alumni case. ⌂
5. With `RESTRICT_GOOGLE_LOGIN_DOMAINS` patched false, a foreign domain is admitted on `staff`. ⌂

### `pre_social_login` — staff login/signup gate (3)

6. `process="login"` with no Employee → redirect to `account_signup`. ⌂
7. `process="signup"` with an existing Employee → redirect to `account_login`. ⌂
8. `process="login"` with an existing Employee proceeds. ⌂

### `pre_social_login` — record creation (4)

9. Existing user on `staff`: profile synced, Google fields set, Employee ensured. ⌂
10. Existing user on the apex: profile synced, **no** Employee created. ⌂
11. `_sync_google_account_fields` sets `google_sub`, `email_verified`, `auth_provider` on an existing login — the 2026-08-07 bug the docstring records.
12. A verified profile claim in session connects to the claimed user instead of creating a duplicate, and marks the claim `CONSUMED`.

### `save_user` (3)

13. A new signup populates User, profile names from `extra_data`, and Google fields.
14. On `staff`, an Employee is created; on the apex, it is not. ⌂
15. **Adapter ↔ signal:** exactly one `UserProfile` after a new social signup, with names populated from Google — the signal creates it blank, the adapter fills it.

### `CustomAccountAdapter.get_login_redirect_url` (6)

16. Superuser → `admin:index`, with **no** Employee stub created (the 2026-08-07 regression).
17. `is_staff` with an incomplete Employee → absolute staff-subdomain `complete_profile` URL. ⌂
18. **Finding B:** `is_staff`, complete Employee, no `AlumniProfile`, logging in on `staff` — assert what actually happens. ⌂
19. Plain user on `staff`, Employee incomplete → `complete_profile`; complete → `get_absolute_url()`. ⌂
20. Plain user on the apex with no `AlumniProfile` → `home:uon_alumni_register`. ⌂
21. Plain user on `students` with no Student → `register`; with a Student and a safe `post_login_next` in session → that URL, and the session key is popped. ⌂

### `get_signup_redirect_url` (2)

22. `staff` → `complete_profile` unconditionally, no existence check.
23. `students` → `register` unconditionally. ⌂

### `is_safe_url` / `get_logout_redirect_url` (3)

24. Accepts apex, `staff.`, `students.`; rejects an external host.
25. Under `DEBUG`, accepts the `:8000` variants.
26. Logout from any host returns the absolute apex URL with the port preserved. ⌂

### `get_connect_redirect_url` — finding A (1, folded into 26 above)

Connecting on the apex — assert the actual return value, expected `None`.

---

## Awaiting sign-off

Confirm the list — and, more importantly, how you want the three candidate findings handled. My recommendation: **write the tests to assert current behaviour**, and if B in particular reproduces a `NoReverseMatch`, raise it as a gated finding for a separate fix pass, exactly as the QA-500 sweep ran. Finding C is a settings question rather than a test one, and worth checking against the live `.env` value directly.
