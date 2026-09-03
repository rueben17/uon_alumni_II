"""
Membership service layer -- the "one door" todo.md 1.3 asks for.

Every state change against a Membership -- creating a renewal/upgrade
request, or activating one once payment is confirmed -- goes through a
function here instead of call sites creating/mutating rows directly.
Today's callers are a self-service view and the admin's manual-approval
action; the point of centralizing this now is that a payment-gateway
callback (Phase 2) or a scheduled job (2.6's installment-upgrade
auto-bump) can become a caller later without re-deriving this logic.

Design decisions ratified 2026-08-08, built 2026-08-10:
  - A renewal/upgrade request is always a NEW Membership row -- the prior
    row is never mutated in place (Membership is FK-not-O2O so history
    accumulates; see the model's own docstring).
  - On activation, whatever was previously ACTIVE for that user is
    explicitly flipped to Status.SUPERSEDED (distinct from EXPIRED, which
    means they let it lapse with nothing replacing it).
  - membership_number carries forward from the superseded row rather than
    being regenerated -- it identifies the person/enrollment, not a
    single payment period, and the Phase 7 QR credential wants one
    durable identifier per member.
"""
from django.db import transaction
from django.utils import timezone

from apps.home.models import Membership


def _supersede_prior_active(membership):
    """If `membership` is being activated for the first time, find
    whatever was previously ACTIVE for the same user, carry its
    membership_number onto `membership` (only if `membership` doesn't
    already have one -- an admin-assigned number should never be
    overwritten), and return it so the caller can flip its status once
    the new row has actually activated. Returns None if there was nothing
    to supersede (this is the member's first-ever membership)."""
    prior_active = (
        Membership.objects.filter(user=membership.user, status=Membership.Status.ACTIVE)
        .exclude(pk=membership.pk)
        .first()
    )
    if prior_active and not membership.membership_number:
        membership.membership_number = prior_active.membership_number
    return prior_active


def _close_out(prior_active):
    if prior_active:
        prior_active.status = Membership.Status.SUPERSEDED
        prior_active.save(update_fields=["status", "updated_at"])


def activate_membership(membership, payment_date=None):
    """Activate a pending (lump-sum) Membership row. The one door for what
    PaymentAdmin.mark_completed() used to call membership.activate() for
    directly -- same underlying model method, now wrapped so renewal/
    upgrade supersession happens automatically instead of being the
    caller's job to remember.

    Supersedes the prior row BEFORE activating the new one, not after --
    the unique-while-active constraint on membership_number is checked
    per-statement, so activating first would briefly leave both rows
    ACTIVE with the same number and fail the constraint. Wrapped in
    transaction.atomic() so a reader never observes the moment in between
    where the user has zero active memberships.

    Idempotent on an already-ACTIVE row (no-op supersession) so a second
    call -- e.g. a retried admin action -- can't supersede a membership
    against itself.
    """
    with transaction.atomic():
        first_activation = membership.status != Membership.Status.ACTIVE
        if first_activation:
            _close_out(_supersede_prior_active(membership))
        membership.activate(payment_date=payment_date)
    return membership


def record_installment_payment(membership, amount, payment_date=None):
    """Record one installment toward `membership`. The one door for what
    PaymentAdmin.mark_completed() used to call
    membership.record_installment_payment() for directly -- activates (and
    supersedes/carries the number forward) on the FIRST installment only;
    subsequent installments just accumulate amount_paid, same as the
    underlying model method already did. Same supersede-before-activate
    ordering as activate_membership(), for the same reason.
    """
    with transaction.atomic():
        first_activation = membership.status != Membership.Status.ACTIVE
        if first_activation:
            _close_out(_supersede_prior_active(membership))
        membership.record_installment_payment(amount, payment_date=payment_date)
    return membership


def confirm_payment(payment):
    """Activate the membership a confirmed payment was for.

    The activation half of what PaymentAdmin.mark_completed used to do
    inline. It lives here so that every path which completes a payment --
    the admin bulk action, the admin change form, a shell call, a future
    gateway callback -- reaches the same one door, rather than only the
    bulk action doing it (finding D).

    Assumes the payment is already marked completed; it never touches
    payment status itself. Returns the membership it activated, or None
    when the payment carries no tier and there is nothing to apply.

    The two date arms are deliberately different and must stay that way
    (2026-08-21): an installment plan anchors next_installment_due to
    TODAY, the moment of Secretariat confirmation, because a request can
    sit pending for days or weeks and anchoring to the submission date
    could make an installment read as overdue the moment it activates.
    A lump-sum activation still uses the payment's own date.

    KNOWN BOUNDARY: assigning payment.payment_status = "completed" and
    calling save() directly bypasses this, because nothing observes that
    transition. Every entry point the application actually uses goes
    through Payment.mark_as_completed() or the admin, both of which call
    this. Catching a raw field write would need a save() override or a
    signal tracking the previous value -- deliberately not done.
    """
    tier = payment.membership_tier
    if not tier:
        return None

    if payment.membership_id:
        record_installment_payment(
            payment.membership, payment.amount, payment_date=timezone.now().date()
        )
        return payment.membership

    payment_date = payment.payment_date.date() if payment.payment_date else None
    user = payment.alumni.user
    membership = Membership.objects.filter(
        user=user, tier=tier, status=Membership.Status.PENDING
    ).order_by('-created_at').first()
    if membership is None:
        membership = Membership.objects.create(user=user, tier=tier)
    activate_membership(membership, payment_date=payment_date)
    return membership


def assign_membership_tier(user, tier, payment_frequency=Membership.PaymentFrequency.ONCE):
    """Create a new pending Membership row for `user` at `tier` -- the
    general-purpose door for a first-time grant, a renewal, or an upgrade
    alike (today's self-service form lets a member pick any tier from one
    dropdown, so there is no narrower case to special-case here). Left
    PENDING; call activate_membership()/record_installment_payment() once
    payment is confirmed, same as every other membership in this system
    (manual Secretariat approval, until Phase 2 automates it).
    """
    return Membership.objects.create(user=user, tier=tier, payment_frequency=payment_frequency)


def renew_membership(user, payment_frequency=Membership.PaymentFrequency.ONCE):
    """Member-initiated renewal at their CURRENT tier -- a narrower door
    than assign_membership_tier() for callers that specifically mean
    "renew what they already have," not "change tier." Raises if there's
    no current membership to read the tier from (a first-time grant is
    assign_membership_tier(), not this)."""
    current = Membership.objects.current_active_for(user)
    if current is None:
        raise ValueError("No current membership to renew -- use assign_membership_tier() for a first-time grant.")
    return assign_membership_tier(user, current.tier, payment_frequency=payment_frequency)


def upgrade_to_lifetime(user, tier, payment_frequency=Membership.PaymentFrequency.ONCE):
    """Member-initiated upgrade to a Life tier -- a narrower door than
    assign_membership_tier() for callers that specifically mean "move to
    a lifetime tier," not an arbitrary tier change. Raises on a non-life
    tier so a caller can't silently use this for an ordinary renewal."""
    if not tier.is_lifetime():
        raise ValueError(f"{tier.name} is not a lifetime tier -- use assign_membership_tier() for a same-cycle change.")
    return assign_membership_tier(user, tier, payment_frequency=payment_frequency)
