"""
Data migration applying the tier-differentiation redesign (2026-08-10
membership strategy audit) on top of the matrix seeded in 0016.

Fixes the one structural break (AGM vote sat on the cheaper Full Annual
tier and NOT on the pricier Associate tier, so Associate was a strict
downgrade at a higher price) and tightens the flatlines the audit found
(career services, library borrowing limits, sports guest passes,
consultancy panel, mentor programme, publication slots, advisory forum,
donor wall) into real escalation ladders. Two Benefit rows are
reclassified from VOICE to ACCESS (publication/speaking slots; VC/
Chancellor invitation) -- scarce channel/event access, not enforceable
governance input.

Deliberately NOT touched: Associate was kept as its own tier rather than
collapsed into Full Annual (Association decision 2026-08-10) -- its
entire differentiator is the AGM vote moved here.

Only updates existing TierBenefit rows (by tier name + benefit name) and
two Benefit.axis values -- no new MembershipTier/Benefit/TierBenefit rows,
no schema change.
"""
from django.db import migrations


# (benefit_name, tier_name, new_status, new_detail)
UPDATES = [
    # Physical ID card -- label consistency, Life tiers all read "permanent"
    ("Physical ID card", "Silver Life Member", "included", "permanent"),
    ("Physical ID card", "Gold Life Member", "included", "permanent"),
    ("Physical ID card", "Diamond Life Membership", "included", "permanent"),
    ("Physical ID card", "Platinum Life Membership", "included", "permanent"),

    # Library borrowing -- was a flat ✓ across 5 tiers spanning 25k-500k
    ("Library — borrowing + e-resources", "Bronze Life Member", "included", "5 items/mo"),
    ("Library — borrowing + e-resources", "Silver Life Member", "included", "10 items/mo"),
    ("Library — borrowing + e-resources", "Gold Life Member", "included", "15 items/mo"),
    ("Library — borrowing + e-resources", "Diamond Life Membership", "included", "25 items/mo"),
    ("Library — borrowing + e-resources", "Platinum Life Membership", "included", "unlimited"),

    # Career services -- was a flat ✓ across 8 tiers spanning 500-500,000
    ("Career services / job board", "Student Annual Membership", "included", "browse listings"),
    ("Career services / job board", "Full Annual Member", "included", "browse listings"),
    ("Career services / job board", "Associate", "included", "browse listings"),
    ("Career services / job board", "Bronze Life Member", "included", "apply direct"),
    ("Career services / job board", "Silver Life Member", "included", "résumé featured to recruiters"),
    ("Career services / job board", "Gold Life Member", "included", "1:1 career coaching"),
    ("Career services / job board", "Diamond Life Membership", "included", "executive-search referral"),
    ("Career services / job board", "Platinum Life Membership", "included", "C-suite intro network"),
    ("Career services / job board", "Corporate Membership", "not_applicable", ""),

    # AGM vote -- THE structural fix: moves from Full Annual to Associate
    ("Vote at AGM & Association elections", "Full Annual Member", "excluded", ""),
    ("Vote at AGM & Association elections", "Associate", "included", ""),

    # Parking -- Diamond=Platinum flatline at the most expensive pair
    ("Parking sticker", "Platinum Life Membership", "included", "reserved bay + valet"),

    # Sports & recreation -- was a flat ✓ across 4 tiers spanning 50k-500k
    ("Sports & recreation facilities", "Silver Life Member", "included", "member access"),
    ("Sports & recreation facilities", "Gold Life Member", "included", "+1 guest pass"),
    ("Sports & recreation facilities", "Diamond Life Membership", "included", "+2 guest passes"),
    ("Sports & recreation facilities", "Platinum Life Membership", "included", "+4 guest passes / family access"),

    # Consultancy panel -- removes the Silver=Gold and Diamond=Platinum duplicate pairs
    ("Consultancy / research / training panel", "Silver Life Member", "excluded", ""),
    ("Consultancy / research / training panel", "Platinum Life Membership", "included", "first refusal"),

    # Working space -- removes the Bronze=Silver duplicate
    ("UONAA working space", "Bronze Life Member", "excluded", ""),

    # Mentor programme -- differentiates the receiving tiers, reframes the giving tiers
    ("Mentor programme — priority matching", "Associate", "included", "mentor, priority pairing"),
    ("Mentor programme — priority matching", "Bronze Life Member", "included", "mentor, dedicated coordinator"),
    ("Mentor programme — priority matching", "Silver Life Member", "included", "mentor (give back)"),
    ("Mentor programme — priority matching", "Gold Life Member", "included", "mentor (give back)"),
    ("Mentor programme — priority matching", "Diamond Life Membership", "included", "mentor (give back)"),
    ("Mentor programme — priority matching", "Platinum Life Membership", "included", "mentor (give back)"),

    # Publication/speaking slots -- was a flat ✓ across Gold-Platinum
    ("Publication / speaking slots in Association channels", "Gold Life Member", "included", "occasional feature"),
    ("Publication / speaking slots in Association channels", "Diamond Life Membership", "included", "regular column"),
    ("Publication / speaking slots in Association channels", "Platinum Life Membership", "included", "keynote / cover feature"),

    # Advisory forum -- splits consultative (Diamond) from voting (Platinum)
    ("Advisory forum / committee co-option", "Diamond Life Membership", "included", "forum seat (consultative)"),
    ("Advisory forum / committee co-option", "Platinum Life Membership", "included", "committee seat (voting)"),

    # Donor wall -- was a flat ✓ across Gold/Diamond/Platinum/Corporate
    ("Alumni Centre — donor wall", "Gold Life Member", "included", "standard listing"),
    ("Alumni Centre — donor wall", "Diamond Life Membership", "included", "featured plaque"),
    ("Alumni Centre — donor wall", "Platinum Life Membership", "included", "lead placement"),
    ("Alumni Centre — donor wall", "Corporate Membership", "included", "institutional wall"),

    # Shareholding -- Corporate's terms named distinctly from the individual track
    ("Alumni Centre shareholding pre-emption", "Corporate Membership", "included", "institutional terms"),
]

