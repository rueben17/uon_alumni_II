# apps/home/management/commands/expire_lapsed_installment_plans.py
"""
Flips ACTIVE installment-plan Memberships to EXPIRED once they're past
their grace period (Membership.is_overdue -- one full billing cycle past
next_installment_due, e.g. 60 days total for a monthly plan).

Membership.is_overdue is computed live, so admin/dashboard display is
always correct even between runs of this command -- what THIS command
does is make that judgment stick in the `status` field itself, which is
what MembershipManager/is_valid/everything else actually trusts.

There is no scheduled-task infrastructure in this project yet (no Celery,
no cron wired up on the VPS) -- this needs to be run periodically by
whatever mechanism gets set up for that (see docs/todo.md Phase 3's
"scheduled jobs" note, the same gap). Safe to run as often as you like in
the meantime; it's idempotent -- membership.status only ever moves
PENDING/ACTIVE -> EXPIRED here, never the other direction.
"""
from django.core.management.base import BaseCommand

from apps.home.models import Membership


class Command(BaseCommand):
    help = "Expire installment-plan memberships that are past their grace period"

    def handle(self, *args, **options):
        # is_lifetime is about DURATION (never expires once paid off) --
        # orthogonal to payment status. A Life Member mid-installment-plan
        # is exactly the case this command needs to catch if they stop
        # paying, so it is deliberately NOT excluded here. is_overdue
        # itself already handles "fully paid" correctly regardless of
        # is_lifetime (apps/home/models.py).
        candidates = Membership.objects.filter(
            status=Membership.Status.ACTIVE,
        ).exclude(payment_frequency=Membership.PaymentFrequency.ONCE)

        expired = 0
        for membership in candidates:
            if membership.is_overdue:
                membership.status = Membership.Status.EXPIRED
                membership.save(update_fields=["status"])
                expired += 1
                self.stdout.write(
                    f"  Expired: {membership.user.email} - {membership.tier.name} "
                    f"(balance due KES {membership.balance_due})"
                )

        self.stdout.write(self.style.SUCCESS(f"Done: {expired} installment plan(s) expired."))
