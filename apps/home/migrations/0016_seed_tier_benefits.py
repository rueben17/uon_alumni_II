"""
Data migration seeding Benefit/TierBenefit from the tier-benefits matrix
(2026-08-10 UX/UI spec appendix).

Two new MembershipTier rows are added here too (Registered/free and
Associate/3000, Association decision 2026-08-10 -- see docs/todo.md 1.6):
neither existed in the previously-seeded 9-tier lineup, and the appendix's
own cell values are written against this exact 10-tier set. Existing
Full Annual/Student `order` values shift by one to make room; no other
existing MembershipTier row is touched.

Honorary Member is deliberately NOT seeded with TierBenefit rows -- the
appendix doesn't cover it (its own tier list has no "Honorary" entry;
"Associate" is a new, distinct tier at the same 3,000 price point, not a
rename of it -- Honorary is conferred, Associate is purchased). Association
still needs to specify Honorary's benefits separately; inventing values
for it here would be fabricating data nobody supplied.
"""
from django.db import migrations


# (name, axis, [10 cell values, tier order: Registered, Student, Full
# Annual, Associate, Bronze, Silver, Gold, Diamond, Platinum, Corporate])
BENEFIT_ROWS = [
    ("Newsletter, directory listing, social groups, public events", "access",
     ["✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓"]),
    ("Digital alumni ID (QR)", "access",
     ["—", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "n/a"]),
    ("Physical ID card", "access",
     ["—", "—", "annual", "annual", "permanent", "✓", "✓", "✓", "✓", "n/a"]),
    ("Library — reading access", "access",
     ["—", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "staff seats"]),
    ("Library — borrowing + e-resources", "access",
     ["—", "—", "—", "—", "✓", "✓", "✓", "✓", "✓", "staff seats"]),
    ("Career services / job board", "economic",
     ["—", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "—"]),
    ("Vote at AGM & Association elections", "voice",
     ["—", "—", "✓", "—", "✓", "✓", "✓", "✓", "✓", "1 delegate"]),
    ("Stand for elective office", "voice",
     ["—", "—", "—", "—", "✓", "✓", "✓", "✓", "✓", "—"]),
    ("Parking sticker", "access",
     ["—", "—", "—", "—", "—", "1 vehicle", "2 vehicles", "reserved bay", "reserved bay", "3 visitor passes"]),
    ("Sports & recreation facilities", "access",
     ["—", "—", "—", "—", "—", "✓", "✓", "✓", "✓", "—"]),
    ("Consultancy / research / training panel", "economic",
     ["—", "—", "—", "—", "—", "eligible", "eligible", "priority", "priority", "partner track"]),
    ("UONAA working space", "access",
     ["—", "—", "—", "—", "discounted", "discounted", "4 days/mo", "8 days/mo", "unlimited", "meeting room quota"]),
    ("Paid Association events", "access",
     ["pay", "student rate", "pay", "pay", "10% off", "25% off", "50% off", "complimentary", "complimentary +1", "table of 8"]),
    ("Mentor programme — priority matching", "economic",
     ["—", "mentee", "mentor", "mentor", "mentor", "✓", "✓", "✓", "✓", "staff cohort"]),
    ("Alumni Awards nomination rights", "voice",
     ["—", "—", "—", "—", "—", "—", "✓", "✓", "✓", "—"]),
    ("Publication / speaking slots in Association channels", "voice",
     ["—", "—", "—", "—", "—", "—", "✓", "✓", "✓", "thought-leadership"]),
    ("Spouse / dependant membership", "access",
     ["—", "—", "—", "—", "—", "—", "spouse", "spouse + 2", "spouse + 3", "n/a"]),
    ("Advisory forum / committee co-option", "voice",
     ["—", "—", "—", "—", "—", "—", "—", "✓", "✓", "board observer"]),
    ("Named bursary in member's name", "legacy",
     ["—", "—", "—", "—", "—", "—", "—", "1 student", "3 students", "co-branded fund"]),
    ("Alumni Centre — donor wall", "legacy",
     ["—", "—", "—", "—", "—", "—", "✓", "✓", "✓", "✓"]),
    ("Alumni Centre — naming rights", "legacy",
     ["—", "—", "—", "—", "—", "—", "—", "—", "room/feature", "facility"]),
    ("Alumni Centre shareholding pre-emption", "legacy",
     ["—", "—", "—", "—", "—", "—", "—", "✓", "✓", "✓"]),
    ("Standing invitation to VC / Chancellor functions", "voice",
     ["—", "—", "—", "—", "—", "—", "—", "—", "✓", "2 seats"]),
    ("Graduate talent pipeline / campus recruitment", "economic",
     ["—", "—", "—", "—", "—", "—", "—", "—", "—", "✓"]),
    ("Branding at Association events & platforms", "economic",
     ["—", "—", "—", "—", "—", "—", "—", "—", "—", "✓"]),
]

