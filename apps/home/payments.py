# apps/home/payments.py
"""
Payment gateway integration point.

No real gateway credentials exist yet (no M-Pesa/Daraja, Stripe, etc. in
settings) -- this module is the single place a real integration plugs
into later. Every payment method currently routes to ManualGateway, which
just leaves the Payment record for a supervisor to confirm by hand via
Payment.mark_as_completed() / mark_as_failed() / mark_as_pending_verification().

To add a real gateway later (e.g. M-Pesa STK push, Stripe):
  1. Add credentials to settings (mirroring GOOGLE_OAUTH_CLIENT_ID's pattern).
  2. Write a class implementing PaymentGateway.initiate()/verify().
  3. Point GATEWAYS["mpesa"] (or the relevant key) at it.
Nothing calling initiate_payment() needs to change.
"""
import logging

logger = logging.getLogger(__name__)


class PaymentGateway:
    """Interface every gateway (M-Pesa, Stripe, manual reconciliation) implements."""

    def initiate(self, payment):
        raise NotImplementedError

    def verify(self, payment):
        raise NotImplementedError


class ManualGateway(PaymentGateway):
    """
    No online processing -- the Payment stays 'pending' (cash/bank_transfer/
    cheque) or 'pending_verification' until a supervisor confirms it.
    """

    def initiate(self, payment):
        logger.info(
            "Payment %s (%s, KES %s) recorded for %s -- awaiting manual confirmation.",
            payment.transaction_reference, payment.payment_method, payment.amount, payment.alumni,
        )
        return payment

    def verify(self, payment):
        return payment.payment_status


GATEWAYS = {
    "mpesa": ManualGateway,
    "credit_card": ManualGateway,
    "bank_transfer": ManualGateway,
    "cash": ManualGateway,
    "cheque": ManualGateway,
}


def get_gateway(payment_method):
    gateway_class = GATEWAYS.get(payment_method, ManualGateway)
    return gateway_class()


def initiate_payment(payment):
    """Single entry point views call after creating a Payment row."""
    gateway = get_gateway(payment.payment_method)
    return gateway.initiate(payment)
