# Coverage priority 3 — OAuth adapter covered

**Date:** 2026-09-01
**Branch:** `coverage/phase-1`
**Commit:** `1bfcf57`
**Executes:** [`coverage-phase1-adapter-step1-2026-09-01.md`](coverage-phase1-adapter-step1-2026-09-01.md)

**No production code changed.** `git status` showed only `apps/user/tests.py`.

---

## Result

| | Before | After |
|---|---:|---:|
| `apps/user/adapter.py` | 24% | **86%** |
| `apps.user` (app total) | 57% | 84% |
| Overall | 61% | 63% |
| Suite | 136 tests | **164 tests, all green** |

28 tests. Remaining uncovered in `adapter.py` (30 of 210 statements): the claim-expiry branches at 60-73, `_ensure_profile`'s create-from-scratch path at 103-113, and `get_connect_redirect_url`'s staff branch at 533-545.

---

## Findings: one confirmed, two retracted

### ✅ Finding B — CONFIRMED. A live 500 on the login path.

`apps/user/adapter.py:220`:

```python
def _admin_onboarding_redirect_url(user, request):
    employee = _ensure_employee(user)
    if not employee.profile_is_complete:
        path = reverse("staff:complete_profile", ..., urlconf=STAFF_URLCONF)
        return _staff_subdomain_url(request, path)          # absolute
    if not hasattr(user, "alumni_profile"):
        return reverse("home:uon_alumni_register")          # BARE -- line 220
```

The asymmetry inside a single function is the tell: the first branch builds an **absolute** staff URL precisely because the user may be on another host, and the branch immediately below returns a **bare** reverse with no `urlconf=`.

`reverse()` without `urlconf` resolves against the request's urlconf, which `SubdomainRoutingMiddleware` sets from the host. On the staff subdomain that is `apps.staff.site_urls`, where the `home` namespace is not registered.

**Reproduced.** `LoginRedirectResolutionTests.test_admin_staff_without_alumni_profile_on_the_staff_host` raises `NoReverseMatch` for an `is_staff` non-superuser with a complete Employee record and no `AlumniProfile`, logging in on `staff.`

The test **asserts the raise**, as instructed — so it is green while documenting a defect, and must be inverted when the bug is fixed. Same class as QA-500 finding 7, and not fixed here.

### ❌ Finding A — RETRACTED. I was wrong.

Step 1 claimed `get_connect_redirect_url` fell off its end and returned `None`. It does not. The file's true last line is:

```python
        return super().get_connect_redirect_url(request, socialaccount)
```

My earlier read window stopped just short of it, and I reported the absence of something I had simply not looked at. The test now pins the real behaviour — the apex correctly yields allauth's connections page.

### ❌ Finding C — RETRACTED as a defect, with a caveat.

Step 1 raised the strict-string comparison at `settings.py:535` as a fail-open risk. Checked against the live value:

```
.env:  RESTRICT_GOOGLE_LOGIN_DOMAINS=False
settings.RESTRICT_GOOGLE_LOGIN_DOMAINS = False
adapter module global                  = False
```

Correctly spelled and **deliberate** — `settings.py:532-534` documents exactly this for development. Not a casing accident, and nothing is mis-set.

The fragility itself stands as an observation: `os.getenv(...) == 'True'` means `true`, `TRUE`, `1` and `yes` would all silently disable the restriction, whereas `DJANGO_DEBUG` at `settings.py:44` is tolerant. Worth hardening one day; not a bug today.

---

## The retraction that changed the tests

Finding C being *true-but-deliberate* mattered more than finding C being a bug would have.

**The domain restriction is OFF in this environment.** The first run made that obvious: `test_foreign_domain_is_rejected_on_staff` expected a redirect to `/accounts/login/` and got `/accounts/signup/` — the staff login/signup gate firing, because the domain check had been skipped entirely.

Had I not chased that, all five domain-restriction tests would have **passed while asserting nothing**. They now force the flag on:

