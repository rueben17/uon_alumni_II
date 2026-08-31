# `current_for()` status bug — fix design

**Date:** 2026-08-31
**Branch:** `feature/qa-500-tests`
**Findings:** [`qa_500_report.md`](../qa_500_report.md) #2 and #3
**Status:** design only. **No code changed** — the manager, all six call sites, every test, settings and migrations are untouched.

Refines [`qa-500-tierB-plans-2026-08-31.md`](qa-500-tierB-plans-2026-08-31.md), which named the corporate-onboarding trace as an outstanding gap. That gap is walked in §2 below. Where this document and the plans doc disagree, **this one supersedes it** — three sites moved (see §6).

---

## 1. The bug, and the invariant it violates

`apps/home/models.py:1373-1381`:

```python
class MembershipManager(models.Manager):
    def current_for(self, user):
        """Most recent membership row for a user, active or otherwise -- ..."""
        return self.filter(user=user).first()
```

with `Meta.ordering = ["-created_at"]` (`models.py:1500-1501`). No status filter.

**The model's own design intent contradicts this.** `models.py:1408-1413`, on `Status.SUPERSEDED`:

```python
        # A renewal/upgrade activated and replaced this row (1.3 service
        # layer, 2026-08-10) -- distinct from EXPIRED, which means the
        # member let it lapse with nothing replacing it. Lets "current
        # membership" stay a simple status filter instead of every call
        # site having to order-by-latest to find it.
        SUPERSEDED = "superseded", _("Superseded")
```

`SUPERSEDED` exists *precisely so that* "current membership" can be a status filter rather than an order-by-latest. `current_for` is the order-by-latest the status was introduced to make unnecessary.

**The service layer maintains a one-ACTIVE-row invariant.** `apps/home/services.py:37-44`:

```python
    prior_active = (
        Membership.objects.filter(user=membership.user, status=Membership.Status.ACTIVE)
        .exclude(pk=membership.pk)
        .first()
    )
```

and `services.py:47-50` flips it to `SUPERSEDED`. Both `activate_membership` (`:71-76`) and `record_installment_payment` (`:88-93`) call this inside `transaction.atomic()` before activating. So **at most one ACTIVE row per user exists at any time**, and a status filter is deterministic — ordering is belt-and-braces, not load-bearing.

**Confirmed enum members** (`models.py:1403-1413`): `PENDING`, `ACTIVE`, `EXPIRED`, `CANCELLED`, `SUPERSEDED`. The already-correct reference query is `apps/qr_manager/views.py:64-66`:

```python
    membership = Membership.objects.filter(
        user=alumni_profile.user, status=Membership.Status.ACTIVE
    ).order_by("-created_at").first()
```

---

## 2. Corporate onboarding, traced

### There is no corporate-specific membership flow

`corporate` is only a `tier_type` value. `models.py:970-975`:

```python
    def is_corporate(self):
        return self.tier_type == "corporate"
```

It affects display grouping (`views.py:600-603`) and, because the dev fee is KES 1,000,000, payment method — the tier sits above `MembershipTier.MPESA_FEE_CEILING`, so `views.py:846-848` marks it non-M-Pesa. **The membership lifecycle is identical to every other tier.** In practice "corporate onboarding" means the generic flow run with an instalment `payment_frequency`, because of the fee size.

### Where rows are created, and in what status

| Step | Source | Status created |
|---|---|---|
| First-time registration | `views.py:493` — `services.assign_membership_tier(...)` | `PENDING` |
| Renewal / tier change | `views.py:891` — `services.assign_membership_tier(...)` | `PENDING` |
| Secretariat confirms, instalment | `admin.py:721` — `services.record_installment_payment(...)` | activates on **first** instalment; supersedes prior |
| Secretariat confirms, lump sum | `admin.py:730` — `services.activate_membership(...)` | activates; supersedes prior |
| Confirm with no matching row | `admin.py:727-729` — `Membership.objects.create(user=user, tier=tier)` | `PENDING`, then activated immediately |

`assign_membership_tier` (`services.py:96-105`) always leaves the row `PENDING`:

```python
    return Membership.objects.create(user=user, tier=tier, payment_frequency=payment_frequency)
```

### Every point where ACTIVE-plus-newer-PENDING can exist

**One, and it is the main one:** from a renewal/upgrade request at `views.py:891` until the Secretariat confirms it at `admin.py:721` or `:730`.

That window is **not brief**. `admin.py:704-707` says so directly:

> `payment_date` defaults to when the member submitted the payment request, which can sit pending **for days/weeks** before the Secretariat gets to it

For an instalment plan — i.e. the corporate case — the pair persists until the **first** instalment is confirmed (`services.py:89-92`); later instalments only accumulate `amount_paid`.

Reaching that window requires an already-established member. `views.py:823-826` gates the renewal view on it:

```python
            has_paid_membership = Membership.objects.filter(user=request.user).exclude(
                status=Membership.Status.PENDING
            ).exists()
```

