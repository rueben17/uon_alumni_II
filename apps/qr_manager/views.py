import secrets

from django.shortcuts import redirect, render

from apps.qr_manager.models import QRCode, ScanLog


def _client_ip(request):
    """First hop of X-Forwarded-For behind nginx, REMOTE_ADDR in dev."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _log(request, qr_code, result):
    ScanLog.objects.create(
        qrcode=qr_code,
        result=result,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )


def verify_scan(request, qr_id):
    """
    Scan → employee profile, via get_absolute_url() — so a complete
    profile opens the slugged detail page and an incomplete one opens
    the UUID fallback page, automatically.

    Validity enforcement (is_valid / expiry / revocation blocking the
    redirect) is deferred by design: the model fields and ScanLog
    already capture everything, so switching it on later is a few
    lines here — no badge ever needs reprinting for it.

    The token check stays even in this simple version: it is what
    makes rotate_token() a real lost-badge lever rather than
    decoration, and it stops guessed UUIDs from resolving.
    """
    qr_code = QRCode.objects.filter(pk=qr_id).select_related("employee").first()

    if qr_code is None or qr_code.employee is None:
        _log(request, qr_code, ScanLog.Result.UNKNOWN)
        return render(request, "qr_manager/scan_invalid.html", status=404)

    supplied = request.GET.get("t", "")
    if not supplied or not secrets.compare_digest(supplied, qr_code.token):
        _log(request, qr_code, ScanLog.Result.BAD_TOKEN)
        return render(request, "qr_manager/scan_invalid.html", status=403)

    _log(request, qr_code, qr_code.status)
    return redirect(qr_code.employee.get_absolute_url())