```python
        patcher = mock.patch.object(
            adapter_module, "RESTRICT_GOOGLE_LOGIN_DOMAINS", True
        )
```

`override_settings` cannot be used: `adapter.py:17-33` reads the three domain constants into module globals at import, so patching the module attribute is the only route. That constraint was identified in Step 1 and held up.

---

## Two security behaviours pinned along the way

Both surfaced while correcting my own failing assertions, and both are worth having recorded.

**`is_safe_url` requires HTTPS outside DEBUG.** `adapter.py:285` sets `require_https=not settings.DEBUG`, and the test runner forces `DEBUG` False — so plain `http` is refused *even for our own hosts*. My first attempt asserted `http://staff.lvh.me/` was safe and failed correctly.

**An `http` `post_login_next` is therefore refused.** The students test initially stashed `http://students.lvh.me/dashboard/` and got `/` back, because the session URL is filtered through `is_safe_url`. It now uses `https`, and a companion test confirms an off-site URL (`https://evil.example.com/`) is ignored.

---

## What is covered

| Group | Tests | Notes |
|---|---:|---|
| Domain restriction | 5 | staff, students and apex rules; the apex admits any Google account by design |
| Staff login/signup gate | 3 | login without an Employee → signup; signup with one → login |
| Record creation | 4 | existing-login sync, apex creating no Employee, the 2026-08-07 google-fields bug, the verified-claim connect path |
| `save_user` | 3 | including the adapter↔signal interaction |
| `get_login_redirect_url` | 7 | superuser bypass, admin onboarding, staff completeness, apex, students, `post_login_next`, and finding B |
| `get_signup_redirect_url` | 2 | unconditional routing on staff and students |
| `is_safe_url` / logout / connect | 4 | HTTPS requirement, DEBUG port variants, apex logout, connections fallback |

### The adapter ↔ signal interaction

`SaveUserTests.test_adapter_and_signal_yield_exactly_one_profile` proves the interaction the QA-500 invariant work created: the `post_save` receiver creates a blank-named `UserProfile` the moment the User is saved, `_ensure_profile`'s `getattr` guard at `adapter.py:100` then finds it, skips creation, and falls through to the `extra_data` block at `:117-123` which populates the names from Google.

**One row, names populated.** Nothing verified that until now.

### Mocking, in practice

No live OAuth, as predicted — both adapters only ever see an already-constructed `SocialLogin`, so real allauth classes work throughout and `is_existing` derives naturally from whether the user is saved.

One fixture detail worth carrying forward: **`User.google_sub` is unique**, so two identities sharing one `sub` raise `IntegrityError` in `setUp`. `_sociallogin()` now derives the sub per e-mail.

---

## Where the coverage build stands

| Priority | Area | Status |
|---:|---|---|
| 1 | `services.py` lifecycle | ✅ 100% |
| 2 | `expire_lapsed_installment_plans` | ✅ Covered |
| 3 | `adapter.py` OAuth | ✅ **86%** |
| 4 | `payments.py` branches and failure paths | 55% — **next** |
| 5 | `home/forms.py` registration and membership validation | 34% |
| 6 | `qr_manager` `generate_qr` and watermarking | 58% |
| 7 | `home/views.py` / `staff/views.py` POST handling | ~50% |
| 8 | `Membership` model behaviour | 86% |
| 9 | `tasks.py` e-mail and SMS | 18% |
| 10 | `import_legacy_memberships` | 0% |

## Decisions outstanding

1. **Finding B** — a small, well-understood fix: add `urlconf="main.urls"` to `adapter.py:220`, matching what `AlumniProfile.get_absolute_url()` already does at `models.py:1264`. Worth doing before continuing the coverage build, since it is a live login 500.
2. **Next target** — priority 4 (`payments.py`), or take finding B first?
3. **The `RESTRICT_GOOGLE_LOGIN_DOMAINS` parsing** — harden it to match `DJANGO_DEBUG`'s tolerant form, or leave it?