So the affected population is exactly the paid-up membership at renewal or upgrade — including every corporate member renewing.

**A second, transient point:** `admin.py:727-729` creates a `PENDING` row then activates it in the next statement, inside the service layer's `transaction.atomic()`. Not externally observable.

**Bounded to one pending row.** `views.py:877` blocks a second:

```python
        if Membership.objects.filter(user=request.user, status=Membership.Status.PENDING).exists():
```

with a comment that names this very bug — *"with current_for() only ever showing the newer one and the older one silently forgotten"*. So the realistic data shape is **at most one ACTIVE plus at most one PENDING**.

**No schema or migration change is needed.** The statuses and the invariant already exist; only the read path is wrong.

---

## 3. Per-site mapping

| # | Site | What it does with the row | Desired semantic | Justification (quoted) |
|---|---|---|---|---|
| 1 | `views.py:538` — profile badge | Standing badge **and** an awaiting-confirmation panel | **Both** — split into two context vars | `alumni_detail.html:35` renders `{{ current_membership.tier.name }}` as the standing badge, but `:175` branches `{% if current_membership.status == 'pending' %}` to render "Awaiting Confirmation" with `balance_due` and request date. The template needs the ACTIVE row *and* the PENDING row. |
| 2 | `views.py:683` — QR-badge PDF | `tier_name`, `validity_period` printed onto a PDF | **Active-only** | `views.py:687` `tier_name = current_membership.tier.name`, printed to a physical artefact. `views.py:684-686` already handles `None` as `"No active membership"`. **Settled.** |
| 3 | `views.py:839` — membership-update | Pre-selects the tier; renders a standing panel | **Active-only** | `views.py:845` `current_membership.tier_id` pre-selects the form; `alumni_membership_update.html:29` shows `is_valid`. The pending case is already served separately by `pending_payment` (`views.py:848-850`). |
| 4 | `services.py:114` — `renew_membership()` | Reads `current.tier` to renew at | **Active-only** | `services.py:117` `assign_membership_tier(user, current.tier, ...)`. Renewing off a PENDING/CANCELLED tier is a financial error. **Settled.** |
| 5 | `admin.py:92` — export column | `f"{tier.name} ({get_status_display()})"` | **Latest-any-status — no change** | It renders the status *explicitly*. Showing "Gold Life Member (Pending)" is the point: the Secretariat needs in-flight requests visible in an export. Active-only would hide them. |
| 6 | `admin.py:560` — admin display column | `f"{tier.name} ({get_status_display()})"` | **Latest-any-status — no change** | Identical shape to #5, `admin.py:563`. This is the list the Secretariat works from; hiding pending rows there would remove the queue they act on. |

### Reachability note on site 4

`renew_membership()` has **no production caller**. A grep across `apps/` for the service-layer functions returns callers for `assign_membership_tier`, `activate_membership` and `record_installment_payment`, but none for `renew_membership` or `upgrade_to_lifetime` outside `services.py` itself and docstrings. Site 4's bug is therefore latent — reachable today only from the finding-3 reproduction test. That lowers its urgency but not its correctness: it is a loaded gun for the first caller.

---

## 4. Proposed manager API

Least-surprising option, and the one the brief prefers: **keep `current_for`'s contract exactly as it is, and add a status-aware sibling.**

```python
class MembershipManager(models.Manager):
    def current_for(self, user):
        """Most recent membership row for a user, active or otherwise -- ..."""
        return self.filter(user=user).first()

    def current_active_for(self, user):
        """The membership the user actually holds right now.

        The service layer supersedes any prior ACTIVE row before
        activating a new one (apps/home/services.py:37-50), so at most
        one ACTIVE row exists per user; the ordering is a tie-breaker,
        not a semantic. Returns None when the user holds nothing active
        -- a pending first request, or a lapsed membership.
        """
        return (
            self.filter(user=user, status=self.model.Status.ACTIVE)
            .order_by("-created_at")
            .first()
        )
```

**Why add rather than change:** sites 5 and 6 genuinely want the existing contract, so redefining `current_for` would silently change two admin surfaces to serve a different purpose. Adding a sibling means every changed site is an explicit, reviewable edit, and the two unchanged sites need no edit at all.

**Why not rename `current_for` to `latest_for`:** it is defensible and slightly clearer, but it turns a 3-site change into a 6-site change for no behavioural gain. Worth doing later as tidying, not as part of a correctness fix. **Flagging as an option if you would rather do it once.**

### Behaviour with no ACTIVE row

`current_active_for` returns `None`. Per site:

- **Site 2** — already handled: `views.py:684-686` sets `"No active membership"` / `"—"`. A pending-only member now correctly prints "No active membership" instead of their unconfirmed tier. **An improvement.**
- **Site 3** — `tier_id` becomes `None`, so the form pre-selects nothing. **This is a small regression** for a lapsed member (rows all `EXPIRED`/`SUPERSEDED`) who today gets their last tier pre-selected. See open question Q2.
- **Site 4** — raises the documented `ValueError` (`services.py:116`). A lapsed member can no longer renew off an expired tier and must use `assign_membership_tier`. Arguably correct; no caller exists today either way.

