# Finding 6 — alumni profile page gate — apply pass

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Closes:** [`qa_500_report.md`](../qa_500_report.md) finding 6

**Commits:** `2d452ed` (correctness), `663bb73` (tests)

---

## What changed

| File | Change |
|---|---|
| `apps/home/views.py` | `AlumniProfileDetailView` gains `LoginRequiredMixin`; `get_context_data` computes an `is_owner_or_admin` flag and scopes `alt_email` to it |
| `templates/home/alumni_detail.html` | Alt. Email cell conditionalised; the payment-history guard widened from owner-only to owner-or-admin |
| `apps/home/tests.py` | Finding 6 reproduction flipped, plus the owner / non-owner / admin / sparse-profile matrix |

### The gate

```python
class AlumniProfileDetailView(LoginRequiredMixin, DetailView):
```

Anonymous now gets a 302 to login. Its three sibling views (`views.py:780`, `:803`, `:905`) all already carried `LoginRequiredMixin`, and staff's `EmployeeDetailView` carries an employee gate — this view was the outlier.

### The viewer flag

```python
        viewer = self.request.user
        is_owner_or_admin = viewer.is_authenticated and (
            viewer == self.object.user or viewer.is_staff or viewer.is_superuser
        )
```

The gate alone is not enough. Sessions span every subdomain via `SESSION_COOKIE_DOMAIN`, so **any** authenticated account — staff or student included — reaches this apex view. That is why the sensitive fields are scoped to owner-or-admin rather than to "anyone logged in".

- **`alt_email`** — kept out of the **context entirely** for anyone else, not merely hidden in the template, and its cell in the contact grid is conditionalised.
- **Payment history** — the panel guard widened from owner-only to owner-or-admin, so the Secretariat can handle a membership query against this page.

---

## Three things that differed from the brief's premise

### 1. Payment history was already owner-gated — it never leaked

The brief expected payment history to be exposed to non-owners. It was not. The template guard at `:171` (closing at `:305`) already wrapped it:

```
{% if request.user.is_authenticated and request.user == alumni.user %}
```

and `payments` comes from `{% with payments=alumni.payments.all %}` at `:268`, **inside** that block — so it was never in the view context and never reached a non-owner.

What it *was* missing is **admin** visibility. That one guard is now `is_owner_or_admin`, as specified.

### 2. `alt_email` was the actual leak

`alumni_detail.html:51` rendered `{{ alt_email.email|default:"-" }}` in the contact grid, ungated, to anyone who could see the page. That is the disclosure finding 6 recorded, and it is now closed at both the context and template layers.

### 3. Only one of the four owner guards was widened

There are four in this template:

| Line | Wraps | Decision |
|---|---|---|
| `:106` | Edit Profile / Manage Membership / Deactivate Profile | **Owner-only — unchanged** |
| `:139` | QR badge Download PDF / PNG | **Owner-only — unchanged** |
| `:150` | Apply for / Update Alumni Digital ID | **Owner-only — unchanged** |
| `:171` | Payment history and membership panels | **Widened to owner-or-admin** |

A blanket replacement would have handed an admin someone else's "Deactivate Profile" button — a worse bug than the one being fixed.

### And a framing correction

**Finding 6 was a disclosure, not a 500.** The brief describes the view as 500ing on absent related rows; `qa_500_report.md` records it as returning 200 to anonymous visitors. The context reads were already null-safe — `.first()` returns `None`, the tier block is guarded by `if current_membership:`, and `user.profile` misses are silenced in templates because `ObjectDoesNotExist` sets `silent_variable_failure = True`. Nothing was changed for this; a sparse-profile test now pins it.

---

## Tests

| Test | Asserts |
|---|---|
| Anonymous is redirected to login | 302, `Location` contains `/accounts/` |
| Authenticated non-owner sees directory fields | 200, `is_owner_or_admin` False, primary e-mail present |
| Authenticated non-owner gets no sensitive fields | `alt_email` is `None`; no alt address, no "Alt. Email", no payment-history heading |
| Owner sees the sensitive fields | 200, flag True, alt address and payment-history heading present |
| Admin sees the sensitive fields | 200, flag True, both present |
| Sparse profile renders for an authenticated viewer | 200, `current_membership` and `pending_membership` both `None` |

