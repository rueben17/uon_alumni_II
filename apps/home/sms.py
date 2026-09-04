# apps/home/sms.py
"""
Phone-message gateway integration point -- mirrors apps/home/payments.py's
shape. Named sms.py for history (it started as an SMS-only pipe); the
channel it actually sends over is WhatsApp as of the 2026-09-04 decision
below.

No real provider credentials exist yet -- this module is the single place
a real integration plugs into later. Every send currently routes to
WhatsAppGateway, which just logs the message instead of sending it.

Provider decided 2026-09-04 (docs/todo.md 0.4): WhatsApp (Meta Business
Cloud API), not SMS -- Kenya's "Authentication" template category prices
at roughly KES 0.50/message delivered, cheaper than a typical SMS
gateway, for the same OTP use case this module exists for. Still not
wired to anything real: sending needs (1) a verified Meta Business/
WhatsApp Business Account and (2) Meta's approval of the Authentication
template itself, neither of which exists yet, and the Association cost
conversation still has to happen even at this smaller number. This
module -- and the Q2 task wrapping it (apps/home/tasks.py's dispatch_sms)
-- exist so the pipe is ready the moment both resolve.

To add the real Meta integration later:
  1. Add WHATSAPP_* credentials to settings (mirroring GOOGLE_OAUTH_CLIENT_ID's
     pattern) -- phone number ID, access token, the approved template name.
  2. Implement WhatsAppGateway.send() for real (Meta Cloud API POST to
     /messages, using the Authentication template).
  3. Nothing calling send_sms() needs to change.
"""
import logging

from django.conf import settings

from apps.user.phone import normalize_phone

logger = logging.getLogger(__name__)


class SmsGateway:
    """Interface every phone-message provider implements, whatever the
    actual channel underneath (SMS, WhatsApp, ...)."""

    def send(self, phone_number, message):
        raise NotImplementedError


class LoggingSmsGateway(SmsGateway):
    """No real send -- logs what would have gone out. Same role as
    apps.home.payments.ManualGateway plays for payments."""

    def send(self, phone_number, message):
        logger.info("SMS to %s: %s", phone_number, message)
        return True


class WhatsAppGateway(SmsGateway):
    """The decided channel (2026-09-04, see this module's docstring) --
    still a logging stub, same as LoggingSmsGateway, until the Meta
    Business/WhatsApp Business Account and Authentication template both
    exist. Kept as its own class rather than reusing LoggingSmsGateway
    directly so the real Meta Cloud API call has exactly one place to
    land later, and so GATEWAYS/SMS_GATEWAY below say what channel is
    actually intended, not just "no-op"."""

    def send(self, phone_number, message):
        logger.info("WhatsApp to %s: %s", phone_number, message)
        return True


GATEWAYS = {
    "logging": LoggingSmsGateway,
    "whatsapp": WhatsAppGateway,
}


def get_sms_gateway():
    key = getattr(settings, "SMS_GATEWAY", "whatsapp")
    gateway_class = GATEWAYS.get(key, WhatsAppGateway)
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
