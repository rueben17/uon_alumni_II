# Missing `UserProfile` — root fix design (findings 4 & 5)

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Findings:** [`qa_500_report.md`](../qa_500_report.md) #4 and #5
**Status:** design only. **No code, model, migration or settings changed; no database written.**

---

## Verdict — proceed, with two consequences that change the shape of the work

**Step 1 blocker check: PASSED.** Auto-creation needs no invented data.

But guaranteeing the invariant does **not**, on its own, fix what either finding actually shows a user. It converts both from an exception into a *silently degraded* state, and for one of them into a different exception. Both need handling in the same pass:

1. **A blank-named profile renders an anonymous badge.** `display_name` becomes `""`, so finding 4's public scan page shows a card with no name rather than 500ing. The badge fallback must therefore key on **an empty `display_name`**, not merely on a missing profile.
2. **A blank-named `AlumniProfile` gets `slug = None`**, and `get_absolute_url()` then raises `NoReverseMatch`. Finding 5's crash moves from `save()` to URL reversal. `Employee` is unaffected — the two `AutoSlugField`s are configured differently.

Neither is a reason to change direction. Both are reasons the apply pass is larger than "add a signal".

---

## Step 1 — required fields

`UserProfile` (`apps/user/models.py:174-210`). Only two fields have no explicit default and are neither `blank` nor `null`:

```python
    given_name = models.CharField(max_length=255)
    family_name = models.CharField(max_length=255)
```

Confirmed by introspection (no DB write):

```
given_name    CharField   empty_strings_allowed=True   get_default()=''
family_name   CharField   empty_strings_allowed=True   get_default()=''
```

`blank=True` is a form-validation concern, not a database constraint. Both are `CharField`s with `empty_strings_allowed = True`, so `get_default()` returns `''` and `UserProfile.objects.create(user=u)` succeeds, storing empty strings. **No invented data, no schema change, no blocker.**

Every other field is `blank=True`, `null=True`, or carries a default (`nationality="Kenyan"`, `sms_opt_in=False`, `email_opt_in=False`, `google_photo_url=""`, timestamps auto).

### The consequence

`full_name` (`models.py:220-235`) joins `given_name`, `middle_name` and `family_name`, so it returns `""`. `display_name` (`models.py:237-241`) prefixes an honorific that is also blank, so it too returns `""`.

An auto-created profile is therefore **structurally valid and semantically empty**.

---

## Step 2 — creation paths

| Site | Expression | Note |
|---|---|---|
| `apps/user/adapter.py:111` | `profile, created = UserProfile.objects.get_or_create(user=user, defaults=defaults)` | The real path — Google login, fills names from `extra_data` |
| `apps/home/management/commands/import_legacy_memberships.py:214` | `profile, _ = UserProfile.objects.get_or_create(user=user)` | Legacy import |
| `apps/home/forms.py:282` | `profile = getattr(user, "profile", None) or UserProfile(user=user)` | **Not previously listed.** Unsaved instance, saved by the form — already null-tolerant |
| `apps/staff/forms.py:218` | `profile = getattr(user, "profile", None) or UserProfile(user=user)` | **Not previously listed.** Same pattern |

**`UserManager` creates nothing** (`apps/user/models.py:25-47`) — `create_user` builds the `User`, calls `set_password`, saves, returns. `create_superuser` just sets flags and delegates to it. So `manage.py createsuperuser`, the shell, the Django admin's add form, and any future non-social signup all produce a profile-less `User`.

### Profile-less users today (dev database, read-only)

```
users total          : 5
users WITHOUT profile: 1
  of which superusers: 0
  of which staff     : 0
```

Small, and dev-only. **The production count is unknown** — I have no access and did not attempt any. It should be taken before the cleanup migration runs, since it sizes the backfill.

---

## Step 2 — read sites

**Templates are safe.** `ObjectDoesNotExist` sets `silent_variable_failure = True`, so `{{ user.profile.display_name }}` renders empty rather than raising. Nine templates read through `user.profile.*`; none can 500.

**Python reads raise.** Marked below.

### 500-on-missing — unguarded

