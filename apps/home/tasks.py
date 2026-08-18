# apps/home/tasks.py
"""
Django Q2 task functions. Take primitives only -- IDs and strings, never
a model instance, queryset, request, or file object -- so every task is
safely picklable for the ORM broker and re-runnable regardless of what
changed in the database between enqueue and execution.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management import call_command
from django.utils import timezone


def send_alumni_registration_confirmation(alumni_profile_id):
    """Sends the welcome/confirmation email once an AlumniProfile has been
    created (apps.home.views.AlumniRegisterView.form_valid). Idempotent via
    EmailLog's UniqueConstraint on (email_type, related_object_id): a
    second call for the same alumni_profile_id is a no-op once sent_at is
    set. On failure the error is recorded and the exception re-raised so
    Q2's own max_attempts retries it -- never swallowed here.
    """
    from apps.home.models import AlumniProfile, EmailLog

    log, _created = EmailLog.objects.get_or_create(
        email_type=EmailLog.EmailType.ALUMNI_REGISTRATION_CONFIRMATION,
        related_object_id=str(alumni_profile_id),
    )
    if log.sent_at is not None:
        return

    try:
        alumni = AlumniProfile.objects.select_related("user", "user__profile").get(pk=alumni_profile_id)
        recipient = alumni.user.email
        send_mail(
            subject="Welcome to the University of Nairobi Alumni Association",
            message=(
                f"Dear {alumni.user.profile.given_name},\n\n"
                "Thank you for registering with the University of Nairobi "
                "Alumni Association. Your profile has been created "
                "successfully and your membership application is now "
                "being processed.\n\n"
                "We look forward to keeping you connected with the UoN "
                "alumni community.\n\n"
                "Regards,\nUoN Alumni Association"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception as exc:
        log.error = str(exc)
        log.save(update_fields=["error"])
        raise

    log.recipient_email = recipient
    log.sent_at = timezone.now()
    log.error = ""
    log.save(update_fields=["recipient_email", "sent_at", "error"])


def expire_lapsed_installment_plans():
    """Proof task for the Q2 cluster itself (2026-08-18). Wraps the
    existing, already-idempotent management command
    (apps/home/management/commands/expire_lapsed_installment_plans.py)
    rather than duplicating its query logic here -- that command already
    does the real work and was already tested on its own.

    Registered as a daily Schedule via
    /2005/admin/django_q/schedule/add/ (func:
    "apps.home.tasks.expire_lapsed_installment_plans") -- not created
    programmatically here, since Q2's own admin (auto-registered once
    'django_q' is in INSTALLED_APPS) already manages Schedule rows, and
    this is a one-time setup action, not recurring data.
    """
    call_command("expire_lapsed_installment_plans")
