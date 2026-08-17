# apps/home/management/commands/reconcile_constitutional_categories.py
"""
Reconciles MembershipTier against the eleven membership categories in the
UONAA Constitution (Art. 8) and backfills each one's constitutional
provisions (term, governance rights, ratification route, caps, age
thresholds). Safe to rerun -- a second run makes zero changes.

Ground truth this was built against (2026-08-18 investigation, reported
and confirmed before any of this was written):
  - Only Art. 8(c) through 8(h) were supplied. 8(a)/8(b) were not seen --
    every provision that depends on them stays null (SILENT), never
    inferred.
  - Eight of the eleven categories already exist as MembershipTier rows,
    under names that don't always match the Constitution's own display
    name verbatim (e.g. "Full Annual Member" for "Ordinary/Annual").
    Existing rows are matched by their CURRENT name (MATCH_BY_NAME
    below, first-run only) and then enriched in place -- `name` itself
    is never touched, per this task's own "no existing row renamed"
    rule. Three categories (Founder, Affiliate, Senior Citizen) have no
    existing row and are created fresh, with the Constitution's own
    display name used verbatim since there's nothing to rename.
  - Three existing rows -- "Diamond Life Membership", "Associate", and
    "Registered" -- have no seat in the eleven and are never referenced
    by this command. Left completely untouched (not renamed, not
    disabled, not deleted). Diamond/Associate are exactly the prior
    ten-tier matrix's leftovers this task explicitly has no authority
    to create; Registered is a real, separate, non-constitutional free
    signup tier (apps/home/views.py's MembershipCategoriesView already
    excludes it from the public comparison page on that basis).
  - code, display_order, and every "constitutional provision" field
    (holder_type, fee_amount, fee_basis, ...) are additive/new
    (2026-08-18 model change) -- deliberately parallel to, not a
    replacement for, the pre-existing name/fee/tier_type/duration_months
    /order fields, which this command never modifies on an existing row.
  - tier_type/fee/duration_months/order are pre-existing, REQUIRED
    fields with no constitutional equivalent in the approved Field Set.
    For newly-created rows, they're set to the closest existing fit
    (confirmed 2026-08-18, not guessed): Affiliate -> tier_type
    "registered" (fee 0, matching its own every-provision-SILENT
    status); Senior Citizen -> tier_type "annual" (fee mirrors
    fee_amount, duration_months 12). order continues sequentially after
    the current max. Founder's legacy_tier_type/legacy_fee/
    legacy_duration_months in its spec below are vestigial -- it was
    originally created fresh this same way (tier_type "life"), then
    immediately repurposed from "Platinum Life Membership" instead (see
    that spec's own comment), so its CREATE path is unreachable in
    practice today.

Conflicts in the supplied constitutional text (reported, not resolved,
per this task's own instruction -- each one's chosen handling is
encoded directly in CATEGORY_SPECS below):
  - Art. 8(e) gives Honorary three incompatible routes to membership:
    8(e)(i) General Assembly ELECTION, 8(e)(iii) a prescribed FEE plus
    two-thirds ratification, 8(e)(ii) AUTOMATIC conferral on faculty
    with neither. Honorary's fee_amount is left null.
  - Art. 8(d) is headed "Full membership" but its body grants
    eligibility for "Life membership", and "Full" appears nowhere in
    the eleven-category list -- treated here as the Life band's
    eligibility criteria (Gold/Silver/Bronze, and originally Platinum --
    see the note on Platinum below), not a twelfth category.
  - Affiliate is named in the category list with no defining provision
    anywhere in the supplied text -- every provision field stays null.
  - Founder's relationship to the Life band is unstated, so its
    governance rights cannot be derived and stay null.
  - Whether the Life tiers differ in anything but fee is unstated --
    Gold/Silver/Bronze carry identical provisions below, distinguished
    only by fee_amount.

Post-reconciliation change (2026-08-18, outside this command, done once
by hand): "Platinum Life Membership" (which already carried 25 real
TierBenefit rows) was renamed to "Founder" and given Founder's
provisions in place of its own, rather than keeping both it and the
freshly-created empty Founder row side by side. Platinum no longer
exists as a backed category -- see the "founder" spec's own comment
below for the full reasoning.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from apps.home.models import Membership, MembershipTier

# Shared verbatim eligibility text + provisions for the four Life tiers
# (Art. 8(h), eligibility via Art. 8(d)) -- identical on all four per the
# supplied text; only code/match/display_order/fee_amount differ.
_LIFE_TIER_ELIGIBILITY_NOTES = (
    "Award holders of the University; honorary degree holders; persons pursuing awards; "
    "full-time permanent staff who are not former UoN students but hold a degree from another "
    "recognised institution; holders of awards from other tertiary institutions who applied, "
    "were vetted and admitted by the Executive Committee; members of the University Council and "
    "the Chancellor."
)
_LIFE_TIER_BASE = {
    "holder_type": MembershipTier.HolderType.INDIVIDUAL,
    "fee_basis": MembershipTier.FeeBasis.ONE_OFF,
    "fee_is_provisional": True,
    "is_life": True,
    "max_term_years": None,
    "membership_cap": None,
    "minimum_age": None,
    "requires_general_assembly_election": None,
    "requires_executive_ratification": None,
    "can_vote_governing_body": True,
    "can_stand_for_executive_committee": True,
    "eligible_for_appointment": True,
    "constitution_reference": "Art. 8(h), Art. 8(d)",
    "provisions_confirmed": True,
    "eligibility_notes": _LIFE_TIER_ELIGIBILITY_NOTES,
}


def _life_tier(code, match_by_name, constitution_name, display_order, fee_amount):
    return {
        "code": code,
        "constitution_name": constitution_name,
        "match_by_name": match_by_name,
        "display_order": display_order,
        "fee_amount": fee_amount,
        # New-row-only legacy fields (only used if match_by_name finds
        # nothing and this has to be created -- not expected here, all
        # four already exist, but kept for symmetry/safety).
        "legacy_tier_type": "life",
        "legacy_fee": fee_amount,
        "legacy_duration_months": 0,
        **_LIFE_TIER_BASE,
    }


# One spec per Constitutional category, in the Constitution's own order.
# match_by_name is only consulted when code doesn't match anything yet
# (i.e. the first run, before code has ever been set) -- see handle()
# below for the exact lookup order.
CATEGORY_SPECS = [
    {
        "code": "founder",
        "constitution_name": "Founder",
        # Originally created fresh (no existing row). 2026-08-18: the
        # Association repurposed "Platinum Life Membership" (pk=3) as
        # Founder instead -- it already carried 25 real TierBenefit rows
        # Founder had none of, so the freshly-created empty row was
        # deleted and Platinum was renamed onto this code/spec in place,
        # taking its benefits with it (renaming doesn't touch a
        # TierBenefit's FK, which points at the row's id, not its name).
        # match_by_name is now purely a documentation/fallback path --
        # every real run finds this row by code='founder' first, set on
        # it during that one-time rename.
        "match_by_name": "Platinum Life Membership",
        "display_order": 1,
        "holder_type": MembershipTier.HolderType.INDIVIDUAL,
        "fee_basis": MembershipTier.FeeBasis.ONE_OFF,
        "fee_amount": 100_000,
        "fee_is_provisional": True,
        "is_life": None,  # SILENT -- 8(c) does not state it
        "max_term_years": None,
        "membership_cap": 1000,
        "minimum_age": None,
        "requires_general_assembly_election": None,
        "requires_executive_ratification": None,
        "can_vote_governing_body": None,  # SILENT -- relationship to Life band unstated
        "can_stand_for_executive_committee": None,
        "eligible_for_appointment": None,
        "constitution_reference": "Art. 8(c)",
        "provisions_confirmed": False,
        "eligibility_notes": "First 1,000 persons satisfying Article 8(a). Prescribed fee payable.",
        "legacy_tier_type": "life",
        "legacy_fee": 100_000,
        "legacy_duration_months": 0,
    },
    # No separate Platinum entry (2026-08-18): the row that used to back
    # it, "Platinum Life Membership", was renamed onto the Founder spec
    # above instead -- see that spec's comment. Platinum is no longer a
    # backed category; display_order 2 is deliberately left open rather
    # than renumbered.
    _life_tier("gold_life", "Gold Life Member", "Gold life", 3, 100_000),
    _life_tier("silver_life", "Silver Life Member", "Silver life", 4, 50_000),
    _life_tier("bronze_life", "Bronze Life Member", "Bronze life", 5, 25_000),
    {
        "code": "ordinary_annual",
        "constitution_name": "Ordinary/Annual",
        "match_by_name": "Full Annual Member",
        "display_order": 6,
        "holder_type": MembershipTier.HolderType.INDIVIDUAL,
        "fee_basis": MembershipTier.FeeBasis.ANNUAL,
        "fee_amount": 2_000,
        "fee_is_provisional": True,
        "is_life": None,
        "max_term_years": None,
        "membership_cap": None,
        "minimum_age": None,
        "requires_general_assembly_election": None,
        "requires_executive_ratification": None,
        "can_vote_governing_body": None,
        "can_stand_for_executive_committee": None,
        "eligible_for_appointment": None,
        "constitution_reference": "",  # no defining article supplied
        "provisions_confirmed": False,
        "eligibility_notes": "",
        "legacy_tier_type": "annual",
        "legacy_fee": 2_000,
        "legacy_duration_months": 12,
    },
    {
        "code": "student",
        "constitution_name": "Student",
        "match_by_name": "Student Annual Membership",
        "display_order": 7,
        "holder_type": MembershipTier.HolderType.INDIVIDUAL,
        "fee_basis": MembershipTier.FeeBasis.ANNUAL,
        "fee_amount": 500,
        "fee_is_provisional": True,
        "is_life": None,
        "max_term_years": None,
        "membership_cap": None,
        "minimum_age": None,
        "requires_general_assembly_election": None,
        "requires_executive_ratification": None,
        "can_vote_governing_body": None,
        "can_stand_for_executive_committee": None,
        "eligible_for_appointment": None,
        "constitution_reference": "",  # no Student-specific article supplied
        "provisions_confirmed": False,
        "eligibility_notes": (
            "Persons pursuing academic awards with the University -- inferred from Art. "
            "8(d)(iii), not from a Student-specific provision."
        ),
        "legacy_tier_type": "student",
        "legacy_fee": 500,
        "legacy_duration_months": 12,
    },
    {
        "code": "affiliate",
        "constitution_name": "Affiliate",
        "match_by_name": None,  # no existing row -- created fresh
        "display_order": 8,
        "holder_type": None,  # SILENT
        "fee_basis": MembershipTier.FeeBasis.NONE,
        "fee_amount": None,
        "fee_is_provisional": True,
        "is_life": None,
        "max_term_years": None,
        "membership_cap": None,
        "minimum_age": None,
        "requires_general_assembly_election": None,
        "requires_executive_ratification": None,
        "can_vote_governing_body": None,
        "can_stand_for_executive_committee": None,
        "eligible_for_appointment": None,
        "constitution_reference": "",
        "provisions_confirmed": False,
        "eligibility_notes": "Named in the category list. No defining provision in the supplied text.",
        "legacy_tier_type": "registered",
        "legacy_fee": 0,
        "legacy_duration_months": 0,
    },
    {
        "code": "honorary",
        "constitution_name": "Honorary",
        "match_by_name": "Honorary Member",
        "display_order": 9,
        "holder_type": MembershipTier.HolderType.INDIVIDUAL,
        "fee_basis": None,  # not stated
        "fee_amount": None,  # Conflicts: three incompatible routes, one with no fee at all
        "fee_is_provisional": True,
        "is_life": None,  # not stated
        "max_term_years": 5,
        "membership_cap": None,
        "minimum_age": None,
        "requires_general_assembly_election": True,
        "requires_executive_ratification": True,
        "can_vote_governing_body": False,  # 8(e)(f) expressly excludes them
        "can_stand_for_executive_committee": None,
        "eligible_for_appointment": None,
        "constitution_reference": "Art. 8(e)",
        "provisions_confirmed": True,
        "eligibility_notes": (
            "Persons part of the University community who are not graduates; persons with "
            "sustained impact on the lives of graduate alumni and students, or who foster "
            "relationships across the University community; persons maintaining close "
            "association with the University or Association. Entitled to announcements, the "
            "Alumni Newsletter, the Annual Magazine, and participation in social functions and "
            "activities. Beneficiaries of any Association schemes or assistance programmes. "
            "Separately, Art. 8(e)(ii) deems all regular faculty Honorary Members for as long as "
            "they hold a regular position -- automatic conferral, no election, no fee."
        ),
        "legacy_tier_type": None,  # existing row, legacy fields untouched
        "legacy_fee": None,
        "legacy_duration_months": None,
    },
    {
        "code": "corporate",
        "constitution_name": "Corporate",
        "match_by_name": "Corporate Membership",
        "display_order": 10,
        "holder_type": MembershipTier.HolderType.ORGANISATION,
        "fee_basis": MembershipTier.FeeBasis.PER_TERM,
        "fee_amount": 1_000_000,
        "fee_is_provisional": True,
        "is_life": None,
        "max_term_years": 5,
        "membership_cap": None,
        "minimum_age": None,
        "requires_general_assembly_election": True,
        "requires_executive_ratification": True,
        "can_vote_governing_body": False,  # 8(f)(iii) expressly excludes them
        "can_stand_for_executive_committee": False,  # an organisation cannot sit on the Committee
        "eligible_for_appointment": None,
        "constitution_reference": "Art. 8(f)",
        "provisions_confirmed": True,
        "eligibility_notes": (
            "Institutions or organisations connected with the University or Association, or "
            "otherwise likely to promote its interests. Entitled to announcements, the Alumni "
            "Newsletter, the Annual Magazine, and participation in social functions and "
            "activities. Beneficiaries of Association schemes or assistance programmes."
        ),
        "legacy_tier_type": None,
        "legacy_fee": None,
        "legacy_duration_months": None,
    },
    {
        "code": "senior_citizen",
        "constitution_name": "Senior Citizen",
        "match_by_name": None,  # no existing row -- created fresh
        "display_order": 11,
        "holder_type": MembershipTier.HolderType.INDIVIDUAL,
        "fee_basis": MembershipTier.FeeBasis.ANNUAL,
        "fee_amount": 1_000,
        "fee_is_provisional": True,
        "is_life": None,
        "max_term_years": None,
        "membership_cap": None,
        "minimum_age": 65,
        "requires_general_assembly_election": None,
        "requires_executive_ratification": None,
        "can_vote_governing_body": None,  # SILENT -- 8(g) states none
        "can_stand_for_executive_committee": None,
        "eligible_for_appointment": None,
        "constitution_reference": "Art. 8(g)",
        "provisions_confirmed": True,
        "eligibility_notes": (
            "Members aged 65 and above who satisfy the requirements of Article 8, upon payment "
            "of the prescribed membership fee."
        ),
        "legacy_tier_type": "annual",
        "legacy_fee": 1_000,
        "legacy_duration_months": 12,
    },
]

# Fields copied verbatim onto the tier row, straight from each spec dict.
PROVISION_FIELDS = [
    "holder_type", "fee_basis", "fee_is_provisional", "is_life", "max_term_years",
    "membership_cap", "minimum_age", "requires_general_assembly_election",
    "requires_executive_ratification", "can_vote_governing_body",
    "can_stand_for_executive_committee", "eligible_for_appointment",
    "constitution_reference", "provisions_confirmed", "eligibility_notes", "display_order",
]

UNRECOGNISED_NAMES = ["Diamond Life Membership", "Associate", "Registered"]


class Command(BaseCommand):
    help = "Reconcile MembershipTier against the eleven UONAA Constitution membership categories."

    def handle(self, *args, **options):
        before_counts = self._membership_counts_by_tier()

        created, updated, unchanged = [], [], []
        next_order = (MembershipTier.objects.order_by("-order").values_list("order", flat=True).first() or 0) + 1

        with transaction.atomic():
            for spec in CATEGORY_SPECS:
                tier = MembershipTier.objects.filter(code=spec["code"]).first()

                if tier is None and spec["match_by_name"]:
                    tier = MembershipTier.objects.filter(name=spec["match_by_name"]).first()

                if tier is None:
                    tier = MembershipTier(
                        name=spec["constitution_name"],
                        code=spec["code"],
                        tier_type=spec["legacy_tier_type"],
                        fee=spec["legacy_fee"],
                        duration_months=spec["legacy_duration_months"],
                        order=next_order,
                    )
                    next_order += 1
                    is_new = True
                else:
                    is_new = False

                row_changed = is_new
                if tier.code != spec["code"]:
                    tier.code = spec["code"]
                    row_changed = True

                for field in PROVISION_FIELDS:
                    target = spec[field]
                    if getattr(tier, field) != target:
                        setattr(tier, field, target)
                        row_changed = True

                # fee_amount: only ever set from null -> value, never
                # overwritten once non-null, even across a re-run with a
                # revised spec value -- the one field with its own
                # explicit "never overwrite" rule in this task's brief.
                if tier.fee_amount is None and spec["fee_amount"] is not None:
                    tier.fee_amount = spec["fee_amount"]
                    row_changed = True

                if row_changed:
                    tier.save()
                    (created if is_new else updated).append(tier)
                else:
                    unchanged.append(tier)

        after_counts = self._membership_counts_by_tier()

        self._report(created, updated, unchanged, before_counts, after_counts)

    def _membership_counts_by_tier(self):
        """{tier_id: count} for every tier with at least one Membership row.
        Compared before/after so a bug that reassigned or orphaned a live
        Membership row would show up immediately in the report, even
        though this command never writes to Membership at all."""
        rows = Membership.objects.values("tier_id").annotate(n=Count("id"))
        return {row["tier_id"]: row["n"] for row in rows}

    def _report(self, created, updated, unchanged, before_counts, after_counts):
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created {len(created)}:"))
            for t in created:
                self.stdout.write(f"  + [{t.pk}] {t.name} (code={t.code})")
        if updated:
            self.stdout.write(self.style.WARNING(f"Updated {len(updated)}:"))
            for t in updated:
                self.stdout.write(f"  ~ [{t.pk}] {t.name} (code={t.code})")
        if unchanged:
            self.stdout.write(f"Unchanged {len(unchanged)}:")
            for t in unchanged:
                self.stdout.write(f"  = [{t.pk}] {t.name} (code={t.code})")

        self.stdout.write("")
        self.stdout.write("Skipped (no constitutional basis, left untouched):")
        for name in UNRECOGNISED_NAMES:
            tier = MembershipTier.objects.filter(name=name).first()
            if tier:
                self.stdout.write(f"  - [{tier.pk}] {tier.name} -- not one of the eleven categories")

        self.stdout.write("")
        self.stdout.write(f"Membership counts before: {before_counts}")
        self.stdout.write(f"Membership counts after:  {after_counts}")
        self.stdout.write(
            self.style.SUCCESS("Membership counts identical -- no reassignment occurred.")
            if before_counts == after_counts
            else self.style.ERROR("MEMBERSHIP COUNTS CHANGED -- investigate before trusting this run.")
        )

        self.stdout.write("")
        unconfirmed = MembershipTier.objects.filter(code__isnull=False, provisions_confirmed=False).order_by("display_order")
        self.stdout.write(f"provisions_confirmed=False ({unconfirmed.count()}):")
        for t in unconfirmed:
            self.stdout.write(f"  ? [{t.pk}] {t.name} (code={t.code})")