# (benefit_name, old_axis, new_axis) -- reclassified per the four-axis test
AXIS_UPDATES = [
    ("Publication / speaking slots in Association channels", "voice", "access"),
    ("Standing invitation to VC / Chancellor functions", "voice", "access"),
]


def apply_redesign(apps, schema_editor):
    MembershipTier = apps.get_model("home", "MembershipTier")
    Benefit = apps.get_model("home", "Benefit")
    TierBenefit = apps.get_model("home", "TierBenefit")

    for benefit_name, tier_name, status, detail in UPDATES:
        tb = TierBenefit.objects.get(
            benefit__name=benefit_name,
            tier=MembershipTier.objects.get(name=tier_name),
        )
        tb.status = status
        tb.detail = detail
        tb.save(update_fields=["status", "detail"])

    for benefit_name, _old_axis, new_axis in AXIS_UPDATES:
        Benefit.objects.filter(name=benefit_name).update(axis=new_axis)


def revert_redesign(apps, schema_editor):
    MembershipTier = apps.get_model("home", "MembershipTier")
    Benefit = apps.get_model("home", "Benefit")
    TierBenefit = apps.get_model("home", "TierBenefit")

    # Reconstruct the pre-redesign values from 0016's own seed data rather
    # than guessing -- these are exactly the cells UPDATES touched, with
    # their original (status, detail) restored.
    ORIGINAL = {
        ("Physical ID card", "Silver Life Member"): ("included", ""),
        ("Physical ID card", "Gold Life Member"): ("included", ""),
        ("Physical ID card", "Diamond Life Membership"): ("included", ""),
        ("Physical ID card", "Platinum Life Membership"): ("included", ""),
        ("Library — borrowing + e-resources", "Bronze Life Member"): ("included", ""),
        ("Library — borrowing + e-resources", "Silver Life Member"): ("included", ""),
        ("Library — borrowing + e-resources", "Gold Life Member"): ("included", ""),
        ("Library — borrowing + e-resources", "Diamond Life Membership"): ("included", ""),
        ("Library — borrowing + e-resources", "Platinum Life Membership"): ("included", ""),
        ("Career services / job board", "Student Annual Membership"): ("included", ""),
        ("Career services / job board", "Full Annual Member"): ("included", ""),
        ("Career services / job board", "Associate"): ("included", ""),
        ("Career services / job board", "Bronze Life Member"): ("included", ""),
        ("Career services / job board", "Silver Life Member"): ("included", ""),
        ("Career services / job board", "Gold Life Member"): ("included", ""),
        ("Career services / job board", "Diamond Life Membership"): ("included", ""),
        ("Career services / job board", "Platinum Life Membership"): ("included", ""),
        ("Career services / job board", "Corporate Membership"): ("excluded", ""),
        ("Vote at AGM & Association elections", "Full Annual Member"): ("included", ""),
        ("Vote at AGM & Association elections", "Associate"): ("excluded", ""),
        ("Parking sticker", "Platinum Life Membership"): ("included", "reserved bay"),
        ("Sports & recreation facilities", "Silver Life Member"): ("included", ""),
        ("Sports & recreation facilities", "Gold Life Member"): ("included", ""),
        ("Sports & recreation facilities", "Diamond Life Membership"): ("included", ""),
        ("Sports & recreation facilities", "Platinum Life Membership"): ("included", ""),
        ("Consultancy / research / training panel", "Silver Life Member"): ("included", "eligible"),
        ("Consultancy / research / training panel", "Platinum Life Membership"): ("included", "priority"),
        ("UONAA working space", "Bronze Life Member"): ("included", "discounted"),
        ("Mentor programme — priority matching", "Associate"): ("included", "mentor"),
        ("Mentor programme — priority matching", "Bronze Life Member"): ("included", "mentor"),
        ("Mentor programme — priority matching", "Silver Life Member"): ("included", ""),
        ("Mentor programme — priority matching", "Gold Life Member"): ("included", ""),
        ("Mentor programme — priority matching", "Diamond Life Membership"): ("included", ""),
        ("Mentor programme — priority matching", "Platinum Life Membership"): ("included", ""),
        ("Publication / speaking slots in Association channels", "Gold Life Member"): ("included", ""),
        ("Publication / speaking slots in Association channels", "Diamond Life Membership"): ("included", ""),
        ("Publication / speaking slots in Association channels", "Platinum Life Membership"): ("included", ""),
        ("Advisory forum / committee co-option", "Diamond Life Membership"): ("included", ""),
        ("Advisory forum / committee co-option", "Platinum Life Membership"): ("included", ""),
        ("Alumni Centre — donor wall", "Gold Life Member"): ("included", ""),
        ("Alumni Centre — donor wall", "Diamond Life Membership"): ("included", ""),
        ("Alumni Centre — donor wall", "Platinum Life Membership"): ("included", ""),
        ("Alumni Centre — donor wall", "Corporate Membership"): ("included", ""),
        ("Alumni Centre shareholding pre-emption", "Corporate Membership"): ("included", ""),
    }
    for (benefit_name, tier_name), (status, detail) in ORIGINAL.items():
        tb = TierBenefit.objects.get(
            benefit__name=benefit_name,
            tier=MembershipTier.objects.get(name=tier_name),
        )
        tb.status = status
        tb.detail = detail
        tb.save(update_fields=["status", "detail"])

    for benefit_name, old_axis, _new_axis in AXIS_UPDATES:
        Benefit.objects.filter(name=benefit_name).update(axis=old_axis)


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0016_seed_tier_benefits"),
    ]

    operations = [
        migrations.RunPython(apply_redesign, revert_redesign),
    ]
