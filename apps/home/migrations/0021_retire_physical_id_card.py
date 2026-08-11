"""
Data migration retiring the "Physical ID card" benefit (Association
decision 2026-08-11): no more physical cards are issued -- "Digital
alumni ID (QR)" (already included on every paying individual tier, see
0016) is now the only membership credential.

Flips the currently-included TierBenefit rows to excluded rather than
deleting the Benefit/TierBenefit rows outright, matching 0017's pattern --
keeps the row (and its history) intact and the change cleanly reversible.
Registered/Student Annual Membership/Corporate Membership are untouched:
they were already excluded/not_applicable for this benefit, not flipped
by 0017 either.
"""
from django.db import migrations


# (tier_name, previous_detail) -- the tiers where Physical ID card is
# currently `included`, per 0016's seed as amended by 0017.
CURRENTLY_INCLUDED = [
    ("Full Annual Member", "annual"),
    ("Associate", "annual"),
    ("Bronze Life Member", "permanent"),
    ("Silver Life Member", "permanent"),
    ("Gold Life Member", "permanent"),
    ("Diamond Life Membership", "permanent"),
    ("Platinum Life Membership", "permanent"),
]


def retire(apps, schema_editor):
    MembershipTier = apps.get_model("home", "MembershipTier")
    TierBenefit = apps.get_model("home", "TierBenefit")

    for tier_name, _previous_detail in CURRENTLY_INCLUDED:
        tb = TierBenefit.objects.get(
            benefit__name="Physical ID card",
            tier=MembershipTier.objects.get(name=tier_name),
        )
        tb.status = "excluded"
        tb.detail = ""
        tb.save(update_fields=["status", "detail"])


def reinstate(apps, schema_editor):
    MembershipTier = apps.get_model("home", "MembershipTier")
    TierBenefit = apps.get_model("home", "TierBenefit")

    for tier_name, previous_detail in CURRENTLY_INCLUDED:
        tb = TierBenefit.objects.get(
            benefit__name="Physical ID card",
            tier=MembershipTier.objects.get(name=tier_name),
        )
        tb.status = "included"
        tb.detail = previous_detail
        tb.save(update_fields=["status", "detail"])


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0020_alter_scholarshipapplication_year_of_study"),
    ]

    operations = [
        migrations.RunPython(retire, reinstate),
    ]