# Index-aligned with each BENEFIT_ROWS cell list.
TIER_ORDER = [
    "Registered", "Student Annual Membership", "Full Annual Member", "Associate",
    "Bronze Life Member", "Silver Life Member", "Gold Life Member",
    "Diamond Life Membership", "Platinum Life Membership", "Corporate Membership",
]


def _parse_cell(raw):
    if raw == "✓":
        return "included", ""
    if raw == "—":
        return "excluded", ""
    if raw == "n/a":
        return "not_applicable", ""
    return "included", raw


def seed(apps, schema_editor):
    MembershipTier = apps.get_model("home", "MembershipTier")
    Benefit = apps.get_model("home", "Benefit")
    TierBenefit = apps.get_model("home", "TierBenefit")

    # The eight tiers below were created out-of-band on dev and production
    # and by no migration at all -- 0001_initial only does CreateModel for
    # MembershipTier. A fresh database therefore reached the validation at
    # the foot of this function with every one of them missing, and 0017
    # (:114, :181) and 0021 (:37, :51) went on to fail their own
    # MembershipTier.objects.get(name=...) lookups. Seeded here so the
    # chain builds from empty (2026-08-31).
    #
    # Keyed on `name`: `code`, the stable key used from 0031 onwards, does
    # not exist yet at this point in the chain, and this migration already
    # keys Associate/Registered below the same way. get_or_create makes the
    # whole block inert wherever the rows already exist -- which is every
    # environment this migration has already run on.
    #
    # Full Annual and Student are inserted at their POST-shift order (9 and
    # 10), not the 8 and 9 they historically held, so this block is correct
    # wherever it sits relative to the two .update(order=...) calls below.
    # Those calls are deliberately left alone: they still perform the real
    # shift on any database that reaches this migration with those rows
    # already present at 8/9, and are simply a no-op on a fresh one.
    #
    # order=7 is left empty on purpose -- that is dev's Honorary Member,
    # which sits outside TIER_ORDER and is not this migration's concern.
    for _name, _tier_type, _fee, _months, _order, _ladder in [
        ("Corporate Membership", "corporate", 1000000, 12, 1, 5),
        ("Platinum Life Membership", "life", 500000, 0, 2, None),
        ("Diamond Life Membership", "life", 250000, 0, 3, None),
        ("Gold Life Member", "life", 100000, 0, 4, 4),
        ("Silver Life Member", "life", 50000, 0, 5, 3),
        ("Bronze Life Member", "life", 25000, 0, 6, 2),
        ("Full Annual Member", "annual", 2000, 12, 9, 1),
        ("Student Annual Membership", "student", 500, 12, 10, None),
    ]:
        MembershipTier.objects.get_or_create(
            name=_name,
            defaults={
                "tier_type": _tier_type, "fee": _fee,
                "duration_months": _months, "order": _order,
                "ladder_rank": _ladder, "is_active": True,
            },
        )

    # Make room in the display order for the two new tiers, then create
    # them. Every other existing row's `order` is untouched.
    MembershipTier.objects.filter(name="Full Annual Member").update(order=9)
    MembershipTier.objects.filter(name="Student Annual Membership").update(order=10)

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

    tiers_by_name = {t.name: t for t in MembershipTier.objects.filter(name__in=TIER_ORDER)}
    missing = set(TIER_ORDER) - set(tiers_by_name)
    if missing:
        raise RuntimeError(f"Expected MembershipTier rows missing, aborting seed: {missing}")

    for row_order, (name, axis, cells) in enumerate(BENEFIT_ROWS, start=1):
        benefit, _ = Benefit.objects.get_or_create(
            name=name, defaults={"axis": axis, "display_order": row_order}
        )
        for tier_name, raw in zip(TIER_ORDER, cells):
            status, detail = _parse_cell(raw)
            TierBenefit.objects.update_or_create(
                tier=tiers_by_name[tier_name], benefit=benefit,
                defaults={"status": status, "detail": detail, "display_order": row_order},
            )


def unseed(apps, schema_editor):
    MembershipTier = apps.get_model("home", "MembershipTier")
    Benefit = apps.get_model("home", "Benefit")

    Benefit.objects.filter(name__in=[row[0] for row in BENEFIT_ROWS]).delete()
    # Only the two tiers this migration originally introduced are removed.
    # The eight seeded at the top of seed() predate this migration on every
    # existing environment, so deleting them on reverse would destroy rows
    # this migration never owned.
    MembershipTier.objects.filter(name__in=["Associate", "Registered"]).delete()
    MembershipTier.objects.filter(name="Full Annual Member").update(order=8)
    MembershipTier.objects.filter(name="Student Annual Membership").update(order=9)


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0015_benefit_alter_membershiptier_tier_type_tierbenefit"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
