# `current_for()` fix — apply pass

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Closes:** [`qa_500_report.md`](../qa_500_report.md) findings 2 and 3
**Executes:** [`qa-500-currentfor-design-2026-08-31.md`](qa-500-currentfor-design-2026-08-31.md) — the signed-off design, followed as written

**Commits:** `01630c2` (correctness), `81ee434` (tests)

---

## What changed

### Manager — `apps/home/models.py`

`current_active_for(user)` added, mirroring the hand-rolled query at `apps/qr_manager/views.py:64-66`:

```python
        return (
            self.filter(user=user, status=self.model.Status.ACTIVE)
            .order_by("-created_at")
            .first()
        )
```

`current_for()` **behaviour is unchanged** — only its docstring is sharpened, to say it returns the latest row of *any* status and to point at `current_active_for` for anything stating a member's standing.

### Sites repointed

| # | Site | Change |
|---|---|---|
| 2 | `views.py:683` — QR-badge PDF tier and validity | one line → `current_active_for` |
| 3 | `views.py:839` — membership-update tier pre-selection | one line → `current_active_for` |
| 4 | `services.py:114` — `renew_membership()` | one line → `current_active_for` |

### Site 1 split — `views.py:538` and `templates/home/alumni_detail.html`

`current_membership` now comes from `current_active_for` and drives the standing badge; a new `pending_membership` context variable drives the awaiting-confirmation panel.

### Sites 5 and 6 — unchanged

`admin.py:95` and `:566` keep `current_for`, each with a comment recording that latest-any-status is deliberate: both render the status alongside the tier, and that list is the Secretariat's work queue.

---

## Two things worth flagging

### 1. Site 1's template needed one structural change

The design called for retargeting the awaiting-confirmation panel to `pending_membership`. In practice that panel was the **first arm** of an `{% if %}`/`{% elif %}`/`{% elif %}` chain whose other two arms read `current_membership`:

```
{% if current_membership.status == 'pending' %}      <- awaiting confirmation
{% elif current_membership.is_installment_plan ... %} <- instalment schedule
{% elif current_membership.is_valid ... %}            <- paid in full
```

One arm cannot be pointed at a different variable while the chain survives, so the panel became its own `{% if pending_membership %}` block and the following `{% elif %}` became an `{% if %}`.

This is **inherent to the split rather than extra scope**, and it is what makes the fix actually work: a member can now show an active membership *and* a renewal in flight at the same time, which the old chain structurally prevented — the arms were mutually exclusive by construction. The panel's "Takes priority over both" comment was rewritten, since that reasoning no longer applies.

Verified: `alumni_detail.html` parses, and the held-membership chain below still closes correctly.

### 2. The site-2 PDF assertion needed real decoding

The first attempt searched `resp.content` for the tier name and failed. ReportLab writes content streams through `/ASCII85Decode` then `/FlateDecode`, so the drawn strings are **never present as raw bytes** — a byte search would have passed or failed for reasons unrelated to the bug.

The test now decodes the content streams and asserts on what is actually drawn: `Gold Life Member` and `Lifetime Membership` present, `Student Annual Membership` absent. Two incidental traps found on the way: `"endstream"` contains `"stream"`, so a naive split shifts every boundary; and the badge image must be a genuinely decodable PNG, because ReportLab reads it back through PIL.

---

## Tests

| Test | State |
|---|---|
| `current_active_for` returns the ACTIVE row | new, green |
| `current_for` still returns the newest row of any status | new, green — pins the split so it cannot be collapsed |
| `current_active_for` matches the `qr_manager` query | new, green |
| `current_active_for` is `None` when nothing is active | new, green |
| Finding 3 — `renew_membership` uses the active tier | green, unchanged |
| Site 1 — badge shows held tier, panel shows pending | new, green |
| Site 1 — no panel for a member without a renewal | new, green |
| Site 2 — PDF carries the held tier, not the pending one | new, green |

View-level tests carry an explicit `lvh.me` `HTTP_HOST`; the manager and service tests do not need one.

---

## Suite state

**63 tests, 9 failures.** Down from 11; findings 2 and 3 have dropped off. Nothing regressed.

| Group | Count |
|---|---|
| Pre-existing `apps/qr_manager/tests.py` fixture errors — untouched | 4 |
| Finding 4 — badge scan, missing `UserProfile` | 1 |
| Finding 5 — profile-less user breaks slug save | 1 |
| Finding 6 — `AlumniProfileDetailView` ungated | 1 |
| Finding 8 — `student:` namespace | 2 |

---

## Behaviour changes to be aware of

- A member with **no ACTIVE row** now pre-selects no tier on the renewal form (Q2, accepted in the design — no fallback added).
- Their badge PDF now prints **"No active membership"** rather than an unconfirmed tier. `views.py:684-686` already handled the `None` case.
- `renew_membership()` now raises its documented `ValueError` for a lapsed member instead of renewing off an expired tier. It has no production caller, so this is latent either way.

---

## Scope

`git status` shows exactly the six in-scope files: `apps/home/models.py`, `apps/home/views.py`, `apps/home/services.py`, `apps/home/admin.py`, `apps/home/tests.py`, `templates/home/alumni_detail.html`.

No migration, settings, dependency or real-data change. `apps/qr_manager/tests.py` untouched.

---

## Finding status

| # | Finding | Tier | State |
|---|---|---|---|
| 1 | migrate-from-zero | B | ✅ Closed (`68bb77c`) |
| 2 | `current_for()` ignores status | B | ✅ **Closed** (`01630c2`, `81ee434`) |
| 3 | `renew_membership()` wrong tier | B | ✅ **Closed** (same) |
| 4 | Badge scan 500 on missing profile | B | 🛑 Open — needs a display decision |
| 5 | Profile-less user breaks slug save | B | 🛑 Open — same root cause as #4 |
| 6 | `AlumniProfileDetailView` ungated | B | 🛑 Open — needs an intent decision |
| 7 | Navbar substring host guard | A | ✅ Closed (`c307f84`) |
| 8 | `student:` namespace | A→B | 🛑 Open — fix needs a `main/settings.py` edit |
| — | Staff mis-gating cluster | B | ✅ Closed (`a1771ea`) |

**Next decisions:** findings 4/5 (guarantee the `UserProfile` invariant, or guard each read site — and what a profile-less badge should display), finding 6 (public directory, members-only, or owner-only), finding 8 (may `main/settings.py` be edited).
