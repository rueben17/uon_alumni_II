# apps/student/tasks.py
"""
Django Q2 task functions for apps.student. Take primitives only -- IDs and
strings, never a model instance, queryset, request, or file object -- same
convention as apps.home.tasks.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone


def send_evaluation_receipt(score_sheet_id):
    """Sends a receipt-style confirmation to the EVALUATOR (not the
    applicant) once an InterviewScoreSheet has been recorded
    (apps.student.views.EvaluateApplicationView.post) -- confirms their
    score sheet was saved, deliberately says nothing about the outcome to
    avoid premature disclosure of results to the applicant. Idempotent via
    EmailLog's UniqueConstraint on (email_type, related_object_id).
    """
    from apps.home.models import EmailLog
    from apps.student.models import InterviewScoreSheet

    log, _created = EmailLog.objects.get_or_create(
        email_type=EmailLog.EmailType.EVALUATION_RECEIPT,
        related_object_id=str(score_sheet_id),
    )
    if log.sent_at is not None:
        return

    try:
        sheet = InterviewScoreSheet.objects.select_related(
            "evaluator__user", "evaluator__user__profile", "application"
        ).get(pk=score_sheet_id)
        recipient = sheet.evaluator.user.email
        send_mail(
            subject="Interview score sheet recorded",
            message=(
                f"Dear {sheet.evaluator.user.profile.given_name},\n\n"
                f"This confirms your interview score sheet for "
                f"{sheet.application} was recorded on "
                f"{sheet.interview_date}. Total score: {sheet.total_score}/50.\n\n"
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