All carry `HTTP_HOST='lvh.me'` — the view is on the apex.

**One assertion needed tightening.** `assertNotContains(resp, "Payment History")` failed for a legitimate reason: `alumni_detail.html:317-329` is an **HTML** comment (`<!-- ... -->`, not `{% comment %}`) that mentions the phrase, and HTML comments render into the body. The assertion now targets `">Payment History</h2>"` — the heading markup — so it cannot pass or fail for the wrong reason.

---

## Inbound links — enumerated, not changed

| Site | Reachable anonymously? |
|---|---|
| `templates/home/alumni_membership_update.html:85` | No — owner-only page |
| `templates/home/alumni_profile_delete_confirm.html:39` | No — owner-only page |
| `templates/home/standing_page.html:88` | No — the digital-ID slug/pk variant already implies a logged-in alumnus |
| `apps/home/context_processors.py:296` | No — the navbar "my profile" link, logged-in alumnus only |
| `apps/home/views.py:846` | No — a post-dispatch redirect on an authenticated flow |

**No public listing page links to an alumni profile.** Executive-committee and in-memoriam, named in the brief as candidates, do not.

**The sitemap is unaffected.** `apps/home/sitemaps.py:50` records that `alumni_detail` was *already* deliberately excluded — *"a member's name/tier/county shouldn't be permanently searchable (decided with the user, 2026-08-18)"* — so gating it breaks no crawl path and is consistent with a decision already taken.

**Net UX change: none identified.** Every inbound link is already behind authentication.

---

## Suite state

**71 tests, 6 errors.** Finding 6 is off the list. Nothing else moved.

| Group | Count |
|---|---|
| Pre-existing `apps/qr_manager/tests.py` fixture errors — untouched | 4 |
| Finding 4 — badge scan, missing `UserProfile` | 1 |
| Finding 5 — profile-less user breaks slug save | 1 |

`git status` showed only the three in-scope files.

---

## Finding status — seven of nine closed

| # | Finding | Tier | State |
|---|---|---|---|
| 1 | migrate-from-zero | B | ✅ Closed (`68bb77c`) |
| 2 | `current_for()` ignores status | B | ✅ Closed (`01630c2`, `81ee434`) |
| 3 | `renew_membership()` wrong tier | B | ✅ Closed (same) |
| 4 | Badge scan 500 on missing profile | B | 🛑 **Open** |
| 5 | Profile-less user breaks slug save | B | 🛑 **Open** |
| 6 | `AlumniProfileDetailView` ungated | B | ✅ **Closed** (`2d452ed`, `663bb73`) |
| 7 | Navbar substring host guard | A | ✅ Closed (`c307f84`) |
| 8 | `student:` namespace | A→B | ✅ Closed (`bab912d`) |
| — | Staff mis-gating cluster | B | ✅ Closed (`a1771ea`) |

---

## What remains

**Findings 4 and 5 only**, and they share one root cause: nothing guarantees a `User` has a `UserProfile`. It is created in just two places — `apps/user/adapter.py:111` (social login) and the legacy-import command — while `UserManager.create_user`/`create_superuser` do not.

Two decisions are needed:

1. **Guarantee the invariant** (create the profile in `UserManager` or a `post_save` signal) **or guard each read site**. The invariant retires both findings together and lets the scattered `hasattr(user, 'profile')` guards go; it also wants a backfill for existing profile-less rows, which is a separate approved data migration.
2. **What should a profile-less badge display?** `apps/qr_manager/views.py:90` and `:133` read `user.profile.display_name` in Python, so the scan 500s for an anonymous visitor. Falling back to blank would render an anonymous card; `user.email` or the QR's own `label` are the plausible alternatives.
