# apps/home/sms.py
"""
SMS gateway integration point -- mirrors apps/home/payments.py's shape.

No real SMS provider credentials exist yet -- this module is the single
place a real integration plugs into later. Every send currently routes to
LoggingSmsGateway, which just logs the message instead of sending it.

Deliberately not wired up to anything yet (docs/todo.md, 2026-08-07: phone
verification/OTP is "on hold... not forgotten" specifically because a real
gateway means a paid SMS provider, and that cost conversation hasn't
happened with the Association). This module -- and the Q2 task wrapping it
(apps/home/tasks.py's dispatch_sms) -- exist so the pipe is ready the
moment that conversation resolves. No view or model currently calls
send_sms().

To add a real gateway later (e.g. Africa's Talking):
  1. Add credentials to settings (mirroring GOOGLE_OAUTH_CLIENT_ID's pattern).
  2. Write a class implementing SmsGateway.send().
  3. Add it to GATEWAYS and point settings.SMS_GATEWAY at its key.
Nothing calling send_sms() needs to change.
"""
import logging

from django.conf import settings

from apps.user.phone import normalize_phone

logger = logging.getLogger(__name__)


class SmsGateway:
    """Interface every SMS provider implements."""

    def send(self, phone_number, message):
        raise NotImplementedError


class LoggingSmsGateway(SmsGateway):
    """No real send -- logs what would have gone out. Same role as
    apps.home.payments.ManualGateway plays for payments."""

    def send(self, phone_number, message):
        logger.info("SMS to %s: %s", phone_number, message)
        return True


GATEWAYS = {
    "logging": LoggingSmsGateway,
}


def get_sms_gateway():
    key = getattr(settings, "SMS_GATEWAY", "logging")
    gateway_class = GATEWAYS.get(key, LoggingSmsGateway)
    return gateway_class()


def send_sms(phone_number, message):
    """Single entry point future callers use. Normalizes the number
    through the project's one shared phone-canonicalization function
    (apps/user/phone.py's normalize_phone) before handing it to the
    gateway -- never re-implemented here, only imported, per that
    module's own "single source of truth" rule."""
    phone_number = normalize_phone(phone_number)
    gateway = get_sms_gateway()
    return gateway.send(phone_number, message)
