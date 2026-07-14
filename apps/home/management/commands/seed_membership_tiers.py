# apps/home/management/commands/seed_membership_tiers.py
"""
Seeds MembershipTier from the official UoN Alumni Association membership
form's "Membership Subscription" table.
"""
from django.core.management.base import BaseCommand

from apps.home.models import MembershipTier

# (name, fee, tier_type, duration_months, order)
TIER_DATA = [
    ("Corporate Membership", 1_000_000, "corporate", 0, 1),
    ("Platinum Life Membership", 500_000, "life", 0, 2),
    ("Diamond Life Membership", 250_000, "life", 0, 3),
    ("Gold Life Member", 100_000, "life", 0, 4),
    ("Silver Life Member", 50_000, "life", 0, 5),
    ("Bronze Life Member", 25_000, "life", 0, 6),
    ("Honorary Member", 3_000, "honorary", 0, 7),
    ("Full Annual Member", 2_000, "annual", 12, 8),
    ("Student Annual Membership", 500, "annual", 12, 9),
]


class Command(BaseCommand):
    help = "Populate MembershipTier from the official membership form's fee table"

    def handle(self, *args, **options):
        created_count = 0

        for name, fee, tier_type, duration_months, order in TIER_DATA:
            tier, created = MembershipTier.objects.get_or_create(
                name=name,
                defaults={
                    "fee": fee,
                    "tier_type": tier_type,
                    "duration_months": duration_months,
                    "order": order,
                },
            )
            if created:
                created_count += 1
                self.stdout.write(f"  Created tier: {tier.name} (KES {tier.fee})")

        self.stdout.write(
            self.style.SUCCESS(f"Done: {created_count} membership tiers created.")
        )
