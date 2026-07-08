import logging

from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.qr_manager.models import QRCode
from apps.staff.models import Employee

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Employee)
def create_or_update_qrcode(sender, instance, created, **kwargs):
    """Create a QRCode if missing and regenerate whenever the employee
    is saved, so the badge always exists without anyone clicking
    anything. Cache-based flag prevents infinite recursion when the
    QR generation saves the employee record.

    Compatibility edits vs the original (only these):
      - signed_token → token, and no defaults needed: QRCode.save()
        assigns a token automatically on creation.
      - skip the echo save (update_fields == {qr_code_image}) as a
        fast-path before touching the cache.
    """
    # The save generate_qr() itself performs — nothing to do.
    update_fields = kwargs.get("update_fields")
    if update_fields and set(update_fields) == {"qr_code_image"}:
        return

    qr_gen_key = f"qr_generating_{instance.pk}"

    if cache.get(qr_gen_key):
        return

    try:
        cache.set(qr_gen_key, True, 10)

        qr, _ = QRCode.objects.get_or_create(employee=instance)

        # force=True: always regenerate so the image reflects the
        # current token; save_employee=True persists the field.
        qr.generate_qr(force=True, save_employee=True)

    except Exception as e:
        logger.error(
            f"Failed to generate QR code for employee {instance.pk}: {e}",
            exc_info=True,
        )
    finally:
        cache.delete(qr_gen_key)