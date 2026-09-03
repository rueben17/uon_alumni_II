# `UserProfile` invariant — signal + slug apply pass

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Closes:** [`qa_500_report.md`](../qa_500_report.md) finding 5
**Executes:** [`qa-500-userprofile-design-2026-09-01.md`](qa-500-userprofile-design-2026-09-01.md), passes (a) signal and the decision-B slug fix

**Commits:** `e00e773` (correctness), `f868455` (tests)
**Status:** 🛑 **Stopped** — three fixtures outside the permitted edit list now collide. See [Blocked](#-blocked--three-out-of-scope-fixtures).

---

## What changed

| File | Change |
|---|---|
| `apps/user/signals.py` | **New.** `post_save` receiver `ensure_user_profile` on `User` |
| `apps/user/apps.py` | `UserConfig.ready()` imports the signals module |
| `apps/home/models.py` | `get_alumni_profile_slug` falls back to the model name when the derived name is empty |
| `apps/home/tests.py` | Finding 5 flipped and extended; fixtures adapted to the invariant |
| `apps/user/tests.py` | Nine receiver tests |

### The signal

```python
@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    UserProfile.objects.get_or_create(user=instance)
```

A receiver rather than a `UserManager` override, because the override only covers `create_user()` and is bypassed by `User.objects.create()`, `User(...).save()`, the admin's add form and `loaddata` — exactly the paths that produced today's profile-less accounts. It honours `raw` (loaddata fires `post_save` before related tables are populated) and uses `get_or_create`, so it is idempotent alongside `adapter.py:111`, which may create the profile in the same request.

**No field values are supplied.** `given_name`/`family_name` are `CharField`s defaulting to `""`, so the row is valid with blank names. Deriving a name from the e-mail local part would fabricate identity data, and the DPA-2019 consent flags stay `False` by their own defaults — `models.py:203-205` is explicit that consent cannot be pre-granted.

### Wiring — a new convention, deliberately

There was **no existing signals convention**: no `signals.py`, no `AppConfig.ready()`, no `@receiver` anywhere in the project. Rather than invent an ad-hoc mechanism, this establishes the standard Django one — receivers in `signals.py`, connected from `ready()`.

No new `AppConfig` and no settings change were needed: `UserConfig` already existed at `apps/user/apps.py:4`, and `'apps.user'` in `INSTALLED_APPS` auto-discovers it, so `ready()` runs.

### The slug fix — decision B

The invariant alone would have **moved** finding 5's crash rather than closing it.

A blank name slugifies to `""`. `AlumniProfile.slug` is `blank=True, null=True`, and django-autoslug leaves the field `None` in that case (`autoslug/fields.py:267-273`):

```python
        if not slug:
            slug = None
            if not self.blank:
                slug = instance._meta.model_name
            elif not self.null:
                slug = ''
```

`get_absolute_url()` then reverses `home:alumni_detail` with `slug=None`, and the route matches `<slug:slug>` — never `None`. So the failure would have relocated from `save()` to URL reversal.

`get_alumni_profile_slug` now returns `slug or instance._meta.model_name`, which is exactly what autoslug already does for `Employee.slug` (neither `blank` nor `null`, so it falls back to `"employee"`). Mirroring rather than inventing.

**Uniqueness confirmed non-colliding:** `AlumniProfile.slug` is `unique=False` (`models.py:1188`), so blank-named profiles may share the `"alumniprofile"` placeholder; the UUID in the URL keeps them distinct. `always_update=True` upgrades it to a real slug the moment a name is entered.

---

## Tests — all green

**`apps/user/tests.py` — nine receiver tests.** All four creation paths (`create_user`, `create_superuser`, `User.objects.create`, `User(...).save()`) yield a profile; exactly one per user; resaving creates no second; idempotent alongside the adapter; `raw` saves create nothing; no identity data invented and both consent flags `False`.

**`apps/home/tests.py` — finding 5 flipped and extended.** The `AlumniProfile` now saves for a blank-named user; the placeholder slug resolves through `get_absolute_url()`; two blank-named profiles share the slug without colliding; the slug upgrades once a name is entered; the old *"created superuser has no profile"* test is **inverted** to assert presence, pinning the invariant. A deleted profile still raises `ObjectDoesNotExist`, pinning the exception type for the window before the backfill.

**44 tests green** across `apps.user` and `apps.home`.

---

## 🛑 Blocked — three out-of-scope fixtures

`UserProfile`'s pk **is** the user's pk, so any fixture calling `UserProfile.objects.create(user=u, ...)` now collides with the auto-created row:

```
IntegrityError: duplicate key value violates unique constraint "user_userprofile_pkey"
```

| File | Line | Class affected |
|---|---|---|
| `apps/staff/tests.py` | 40 | `NavbarStaffHostGuardTests` |
| `apps/staff/tests.py` | 228 | `StaffEmployeeGatingTests` |
| `apps/qr_manager/tests.py` | 671 | `VerifyScanMissingProfileTests` |

Each needs the same mechanical change already applied in `apps/home/tests.py` — fill in the auto-created profile rather than creating one:

```python
profile = user.profile
profile.given_name = "Test"
profile.family_name = "Person"
profile.save(update_fields=["given_name", "family_name"])
```

Test-only; no production code involved. Left untouched because `apps/staff/tests.py` is outside this pass's "Edit only" list and editing `qr_manager` is an explicit stop condition.

**Note:** the `qr_manager` site is `VerifyScanMissingProfileTests`, added during an earlier pass of this sweep — **not** the pre-existing fixture. The four pre-existing `Employee() got unexpected keyword arguments: 'given_name', 'family_name'` errors remain untouched regardless.

**Awaiting approval to fix all three.**

---

## The design missed this

[`qa-500-userprofile-design-2026-09-01.md`](qa-500-userprofile-design-2026-09-01.md) enumerated production creation paths and read sites thoroughly, but did not consider that **test fixtures** create profiles explicitly. That is an obvious consequence of a pk-sharing `OneToOneField` and should have been caught at design time. Recorded here so the next invariant-style change looks for it.

---

## Suite state

**72 tests, 7 errors.**

| Group | Count | Cause |
|---|---|---|
| Pre-existing `qr_manager` fixture errors — untouched | 4 | `Employee()` kwargs, predates this sweep |
| Fixture collisions introduced by this pass | 3 | The table above — awaiting approval |

Finding 5's own tests are green. `git status` showed only the five in-scope files.

---

## Not done this pass, by design

- **Badge fallback (finding 4, decision A)** — `display_name` → `label` → invalid-scan page, at `apps/qr_manager/views.py:90` and `:133`. Next pass.
- **Backfill data migration** — idempotent `get_or_create` for existing profile-less users. The pass after, once the signal has stopped new ones appearing. Dev holds 1 profile-less user of 5; the production count is still unknown and should be taken first.

---

## Finding status — eight of nine closed

| # | Finding | Tier | State |
|---|---|---|---|
| 1 | migrate-from-zero | B | ✅ Closed (`68bb77c`) |
| 2 | `current_for()` ignores status | B | ✅ Closed (`01630c2`, `81ee434`) |
| 3 | `renew_membership()` wrong tier | B | ✅ Closed (same) |
| 4 | Badge scan 500 on missing profile | B | 🟡 Root cause closed; **badge fallback still to do** |
| 5 | Profile-less user breaks slug save | B | ✅ **Closed** (`e00e773`, `f868455`) |
| 6 | `AlumniProfileDetailView` ungated | B | ✅ Closed (`2d452ed`, `663bb73`) |
| 7 | Navbar substring host guard | A | ✅ Closed (`c307f84`) |
| 8 | `student:` namespace | A→B | ✅ Closed (`bab912d`) |
| — | Staff mis-gating cluster | B | ✅ Closed (`a1771ea`) |

Finding 4's *root cause* is now closed for every newly created account — what remains is the fallback for a profile that is blank-named or deleted after the fact, plus the backfill for existing accounts.
