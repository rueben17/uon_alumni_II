# Migrate-from-zero fix — Phase 0 (read & report)

**Date:** 2026-08-31
**Branch:** `feature/qa-500-tests`
**Concern:** make `migrate` succeed from an empty database. One concern only — no taxonomy change, no benefits change.

Related: [`qa_500_report.md`](../qa_500_report.md) Finding 1, [`qa-500-phase1-2026-08-31.md`](qa-500-phase1-2026-08-31.md).

---

## Correction to the brief

> "The failing test for this (QA 500 sweep, Finding 1) already exists — your fix must turn it green."

**There is no such test.** `qa_500_report.md` records Finding 1 as *"Test: none. A migration failure cannot be captured by a test that itself needs the database."* A grep across all five `tests.py` files for `migrat|seed_tier|0016|finding 1` returns nothing.

So there is no red test to turn green. The real acceptance signal is different, and better:

- `migrate` on a fresh empty database completes cleanly, **and**
- the whole suite then runs on the **stock settings** — dropping the `--settings=nomig_settings` shim that Phase 1 needed. That shim existing at all is the symptom; its removal is the proof.

I flag this now because it changes what "verify" means, not what the fix is.

---

## 1. What `0016` expects, and by what key

`apps/home/migrations/0016_seed_tier_benefits.py:118-123`:

```python
    tiers_by_name = {t.name: t for t in MembershipTier.objects.filter(name__in=TIER_ORDER)}
    missing = set(TIER_ORDER) - set(tiers_by_name)
    if missing:
        raise RuntimeError(f"Expected MembershipTier rows missing, aborting seed: {missing}")
```

**Lookup key is `name`** — a plain `CharField(max_length=50)`, not unique at this point in the chain.

`TIER_ORDER` (ten names):

```python
TIER_ORDER = [
    "Registered", "Student Annual Membership", "Full Annual Member", "Associate",
    "Bronze Life Member", "Silver Life Member", "Gold Life Member",
    "Diamond Life Membership", "Platinum Life Membership", "Corporate Membership",
]
```

`0016` itself creates exactly two of them (`seed()` lines 106-119):

```python
    MembershipTier.objects.get_or_create(
        name="Associate",
        defaults={
            "fee": 3000, "tier_type": "annual", "duration_months": 12,
            "order": 8, "is_active": True,
        },
    )
    MembershipTier.objects.get_or_create(
        name="Registered",
        defaults={
            "fee": 0, "tier_type": "registered", "duration_months": 12,
            "order": 11, "is_active": True,
        },
    )
```

leaving **eight** that must already exist. On dev and production they were created out-of-band — `0001_initial.py:110` only does `CreateModel` for `MembershipTier`, and no migration in the 41-file chain ever inserts a tier row apart from those two.

---

## 2. The eight tiers, from the dev database

Read-only query against `uon_alumni_II @ localhost`. Dev holds 13 tier rows; these are the eight `0016` requires:

| name | tier_type | fee | duration_months | ladder_rank | `order` in dev (post-0016) | **`order` the seed must insert** |
|---|---|---|---|---|---|---|
| Corporate Membership | `corporate` | 1000000.00 | 12 | 5 | 1 | 1 |
| Platinum Life Membership | `life` | 500000.00 | 0 | — | 2 | 2 |
| Diamond Life Membership | `life` | 250000.00 | 0 | — | 3 | 3 |
| Gold Life Member | `life` | 100000.00 | 0 | 4 | 4 | 4 |
| Silver Life Member | `life` | 50000.00 | 0 | 3 | 5 | 5 |
| Bronze Life Member | `life` | 25000.00 | 0 | 2 | 6 | 6 |
| Full Annual Member | `annual` | 2000.00 | 12 | 1 | 9 | **8** |
| Student Annual Membership | `student` | 500.00 | 12 | — | 10 | **9** |

**The `order` subtlety that must not be got wrong.** `0016`'s first two statements shift two rows to make room:

```python
    MembershipTier.objects.filter(name="Full Annual Member").update(order=9)
    MembershipTier.objects.filter(name="Student Annual Membership").update(order=10)
```

and `unseed()` reverses them to 8 and 9. So dev's 9 and 10 are *post*-shift values. A seed running **before** those two lines must insert 8 and 9, and let `0016` shift them — otherwise a fresh database ends at 10 and 11 and silently diverges from every existing environment.

**All seven fields are settable at this point in the chain.** `name`, `fee`, `tier_type`, `duration_months`, `is_active`, `order` and `ladder_rank` all come from `0001_initial.py:112-119`. `0015` only widens `tier_type`'s choices to admit `registered`. Fields like `code`, `display_order` and `is_life` arrive later in `0031` and are correctly out of reach here — so the eight rows can be reproduced *exactly*, `ladder_rank` included.

---

## 3. Dependency chain around `0016`

```
0015_benefit_alter_membershiptier_tier_type_tierbenefit
        │
        ▼
0016_seed_tier_benefits          ← dependencies = [("home", "0015_...")]
        │
        ▼
0017_redesign_tier_benefits      ← the ONLY migration declaring 0016 as a dependency
        │
        ⋮
0021_retire_physical_id_card
        ⋮
0041_remove_alumniprofile_graduation_year_and_more   (latest)
```

