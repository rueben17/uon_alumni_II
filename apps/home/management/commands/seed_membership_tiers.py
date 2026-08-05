# apps/home/management/commands/seed_membership_tiers.py
"""
Seeds MembershipTier from the official UoN Alumni Association membership
form's "Membership Subscription" table.

Two fixes over the original seed data, per docs/0.1-identity-decisions.md's
own resolutions (technical fixes, not business decisions):
  - Honorary and Corporate used duration_months=0, which
    MembershipTier.is_lifetime() reads as "lifetime" -- silently permanent
    by accident, not because anyone decided these should never expire.
    Provisional 12-month period so they're at least *payable* on a period;
    the actual billing cadence is still the Association's call.
  - Student Annual now uses tier_type="student" (added to TIER_TYPES
    alongside this rebuild) instead of "annual" -- it's the pipeline tier,
    not a variant of the paid annual membership.

ladder_rank encodes the monotonic upgrade path already settled in
todo.md's guiding decisions (Annual -> Bronze -> Silver -> Gold ->
Corporate) -- not seeded on tiers outside that path (Honorary, Student,
Platinum, Diamond).

Platinum/Diamond and Honorary/Corporate's real billing period remain open
per docs/rebuild-schema.md's "Still the Association's call" section --
kept here for continuity with what the old system offered, not as a
decision this command is making.
"""
from django.core.management.base import BaseCommand

from apps.home.models import MembershipTier

# (name, fee, tier_type, duration_months, order, ladder_rank)
TIER_DATA = [
    ("Corporate Membership", 1_000_000, "corporate", 12, 1, 5),
    ("Platinum Life Membership", 500_000, "life", 0, 2, None),
    ("Diamond Life Membership", 250_000, "life", 0, 3, None),
    ("Gold Life Member", 100_000, "life", 0, 4, 4),
    ("Silver Life Member", 50_000, "life", 0, 5, 3),
    ("Bronze Life Member", 25_000, "life", 0, 6, 2),
    ("Honorary Member", 3_000, "honorary", 12, 7, None),
    ("Full Annual Member", 2_000, "annual", 12, 8, 1),
    ("Student Annual Membership", 500, "student", 12, 9, None),
]


class Command(BaseCommand):
    help = "Populate MembershipTier from the official membership form's fee table"

    def handle(self, *args, **options):
        created_count = 0

        for name, fee, tier_type, duration_months, order, ladder_rank in TIER_DATA:
            tier, created = MembershipTier.objects.get_or_create(
                name=name,
                defaults={
                    "fee": fee,
                    "tier_type": tier_type,
                    "duration_months": duration_months,
                    "order": order,
                    "ladder_rank": ladder_rank,
                },
            )
            if created:
                created_count += 1
                self.stdout.write(f"  Created tier: {tier.name} (KES {tier.fee})")

        self.stdout.write(
            self.style.SUCCESS(f"Done: {created_count} membership tiers created.")
        )