---

## 5. Proposed per-site edits

Proposals, **not applied**.

**Site 2** — `apps/home/views.py:683`
```python
-    current_membership = Membership.objects.current_for(alumni.user)
+    current_membership = Membership.objects.current_active_for(alumni.user)
```

**Site 3** — `apps/home/views.py:839`
```python
-        current_membership = Membership.objects.current_for(request.user)
+        current_membership = Membership.objects.current_active_for(request.user)
```

**Site 4** — `apps/home/services.py:114`
```python
-    current = Membership.objects.current_for(user)
+    current = Membership.objects.current_active_for(user)
```

**Site 1** — `apps/home/views.py:538`, **not a one-line swap.** The template needs both rows:
```python
-        current_membership = Membership.objects.current_for(self.object.user)
-        context["current_membership"] = current_membership
+        current_membership = Membership.objects.current_active_for(self.object.user)
+        context["current_membership"] = current_membership
+        context["pending_membership"] = Membership.objects.filter(
+            user=self.object.user, status=Membership.Status.PENDING
+        ).order_by("-created_at").first()
```
plus retargeting `templates/home/alumni_detail.html:175-203` from `current_membership` to `pending_membership`, and making the `{% if current_membership %}` badge at `:34` tolerate `None`. **This is the only site needing a template change**, and the only one I would not treat as mechanical.

**Sites 5 and 6** — `apps/home/admin.py:92` and `:560`: **no change.** Worth a one-line comment at each recording that latest-any-status is deliberate, so a future reader does not "fix" them.

---

## 6. Changes from the plans doc

| Site | Plans doc said | This design says | Why |
|---|---|---|---|
| 1 | `active_for`, flagged as a choice | **Both vars + template change** | `alumni_detail.html:175` already branches on `status == 'pending'`; active-only would dead-code the awaiting-confirmation panel |
| 3 | `latest_for` "likely" | **Active-only** | `pending_payment` (`views.py:848`) already serves the pending case separately; `:845` pre-selects a tier, which should be the held one |
| 5, 6 | "Choice" | **Confirmed no change** | Both render `get_status_display()` explicitly — showing a non-ACTIVE status is the feature |

The plans doc also proposed retiring `current_for` in favour of `active_for`/`latest_for`. Superseded: sites 5 and 6 want the existing contract, so keeping `current_for` and adding one sibling is the smaller, safer change.

---

## 7. Tests that would flip

**Finding 2** — `apps.home.tests.CurrentForStatusTests.test_current_for_prefers_the_active_membership`. Currently asserts `current_for()` returns the ACTIVE row; it returns the newer PENDING one.

Under this design `current_for` **keeps** its behaviour, so the test must be *retargeted*, not just flipped: assert `current_active_for(user)` returns the ACTIVE row, and add a companion asserting `current_for(user)` still returns the newest row of any status — pinning the deliberate two-method split. The existing passing pin `test_qr_manager_status_filtered_lookup_stays_correct` should additionally assert `current_active_for` returns the same row as the hand-rolled query at `qr_manager/views.py:64-66`.

**Finding 3** — `apps.home.tests.RenewMembershipTierTests.test_renewal_uses_the_active_tier`. Asserts `renew_membership(user).tier == gold` where a newer PENDING Student row exists. Goes green with the site-4 edit, unchanged as written.

**New coverage worth adding in the fix pass:** site 2 (the PDF prints the ACTIVE tier, not the pending one) and site 1 (the badge shows ACTIVE while the awaiting-confirmation panel shows the PENDING row) — neither is covered today.

---

## 8. Open questions

**Q1 — Site 1's template change.** Do you want the two-variable split, or should the profile page keep showing the pending row as the headline badge? The split is more correct but touches `alumni_detail.html`.

**Q2 — Site 3 and lapsed members.** Under active-only, a member whose rows are all `EXPIRED`/`SUPERSEDED` gets no tier pre-selected. Accept the small regression, or add an explicit `active-else-most-recent-non-pending` fallback for the pre-selection only?

**Q3 — Naming.** Keep `current_for` + add `current_active_for` (proposed), or rename to `latest_for`/`active_for` and touch all six sites once?

**Q4 — Sites 5 and 6.** Confirm that latest-any-status is right for the Secretariat's admin list and export — my reading is that it is, because both render the status.

---

✅ Read — plans doc, `models.py` manager and `Status`, all six call sites, `services.py` in full, `admin.py:700-735`, `alumni_detail.html`, `alumni_membership_update.html`
✅ Traced — corporate/instalment onboarding, every ACTIVE-plus-newer-row point
🛑 Design complete — awaiting confirmation. No code written.