**`0016` is not the only casualty.** Two later data migrations do `MembershipTier.objects.get(name=...)`, which raises `DoesNotExist` rather than the explicit `RuntimeError`:

- `0017_redesign_tier_benefits.py:114` and `:181` — `tier=MembershipTier.objects.get(name=tier_name)`
- `0021_retire_physical_id_card.py:37` and `:51` — same shape, against `Diamond Life Membership` and `Platinum Life Membership`

Every tier name these two reference is inside `TIER_ORDER`, so **seeding the eight satisfies 0016, 0017 and 0021 together.** No further seed points are needed.

**Where a seed step can go.** The constraint that decides the whole design: `0016` has *already applied* on dev and production. Any new node inserted **before** an applied migration makes those databases inconsistent — Django's `MigrationLoader.check_consistent_history()` raises

```
InconsistentMigrationHistory: Migration home.0016_seed_tier_benefits is applied
before its dependency home.00XX_seed_base_tiers on database 'default'.
```

on the next `migrate` (or any management command that loads the graph). This applies equally whether the edge is expressed as a `dependencies` entry on `0016` or a `run_before` on the new migration — both resolve into the same graph edge.

---

## 4. Proposed approach

### (a) New data migration, made a dependency of `0016` — **not recommended**

Create `0015b_seed_base_tiers` depending on `0015`, and add it to `0016.dependencies`.

- Fresh DB: works.
- **Existing DBs: breaks.** `0016` is already applied, the new node is not — `InconsistentMigrationHistory` on the next `migrate`, as above. Recovering needs a manual `migrate home 0015b --fake` on dev *and* production before any subsequent deploy. That is an un-migratable migration: a step someone must remember to run by hand, on every existing environment, or the chain jams.
- Placing it *after* `0041` instead avoids the inconsistency but is useless — `0016` still crashes first on a fresh DB.

The only thing (a) has going for it is that it leaves shipped migration files untouched. That is not worth a mandatory manual fake on production.

### (b) Make `0016` seed-then-benefit idempotently — **recommended**

Extend `0016.seed()` to `get_or_create` all ten `TIER_ORDER` names — the eight above plus the two it already creates — at the **top of the function, before** the two `.update(order=...)` calls, then leave the benefit loop exactly as it is.

- **Fresh DB:** all ten rows are created at their pre-shift `order`, the shift moves Full Annual and Student to 9 and 10, and the benefit matrix seeds against a complete set. `0017` and `0021` then find every tier they look up.
- **Already-migrated DB: a genuine no-op.** `0016` is recorded in `django_migrations`, so it never runs again. Django does not checksum migration bodies, so editing an applied migration's Python changes nothing on those databases — no duplicates, no errors, no history inconsistency, no manual step.
- **`showmigrations` stays linear** — no node added, no edge changed.
- Idempotent regardless: `get_or_create` on `name` is a no-op wherever the row already exists, so even a `--fake`-less replay or a partially-seeded environment converges rather than duplicating.

The usual objection to editing an applied migration is that the file stops describing what actually ran on production. Here that divergence already exists and is the bug: the file assumes state it never created. The edit closes the gap in the correct direction — it makes the migration reproduce what production already holds.

**Keying on `name`.** `0031` later adds `code` with the note *"Stable key for this category ... get_or_create in the reconciliation command keys off this, never off name."* That convention cannot apply here: `code` does not exist until fifteen migrations later. At `0016`-time `name` is the only available key, and `0016` already keys on it for Associate and Registered — so this is consistent with the surrounding code, not a new precedent.

**Recommendation: (b).**

---

## 5. Risks and things to flag

1. **`unseed()` asymmetry — deliberate.** Reverse currently deletes only Associate and Registered. I propose **not** extending it to delete the eight: on every existing environment those rows predate the migration, and a reverse that destroys them would be far worse than an asymmetric one. Worth a comment in the file saying so.
2. **Fresh DBs will hold 10 tiers; dev holds 13.** `Honorary Member` (order 7), `Affiliate` (12) and `Senior Citizen` (13) exist on dev, are created by no migration, and are outside `TIER_ORDER` — so nothing in the chain needs them. Scope says add no tiers, so I propose leaving them out, which leaves a gap at `order=7` on fresh databases. Purely cosmetic (`order` is display sequence), but it means a fresh environment is not a byte-for-byte match for dev. **Flagging, not fixing** — `Honorary` in particular is discussed at length in `0016`'s own docstring and touches the taxonomy question this task explicitly defers.
3. **Fee values are historical, not authoritative.** The eight rows are transcribed from dev exactly as they stand. If any tier's fee has drifted in production away from dev, the seed will bake in dev's value for future fresh databases. Worth a glance at production's tier table before sign-off if that is a live concern.
4. **Not a Neon/production write.** Nothing in this proposal writes to any existing database. On dev and production the edited migration is inert.

---

## Decision needed before I write anything

1. **Approve approach (b)** — edit `0016.seed()` to `get_or_create` all ten tiers at the top of the function.
2. **Confirm the `order` values in §2** — specifically that Full Annual seeds at **8** and Student at **9**, pre-shift.
3. **Confirm the eight-only scope** — leaving `Honorary Member`, `Affiliate` and `Senior Citizen` unseeded, with the `order=7` gap on fresh databases.

Nothing has been written. Stopping here for sign-off.
