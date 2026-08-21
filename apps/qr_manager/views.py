import secrets

from django.shortcuts import redirect, render
from django.utils import timezone

from apps.home.models import Membership
from apps.qr_manager.models import QRCode, ScanLog
from apps.qr_manager.utils import humanize_duration


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


def _render_noindex(request, template_name, context=None, status=None):
    """render() wrapper that sets X-Robots-Tag itself (2026-08-21) --
    both qr_manager templates already carry a <meta name="robots"
    content="noindex"> tag, but that's presentation-layer only and
    depends on the template rendering exactly as intended (a multi-line
    {# #} comment silently breaking that same tag, found and fixed the
    same day, is live proof it can't be trusted alone for a page that
    exposes a real member's name and standing). The HTTP header is set
    here in code, so it holds even if the template ever changes again."""
    response = render(request, template_name, context, status=status)
    response["X-Robots-Tag"] = "noindex"
    return response


def _alumni_verification_context(alumni_profile):
    """Everything the public alumni verification page shows -- all read
    live from the database at request time (2026-08-14), nothing
    cached, stored, or derived from the QR payload itself.

    Tier is shown as its coarse category (MembershipTier.tier_type's
    display, e.g. "Life Member"), not the specific named tier -- the
    named tier reveals roughly what was paid (the fee table on the
    public Categories & Benefits page), which the exact tier name would
    expose to anyone holding the badge; the category confirms standing
    without that (decided with the user, 2026-08-14).

    membership (2026-08-21): looked up directly by status=ACTIVE rather
    than via Membership.objects.current_for() -- that manager method
    deliberately returns the most-recently-CREATED row regardless of
    status (see its own docstring; apps/home/views.py:865 documents the
    same ambiguity), which is right for showing "you have a renewal
    pending" elsewhere but wrong here: a member with a still-valid
    ACTIVE membership who has since started a renewal (a new PENDING
    row) would otherwise show as "Not currently valid" on this public
    page even though their badge is still genuinely good.
    """
    membership = Membership.objects.filter(
        user=alumni_profile.user, status=Membership.Status.ACTIVE
    ).order_by("-created_at").first()

    tier_category = membership.tier.get_tier_type_display() if membership else None

    if membership is None:
        validity_label = "Not currently valid"
    elif not membership.is_valid:
        if membership.expires_on and not membership.is_lifetime:
            validity_label = f"Expired on {membership.expires_on:%d %b %Y}"
        else:
            validity_label = "Not currently valid"
    elif membership.is_lifetime:
        validity_label = "Life member"
    else:
        validity_label = "Valid"

    # registration_date is auto_now_add=True (never null through normal
    # signup), but defended here anyway -- a bulk-imported/legacy row
    # could still land with it unset, and this page must not 500 for one.
    signup = alumni_profile.registration_date
    member_since = timezone.localtime(signup).strftime("%B %Y") if signup else None
    duration = humanize_duration(signup, timezone.now()) if signup else None

    return {
        "display_name": alumni_profile.user.profile.display_name,
        "tier_category": tier_category,
        "validity_label": validity_label,
        "member_since": member_since,
        "duration": duration,
    }


def verify_scan(request, qr_id):
    """
    Scan → holder verification.

    Employee: unchanged -- redirects to get_absolute_url() (the full
    staff profile page), exactly as before this pass.

    AlumniProfile (2026-08-14): renders a dedicated, minimal public
    verification page directly instead of redirecting to the full
    alumni_detail.html profile -- that page carries owner-only content
    (payment history, edit/manage/deactivate actions) with nothing
    appropriate to show an anonymous badge-holder. See
    _alumni_verification_context() for exactly what's shown and why.

    Validity enforcement (is_valid / expiry / revocation blocking the
    scan itself) is deferred by design, same as before: the model
    fields and ScanLog already capture everything, so switching it on
    later is a few lines here — no badge ever needs reprinting for it.

    The token check stays even in this simple version: it is what
    makes rotate_token() a real lost-badge lever rather than
    decoration, and it stops guessed UUIDs from resolving.
    """
    qr_code = QRCode.objects.filter(pk=qr_id).select_related("employee", "alumni_profile").first()

    if qr_code is None or qr_code.holder is None:
        _log(request, qr_code, ScanLog.Result.UNKNOWN)
        return _render_noindex(request, "qr_manager/scan_invalid.html", status=404)

    supplied = request.GET.get("t", "")
    if not supplied or not secrets.compare_digest(supplied, qr_code.token):
        _log(request, qr_code, ScanLog.Result.BAD_TOKEN)
        return _render_noindex(request, "qr_manager/scan_invalid.html", status=403)

    _log(request, qr_code, qr_code.status)

    if qr_code.alumni_profile_id:
        return _render_noindex(
            request, "qr_manager/alumni_verify.html", _alumni_verification_context(qr_code.alumni_profile)
        )

    return redirect(qr_code.holder.get_absolute_url())