| Site | Expression | Exposure |
|---|---|---|
| `apps/qr_manager/views.py:90` | `"display_name": alumni_profile.user.profile.display_name` | **Public, anonymous** — finding 4 |
| `apps/qr_manager/views.py:133` | `"display_name": employee.user.profile.display_name` | **Public, anonymous** — finding 4 |
| `apps/home/models.py:1091` | `profile = instance.user.profile` (`get_alumni_profile_slug`) | Save-time — finding 5 |
| `apps/staff/models.py:28` | `profile = instance.user.profile` (`get_employee_slug`) | Save-time — finding 5 |
| `apps/home/models.py:1245` | `return self.user.profile.full_name` | Authenticated |
| `apps/home/models.py:1251` | `return self.user.profile.display_photo_url` | Authenticated |
| `apps/home/models.py:1721` | `f"{self.alumni.user.profile.full_name} - ..."` | `Payment.__str__` — admin |
| `apps/home/views.py:706` | `safe_name = slugify(alumni.user.profile.display_name) or "alumni"` | Owner-only |
| `apps/home/views.py:731` | `display_name = alumni.user.profile.display_name` | Owner-only |
| `apps/staff/views.py:423`, `:435` | same shape, employee badge | Owner-or-admin |
| `apps/staff/models.py:362`, `:434` | `self.user.profile.date_of_birth`, `.display_name` | Save/`__str__` |
| `apps/student/models.py:185` | `self.user.profile.display_name` | `__str__` |
| `apps/qr_manager/admin.py:22`, `:29`, `:138`, `:263` | `.full_name` | Admin |
| `apps/qr_manager/models.py:151` | `holder.user.profile.full_name if holder else (self.label or "unassigned")` | `__str__` — guards a missing *holder*, not a missing *profile* |
| `apps/home/tasks.py:37`, `:99`, `:140` | `.given_name` in e-mail bodies | Background jobs |
| `apps/student/tasks.py:38` | `.given_name` | Background job |

### Already safe — guarded with `hasattr`

`apps/home/admin.py:80`, `:555`; `apps/qr_manager/admin.py:423`; `apps/staff/admin.py:140`.

Four defensive guards, all in admin display methods — evidence the authors already knew this could be missing, but only patched where it bit them.

**The invariant retires every row above at once.** That is its whole appeal over guarding 20+ sites.

---

## Step 4 — mechanism: `post_save` signal

**Recommended over a `UserManager` override.**

A `UserManager` override only covers `User.objects.create_user(...)`. It is bypassed by `User.objects.create(...)`, `User(...).save()`, the Django admin's add form (a `ModelForm` calling `save()`), and `loaddata`. Those are exactly the paths that produce today's profile-less accounts, so the override would leave the hole it is meant to close.

A `post_save` signal on `User` fires on every one of them.

```python
@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, raw=False, **kwargs):
    """Every User has a UserProfile -- an invariant, not a convention.

    UserManager.create_user does not create one, so any account made by
    createsuperuser, the shell, the admin's add form or a future
    non-social signup previously had none, and ~20 unguarded
    `user.profile.*` reads raised RelatedObjectDoesNotExist. See
    qa_500_report.md findings 4 and 5.

    Names are left blank rather than derived from the e-mail address:
    inventing a person's name is worse than showing none, and the Google
    adapter fills them properly on first login
    (apps/user/adapter.py:111).
    """
    if raw or not created:
        return
    UserProfile.objects.get_or_create(user=instance)
```

**Field values supplied: none.** Field defaults apply — `given_name=''`, `family_name=''`, `nationality='Kenyan'`, both consent flags `False`. Deliberately not deriving a name from the e-mail local part: that fabricates identity data, and DPA-2019 consent flags must stay `False` by default (`models.py:203-205`: *"consent cannot be pre-granted"*).

**`raw` guard is required.** During `loaddata`, related tables may not be populated and signals must not fire.

**`get_or_create`, not `create`** — makes the receiver idempotent and safe alongside the adapter, which may have created the profile already in the same request.

---

## Step 5 — cleanup migration (separate, gated step)

A data migration in `apps.user`, **not bundled with the signal**:

```python
def backfill(apps, schema_editor):
    User = apps.get_model("user", "User")
    UserProfile = apps.get_model("user", "UserProfile")
    for pk in User.objects.filter(profile__isnull=True).values_list("pk", flat=True).iterator():
        UserProfile.objects.get_or_create(user_id=pk)
```

- **Idempotent** — `get_or_create` keyed on the user; inert where a profile exists.
- **Reverse is a no-op** — never delete profiles on rollback; they may have been edited since.
- Uses `apps.get_model`, so the historical model is used and the signal does **not** fire (signals are not connected for historical models) — no double-creation.
- `values_list(...).iterator()` keeps memory flat on a large table.

**Sequencing matters:** the signal closes the intake, the migration cleans the backlog. Landing the migration without the signal would leave new profile-less accounts appearing immediately.

---

## Step 6 — badge fallback

### What the fields actually contain

`QRCode.label` (`apps/qr_manager/models.py:117`):

```python
    label = models.CharField(max_length=255, blank=True, default="")
```

with the comment at `:115-116`: *"Human label for codes with no employee\alumni: visitor's name, event name, contractor company — whatever identifies the holder."*

So `label` is populated for **holder-less** codes (visitor and event passes) and is normally **empty** for a code linked to an `Employee` or `AlumniProfile` — which is exactly the case finding 4 is about. There is precedent for it as a fallback, at `models.py:151`:

```python
        name = holder.user.profile.full_name if holder else (self.label or "unassigned")
```

