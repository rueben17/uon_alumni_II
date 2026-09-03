# QA 500 fixes — Tier B plans (awaiting confirmation)

**Date:** 2026-08-31
**Branch:** `feature/qa-500-tests`
**Status:** nothing below has been edited. Plans only.

Source of truth: [`qa_500_report.md`](../qa_500_report.md).
Applied this pass: [finding 7](#) (`c307f84`) and [target 1](#) (`a1771ea`) — see the summary at the end.

---

## 🛑 Findings 2 & 3 — `current_for()` ignores status

**Tier B, and the most sensitive item here.** One manager change, six call sites, and the correct semantic genuinely differs per site. Failing tests: `CurrentForStatusTests.test_current_for_prefers_the_active_membership`, `RenewMembershipTierTests.test_renewal_uses_the_active_tier`.

Root cause, `apps/home/models.py:1373-1381`:

```python
class MembershipManager(models.Manager):
    def current_for(self, user):
        return self.filter(user=user).first()
```

with `Meta.ordering = ["-created_at"]` (`models.py:1500-1501`). No status filter.

### Proposed shape

Split the one overloaded method into two explicitly-named ones, rather than changing what `current_for` returns and hoping every caller wanted that:

```python
def active_for(self, user):
    """The membership this person currently holds."""
    return self.filter(user=user, status=self.model.Status.ACTIVE).order_by("-created_at").first()

def latest_for(self, user):
    """The most recent row of ANY status -- 'is there a request in flight'."""
    return self.filter(user=user).order_by("-created_at").first()
```

`active_for` deliberately mirrors the already-correct query at `apps/qr_manager/views.py:64-66`, which is pinned by a passing test.

Then retire `current_for` entirely, so no call site keeps the ambiguous name by accident.

### Per-call-site mapping — this is what needs your ruling

| # | Site | What it feeds | Proposed | Confidence |
|---|---|---|---|---|
| 1 | `views.py:538` | Profile page standing badge | `active_for` | **Choice.** A member mid-renewal arguably wants to see "renewal pending" too. Cleanest is `active_for` for the badge *plus* a separate `latest_for` for a "renewal in progress" notice — but that is new UI, so out of scope unless you want it. |
| 2 | `views.py:683` | **Tier and validity printed onto the QR badge PDF** | `active_for` | **Certain.** A physical artefact must not carry a pending tier. |
| 3 | `views.py:839` | Membership-update / upgrade flow | `latest_for` | **Likely** — this flow is *about* the in-flight request, and `views.py:865-872` already reasons about a pending row existing. Wants your confirmation. |
| 4 | `services.py:114` | `renew_membership()` reads `current.tier` | `active_for` | **Certain.** Today a Gold Life Member (KES 100,000) renews as Student Annual (KES 500). |
| 5 | `admin.py:92` | Export column | **Choice.** | Reporting. Latest-any-status may be what the Secretariat wants for an export; active-only is what "current membership" reads as. |
| 6 | `admin.py:560` | Admin list display column | **Choice.** | Same as above. Arguably should show both, e.g. `"Gold Life Member (Active) — renewal pending"`. |

Sites 2 and 4 are unambiguous. Sites 1, 5 and 6 are product decisions about what "current" should mean on a screen, and site 3 hinges on the upgrade flow's intent.

### Corporate onboarding

Flagged in the brief as the risk area. Corporate is a `MembershipTier` like any other, so nothing in this change is corporate-specific — but any onboarding path that creates a PENDING row and then reads back "the current membership" before confirmation will change behaviour under `active_for` (it will read `None` where it previously read the pending row). I have not traced the corporate onboarding path; **it should be walked before this lands**, and it is a good reason to give this finding its own pass rather than bundling it here.

**Recommendation: give this its own prompt**, as you suggested. It is a behaviour change across six sites on a payment-adjacent path, and it deserves the same read-quote-confirm discipline the rest of this audit got.

---

## 🛑 Findings 4 & 5 — no `UserProfile` invariant

One root cause, two symptoms. Failing tests: `VerifyScanMissingProfileTests.test_scan_survives_a_holder_whose_profile_row_is_gone`, `MissingUserProfileTests.test_alumni_profile_can_be_created_for_a_profileless_user`.

`UserProfile` is created in exactly two places — `apps/user/adapter.py:111` (social login) and the legacy-import command. `UserManager.create_user`/`create_superuser` (`apps/user/models.py:25-47`) do not, so any account from `createsuperuser` or the admin lacks one.

- **Finding 4** — `apps/qr_manager/views.py:90` and `:133` read `…user.profile.display_name` in Python, so `RelatedObjectDoesNotExist` becomes a **public, anonymous 500** on a badge scan.
- **Finding 5** — `apps/home/models.py:1091` and `apps/staff/models.py:28` read `instance.user.profile` inside an `AutoSlugField` `populate_from`, so the read happens in `save()` and 500s the admin's add form.

### Two options

**(a) Guarantee the invariant — recommended.** Create the `UserProfile` in `UserManager.create_user`, or via a `post_save` signal on `User`. "Every User has a profile" becomes true rather than merely usual. This retires findings 4 and 5 together and lets the scattered `hasattr(user, 'profile')` guards (`home/admin.py:80`, `:552`, `qr_manager/admin.py:423`, `staff/admin.py:140`) eventually go.

- Needs a decision on what a placeholder profile contains — `given_name`/`family_name` blank? That affects `display_name`, which is what the badge page renders.
- Existing profile-less rows in dev/production are **not** fixed by this; it would want a one-off backfill, which is a data migration and therefore a separate, explicitly-approved step.

**(b) Guard each read site.** Narrower and touches no invariant, but leaves eight unguarded reads and only defends the ones we happen to have found. Also still needs a decision on what the badge shows for a profile-less holder — `user.email`? the QR's `label`? Falling back to blank would render an anonymous card, which is arguably worse than a 500.

**Recommendation: (a), with the backfill as a separate approved step.** Either way, the "what does a profile-less badge display" question needs answering before I write code.

---

## 🛑 Finding 6 — `AlumniProfileDetailView` is ungated

Failing test: `AlumniProfileDetailAccessTests.test_anonymous_visitor_cannot_read_a_members_profile` (currently returns 200 to an anonymous visitor).

`apps/home/views.py:515` is a bare `DetailView` while its three siblings (`:780`, `:803`, `:905`) all carry `LoginRequiredMixin`. `get_context_data` (`:537-540`) attaches `current_membership` and the member's **non-primary e-mail address**, and the template carries payment history.

**This needs an intent decision before any code.** The docstring at `views.py:517` says *"Public alumni profile page — mirrors staff's EmployeeDetailView"*, but `EmployeeDetailView` carries `EmployeeRequiredMixin`, so the mirror is already broken.

| Option | Change | Consequence |
|---|---|---|
| **Public directory** | Strip `alt_email` and payment history from context and template; keep the page open | Alumni remain findable; the sensitive fields stop leaking |
| **Members-only** | Add `LoginRequiredMixin`, plus owner-or-employee check | Genuinely mirrors `EmployeeDetailView`; breaks any public link to a profile |
| **Owner-only** | Owner or admin only | Most conservative; makes the page useless as a directory |

I have not checked whether anything links to these URLs publicly — worth knowing before choosing. **Which of the three?**

---

## 🛑 Finding 8 — `student:` namespace — *downgraded, and blocked by scope*

Failing tests: `StudentNamespaceReverseTests.test_student_namespace_reverses_under_its_own_urlconf`, `SubdomainUrlTagStudentTests.test_tag_builds_a_students_subdomain_link`.

The report tagged this **Tier A**. Reading the call sites, it should not be auto-fixed, for three reasons:

**1. It is latent, not live.** Every real call site already works around it, deliberately and with comments:
- `apps/home/views.py:1109` — `reverse("register", urlconf="apps.student.urls")` (bare name) plus `_students_subdomain_url`
- `apps/home/context_processors.py:265-272` — hardcoded paths, noting a `student:` reverse *"crashed this context processor — which runs on every page — for every staff/superuser request site-wide"* (2026-08-19)

No production code path currently raises. The failing tests assert a capability nothing yet uses.

**2. The obvious in-app fix would create two new 500s.** Registering the namespace by wrapping the patterns in `include((patterns, 'student'), namespace='student')` inside `apps/student/urls.py` would break the two templates that use the **bare** names:
- `templates/student/applicant_dashboard.html:22` — `{% url 'analytics_export' %}`
- `templates/student/evaluate_application.html:48` — `{% url 'evaluate_application' pk=applicant.pk %}`

**3. The report's own proposed fix is out of this brief's scope.** Adding `apps/student/site_urls.py` and repointing `SUBDOMAIN_URLCONFS['students']` requires editing `main/settings.py`, which Scope forbids.

### Proposed

Mirror the staff arrangement properly — new `apps/student/site_urls.py` doing `path('', include('apps.student.urls'))`, repoint `SUBDOMAIN_URLCONFS['students']` at it, then convert the two bare-name templates to `student:`-prefixed. That registers the namespace, keeps every URL path identical, and lets the three existing workarounds be simplified later.

**Needs:** your approval to edit `main/settings.py`. Without that, the honest alternative is to leave finding 8 open and mark its two tests as expected failures documenting a known gap.

---

## Summary

| # | Finding | Tier | State |
|---|---|---|---|
| 1 | migrate-from-zero | B | ✅ Closed earlier (`68bb77c`) |
| 2 | `current_for()` ignores status | B | 🛑 Plan above — recommend its own prompt |
| 3 | `renew_membership()` wrong tier | B | 🛑 Same fix as #2 |
| 4 | Badge scan 500 on missing profile | B | 🛑 Plan above — needs display decision |
| 5 | Profile-less user breaks slug save | B | 🛑 Same root cause as #4 |
| 6 | `AlumniProfileDetailView` ungated | B | 🛑 Plan above — needs intent decision |
| 7 | Navbar substring host guard | A | ✅ Fixed, test green (`c307f84`) |
| 8 | `student:` namespace | A→B | 🛑 Latent; fix needs a settings edit |
| — | Staff mis-gating cluster | B | ✅ Fixed, tests green (`a1771ea`) |

**Suite:** 58 tests, 3 failures + 8 errors. Of those 11: seven are the Tier B findings above, four are the pre-existing `apps/qr_manager/tests.py` fixture errors left untouched as instructed.

### Decisions needed

1. **Finding 2/3** — confirm the per-call-site mapping, especially sites 1, 3, 5 and 6. Recommend a dedicated prompt.
2. **Findings 4/5** — option (a) invariant or (b) per-site guards, and what a profile-less badge should display.
3. **Finding 6** — public directory, members-only, or owner-only?
4. **Finding 8** — may I edit `main/settings.py`? If not, it stays open.
