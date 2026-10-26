# apps/home/branding.py
"""
Shared branding helpers for the branded HTML emails in apps/home/tasks.py
(templates/emails/). PDF documents (apps/home/pdf_documents.py) have
their own constants -- different rendering context, different formatting
needs -- but both ultimately read the same settings.UONAA_* values as
their single source of truth.
"""
from pathlib import Path
from urllib.parse import quote

from django.conf import settings

_BADGES_DIR = Path(settings.BASE_DIR) / "static" / "images" / "badges"


def site_base_url():
    """Same base-URL pattern apps.home.tasks.send_newsletter_email and
    apps.home.context_processors.home_url() already use -- a background
    task has no request to build an absolute URL from, so the
    production/dev domain is picked the same way either does."""
    return 'http://lvh.me:8000' if settings.DEBUG else 'https://uonalumni.or.ke'


def static_image_url(relative_path):
    """Builds an absolute URL to a static image for use in an email (a
    mail client fetches images over HTTP -- a relative /static/... path,
    which is all {% static %} normally gives, means nothing to it).
    Safe to construct by hand: STORAGES['staticfiles'] is
    whitenoise.storage.CompressedStaticFilesStorage (main/settings.py),
    not the Manifest variant, so filenames are never content-hashed.
    quote() with safe="/" percent-encodes spaces (e.g. the crest's own
    "UoN CREST_new-01.png") without touching the path separators."""
    return f"{site_base_url()}{settings.STATIC_URL}images/{quote(relative_path, safe='/')}"


def email_branding_context():
    """The dict every templates/emails/*.html template needs for its
    shared header/signature block. Badge/crest-seal URLs are None (the
    template omits that <img> entirely) until the real file exists --
    same graceful-omission pattern as pdf_documents.py's signature/stamp
    images. badge_crest_url is the Association's own circular seal (cropped
    from the user-supplied media/google_auth/email.jpg, 2026-10-27) used
    in the signature's badge row -- distinct from crest_url, the
    University crest used in the header, which this doesn't replace."""
    badge_50 = _BADGES_DIR / "50th_anniversary.png"
    badge_20 = _BADGES_DIR / "20th_anniversary.png"
    badge_crest = _BADGES_DIR / "uonaa_crest.png"
    return {
        "website_url": settings.UONAA_WEBSITE_URL,
        "contact_email": settings.UONAA_CONTACT_EMAIL,
        "facebook_url": settings.UONAA_FACEBOOK_URL,
        "linkedin_url": settings.UONAA_LINKEDIN_URL,
        "twitter_url": settings.UONAA_TWITTER_URL,
        "whatsapp_url": settings.UONAA_WHATSAPP_URL,
        "crest_url": static_image_url("UoN CREST_new-01.png"),
        "badge_50_url": static_image_url("badges/50th_anniversary.png") if badge_50.exists() else None,
        "badge_20_url": static_image_url("badges/20th_anniversary.png") if badge_20.exists() else None,
        "badge_crest_url": static_image_url("badges/uonaa_crest.png") if badge_crest.exists() else None,
    }