but note that guards a missing **holder**, not a missing **profile**.

### Recommendation

Fallback order at `views.py:90` and `:133`: **`display_name` → `label` → refuse to render a card.**

Not `user.email`. The verification page is deliberately minimal — `_alumni_verification_context`'s own docstring (`views.py:44-52`) explains that even the *specific tier name* is withheld because it would reveal roughly what was paid. Publishing an e-mail address to any anonymous scanner would be a **new** disclosure introduced by a bug fix, and a worse one than the page currently makes.

Not blank either. A card reading a name-less identity beside a green "Valid" badge asserts that *someone* holds a valid membership without saying who — which is precisely what a verification page must not do. It is worse than an error, because it looks successful.

So when both `display_name` and `label` are empty, the honest response is the existing `scan_invalid.html` path (or a distinct "verification unavailable" state), not a card. That reuses machinery already present at `views.py:181` and `:186`.

**This is the one genuine product decision in this design** — see Q1.

---

## Step 7 — proposed edits, per finding

All proposals. **Nothing applied.**

### Finding 5 — profile-less user breaks slug save

Retired by the signal: `instance.user.profile` at `apps/home/models.py:1091` and `apps/staff/models.py:28` always resolves.

**But the empty-name consequence must be handled in the same pass.** `autoslug/fields.py:267-273`:

```python
        if not slug:
            slug = None
            if not self.blank:
                slug = instance._meta.model_name
            elif not self.null:
                slug = ''
```

The two fields are configured differently, so they diverge:

| Field | Config | Result with blank names |
|---|---|---|
| `AlumniProfile.slug` (`home/models.py:1186-1193`) | `blank=True, null=True` | **`slug = None`** |
| `Employee.slug` (`staff/models.py:329-338`) | neither `blank` nor `null` | `slug = "employee"` — functional |

`AlumniProfile.get_absolute_url()` reverses `home:alumni_detail` with that slug (`models.py:1261`), and the route is `<slug:slug>` — which will not match `None`. **Finding 5's crash therefore moves from `save()` to URL reversal** unless handled.

Options, needing your call (Q2): give the populate function a fallback (e.g. the user's e-mail local part, or the model name, mirroring `Employee`), or make `get_absolute_url()` tolerate a missing slug.

**Test flip:** `MissingUserProfileTests.test_alumni_profile_can_be_created_for_a_profileless_user` currently errors with `RelatedObjectDoesNotExist`; it would assert the profile saves **and** that `get_absolute_url()` resolves. `test_created_superuser_has_no_profile` **inverts** — it currently passes by asserting the absence, and must become "a created superuser HAS a profile", pinning the invariant.

### Finding 4 — anonymous badge scan

Retired by the signal for the *missing-profile* case, but the *empty-name* case remains — hence the fallback above at `views.py:90` and `:133`.

**Test flip:** `VerifyScanMissingProfileTests.test_scan_survives_a_holder_whose_profile_row_is_gone` deletes the `UserProfile` after minting the badge. Under the invariant that row can still be deleted directly, so the test stays meaningful — it would assert a non-5xx response and, per Q1, either a card naming the holder from `label` or the invalid-scan page. A second test should cover the blank-named profile, which is the state the invariant actually produces.

---

## Open questions

**Q1 — the fallback when both `display_name` and `label` are empty.** My recommendation is to serve the existing invalid-scan page rather than an unnamed "Valid" card. The alternative is a card reading something like "Name unavailable", which still asserts validity. I would not use `user.email`.

**Q2 — `AlumniProfile.slug` when names are blank.** Give the populate function a fallback, or make `get_absolute_url()` tolerate `slug=None`? The first keeps every existing caller working; the second is narrower but leaves the `None` slug in the database.

**Q3 — production profile-less count.** Dev has 1 of 5. Worth taking the production number before the cleanup migration, to size it and to know whether any are staff or superusers.

**Q4 — sequencing.** I propose three gated passes: (a) signal plus its tests, (b) badge fallback plus its tests, (c) the backfill data migration last, once (a) has stopped new profile-less accounts appearing. Confirm, or fold (b) into (a).

---

✅ Step 1 — required fields quoted, verdict *proceed* — `apps/user/models.py`
✅ Step 2 — creation paths and read sites enumerated, each marked — `apps/`, `templates/`
✅ Step 3 — `UserManager` and adapter quoted, confirmed no auto-creation — `apps/user/models.py`, `apps/user/adapter.py`
✅ Step 4 — mechanism recommended with field values — signal over manager override
✅ Step 5 — cleanup specified as a separate idempotent migration; dev count reported
✅ Step 6 — fallback recommended against quoted field contents — `apps/qr_manager/models.py`
✅ Step 7 — per-finding edits and test flips described
🛑 Design complete — awaiting confirmation. No code written.
