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


def send_newsletter_email(publication_id, user_id):
    """Sends one newsletter-announcement email to one recipient. Called
    once per opted-in alumnus (apps.home.admin.PublicationAdmin's "Send by
    email" action fans out one of these per recipient -- never one task
    looping over the whole recipient list, so a single bad address can't
    block or slow down the rest of the batch). Idempotent via EmailLog's
    UniqueConstraint on (email_type, related_object_id), where
    related_object_id is "{publication_id}:{user_id}" -- rerunning the
    admin action on the same Publication is a no-op for anyone already
    sent to.
    """
    from django.urls import reverse

    from apps.home.models import EmailLog, Publication
    from apps.user.models import User

    log, _created = EmailLog.objects.get_or_create(
        email_type=EmailLog.EmailType.NEWSLETTER_ANNOUNCEMENT,
        related_object_id=f"{publication_id}:{user_id}",
    )
    if log.sent_at is not None:
        return

    try:
        publication = Publication.objects.get(pk=publication_id)
        user = User.objects.select_related("profile").get(pk=user_id)
        recipient = user.email

        # Same base-URL pattern as apps/home/context_processors.py's
        # home_url() -- a background task has no request to build an
        # absolute URL from, so the production/dev domain is picked the
        # same way that context processor already does.
        base = 'http://lvh.me:8000' if settings.DEBUG else 'https://uonalumni.or.ke'
        downloads_url = base + reverse("home:uon_alumni_downloads", urlconf="main.urls") + "?category=newsletter"

        send_mail(
            subject=f"New newsletter: {publication.title}",
            message=(
                f"Dear {user.profile.given_name},\n\n"
                f"A new issue of the UoN Alumni Association newsletter is "
                f"now available: \"{publication.title}\" ({publication.document_date}).\n\n"
                f"Read it here: {downloads_url}\n\n"
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


def send_profile_claim_otp_email(claim_id, raw_code):
    """Sends the "find my profile" verification code to the address ON
    FILE for the matched user (claim.user.email) -- never to whatever the
    visitor typed into the search form. Not wrapped in EmailLog's
    per-object idempotency: unlike a registration confirmation, a resend
    here is legitimate (the visitor may request a new code), so the
    ProfileClaimVerification row's own status/attempts is this flow's
    idempotency instead. On failure the exception is re-raised, never
    swallowed, so Q2 retries.
    """
    from apps.home.models import ProfileClaimVerification

    claim = ProfileClaimVerification.objects.select_related("user__profile").get(pk=claim_id)
    if claim.user_id is None:
        return  # bookkeeping-only row for a non-match -- nothing to send

    recipient = claim.user.email
    send_mail(
        subject="Your UoN Alumni Association verification code",
        message=(
            f"Dear {claim.user.profile.given_name},\n\n"
            f"Your verification code is: {raw_code}\n\n"
            f"This code expires in {claim.OTP_EXPIRY_MINUTES} minutes. "
            "If you didn't request this, you can safely ignore this email.\n\n"
            "Regards,\nUoN Alumni Association"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )


def send_profile_claim_otp_phone(claim_id, raw_code):
    """Phone twin of send_profile_claim_otp_email() above (2026-09-04) --
    same shape, same reasoning: sends to claim.user.phone (the number ON
    FILE), not whatever the visitor typed, and the ProfileClaimVerification
    row's own status/attempts is the idempotency, not a delivery log, since
    a resend here is legitimate. Goes straight to send_sms(), not through
    dispatch_sms() above -- this caller already has a real business object
    to reason about (the claim row), which is exactly why
    send_profile_claim_otp_email() doesn't route through a generic
    send-an-email primitive either.
    """
    from apps.home.models import ProfileClaimVerification
    from apps.home.sms import send_sms

    claim = ProfileClaimVerification.objects.select_related("user__profile").get(pk=claim_id)
    if claim.user_id is None:
        return  # bookkeeping-only row for a non-match -- nothing to send

    send_sms(
        claim.user.phone,
        (
            f"UoN Alumni Association: your verification code is {raw_code}. "
            f"It expires in {claim.OTP_EXPIRY_MINUTES} minutes. "
            "If you didn't request this, you can ignore this message."
        ),
    )


def dispatch_sms(phone_number, message):
    """Q2 wrapper around apps.home.sms.send_sms() -- primitives only, a
    phone number and message string. Not wired to any real trigger yet
    (see apps/home/sms.py's own docstring for why) -- exercised directly
    for now, the same role expire_lapsed_installment_plans below played
    for the Q2 cluster itself before any real workload existed. No
    delivery-log/idempotency here: unlike EmailLog's callers, there's no
    real business object yet to key idempotency off of -- that shape
    should come from whatever the first real caller turns out to be,
    same as EmailLog's did.
    """
    from apps.home.sms import send_sms

    send_sms(phone_number, message)


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
