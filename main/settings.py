"""
Django settings for UON Alumni platform.

Docs: https://docs.djangoproject.com/en/6.0/topics/settings/
Full reference: https://docs.djangoproject.com/en/6.0/ref/settings/

Environment variables required in production (.env or server environment):
  DJANGO_SECRET_KEY            — secret key, never commit this
  DJANGO_DEBUG                 — set to "False" in production (defaults to True)
  ALLOWED_HOSTS                — comma-separated list of allowed hostnames
  DATABASE_URL                 — Neon Postgres connection string
  CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET — media storage
  GOOGLE_OAUTH_CLIENT_ID        — from Google Auth Platform → Clients
  GOOGLE_OAUTH_CLIENT_SECRET    — from Google Auth Platform → Clients
  ALLOWED_GOOGLE_LOGIN_DOMAINS  — comma-separated email domains allowed to
                                  sign in via Google on staff. (defaults to
                                  uonbi.ac.ke)
  ALLOWED_STUDENT_LOGIN_DOMAINS — same, for students. (defaults to
                                  students.uonbi.ac.ke)
  RESTRICT_GOOGLE_LOGIN_DOMAINS — set to "False" to allow any Google account
                                  (for local dev/testing only)
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import dj_database_url

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
SITE_ID = 1

# ─────────────────────────────────────────────
# Core
# ─────────────────────────────────────────────

# Toggle between local dev and production behaviour throughout this file.
# Set DJANGO_DEBUG=False in the production .env or server environment.
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Insecure fallback — only used locally, never in production.
        SECRET_KEY = "@4*qtifwl633i7kbyd6immw^!=+*6!xv#*+9dgg(6suldrof9i"
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY environment variable is required in production"
        )


# ─────────────────────────────────────────────
# Hosts
# ─────────────────────────────────────────────

def split_env_list(value):
    """Parse a comma-separated env var into a clean Python list."""
    return [item.strip() for item in value.split(',') if item.strip()]


if DEBUG:
    # lvh.me is a public wildcard DNS that resolves to 127.0.0.1.
    # The leading dot covers all subdomains: staff.lvh.me, students.lvh.me etc.
    # No /etc/hosts editing needed for local subdomain testing.
    ALLOWED_HOSTS = split_env_list(
        os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,lvh.me,.lvh.me')
    )
else:
    # Pull explicit hosts from env first (e.g. the VPS IP for health checks),
    # then append the domain and wildcard subdomain pattern.
    ALLOWED_HOSTS = split_env_list(os.getenv('ALLOWED_HOSTS', ''))
    ALLOWED_HOSTS += [
        'uonalumni.or.ke',
        'www.uonalumni.or.ke',
        '.uonalumni.or.ke',   # covers staff., students., any future subdomain
    ]
    if not ALLOWED_HOSTS:
        raise RuntimeError(
            'ALLOWED_HOSTS environment variable is required in production'
        )


# ─────────────────────────────────────────────
# Applications
# ─────────────────────────────────────────────

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    # Slug link rot fix (todo.md 0.3b): Article/Event/Chapter slugs no
    # longer auto-update on every title edit, but an editor can still
    # change one manually -- this is what keeps the old URL alive instead
    # of a silent 404. Requires django.contrib.sites (already below).
    'django.contrib.redirects',

    # django-allauth
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',

    # Third-party
    'corsheaders',
    "crispy_forms",
    "crispy_tailwind",
    'widget_tweaks',
    'django_htmx',
    'cloudinary_storage',
    'django_extensions',
    'phonenumber_field',
    'import_export',
    'django_q',

    # Project apps
    'apps.home',
    'apps.user',
    'apps.staff',
    'apps.student',
    'apps.qr_manager',
]

# ─────────────────────────────────────────────
# Phone numbers (todo.md 0.2)
# ─────────────────────────────────────────────
# Storage is E.164 with the leading '+' (+254712345678). Pinned explicitly
# even though E164 is the library default: apps/user/phone.py guarantees a
# byte-identical canonical string, and a silent change to this setting would
# break both the unique constraint and phone-based login. KE is the region
# bare national input ("0712345678") is interpreted against.
PHONENUMBER_DEFAULT_REGION = 'KE'
PHONENUMBER_DEFAULT_FORMAT = 'E164'


# Custom user model — must be set before the first migration.
AUTH_USER_MODEL = 'user.User'


AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# ─────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    # WhiteNoise must come directly after SecurityMiddleware.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # SubdomainRoutingMiddleware sets request.urlconf and request.subdomain.
    # Must be after SessionMiddleware and before CommonMiddleware.
    'allauth.account.middleware.AccountMiddleware',
    'main.middleware.SubdomainRoutingMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Last resort: only triggers on an otherwise-404, so it can't mask a
    # real routing bug. Catches the case a manual slug edit orphans a link.
    'django.contrib.redirects.middleware.RedirectFallbackMiddleware',
]

ROOT_URLCONF = 'main.urls'

# SAMEORIGIN, not the Django default of DENY -- the applicant evaluation
# screen (apps/student/views.py's EvaluateApplicationView) iframes an
# uploaded PDF served from this same site, and DENY blocks that even
# though it's same-origin. Still blocks third-party clickjacking, which
# is the actual protection this setting exists for.
X_FRAME_OPTIONS = 'SAMEORIGIN'

# ─────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.home.context_processors.images',
                'apps.home.context_processors.date_timer',
                'apps.home.context_processors.contacts',
                'apps.home.context_processors.seo',
            ],
            # Registered as a builtin so {% subdomain_url %} is available
            # in every template without {% load subdomain_urls %}.
            'builtins': [
                'apps.home.templatetags.subdomain_urls',
            ],
        },
    },
]

WSGI_APPLICATION = 'main.wsgi.application'


# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

if DEBUG:
    # Local Postgres via DATABASE_URL (see .env) -- 2026-08-18, replaces
    # the old USE_NEON_LOCALLY escape hatch now that local dev has its own
    # Postgres instance instead of pointing at production. Falls back to
    # SQLite when DATABASE_URL isn't set, so a fresh checkout still works
    # with zero DB setup.
    _db_url = os.getenv('DATABASE_URL')
    if _db_url:
        DATABASES = {
            'default': dj_database_url.parse(
                _db_url, conn_max_age=600, conn_health_checks=True
            )
        }
    else:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }
else:
    # Neon Postgres in production via DATABASE_URL.
    # conn_max_age=600 keeps connections alive for 10 minutes (connection
    # pooling). conn_health_checks=True: Neon's serverless compute can
    # auto-suspend and close idle connections server-side; without this,
    # the next request to reuse a stale pooled connection dies with
    # "SSL connection has been closed unexpectedly" instead of silently
    # reconnecting.
    _db_url = os.getenv('DATABASE_URL')
    if not _db_url:
        raise RuntimeError(
            'DATABASE_URL environment variable is required in production'
        )
    DATABASES = {
        'default': dj_database_url.parse(
            _db_url, conn_max_age=600, conn_health_checks=True
        )
    }
    # DATABASE_URL's host is Neon's pooled endpoint (confirmed:
    # ...-pooler.<region>.aws.neon.tech), which hands out connections
    # PgBouncer-transaction-pooling-style -- a named/server-side cursor
    # opened on one physical connection can silently stop existing if
    # the pooler reassigns a different one mid-request, surfacing as
    # psycopg2.errors.InvalidCursorName ("cursor ... does not exist"),
    # confirmed live in production (2026-08-27, admin change-page
    # dropdown rendering). This is Django's own documented mitigation
    # for exactly this class of pooler: server-side cursors are never
    # safe against a transaction-pooled connection, regardless of how
    # small/optimized the query is, so this closes the failure mode
    # everywhere at once rather than per-queryset.
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True


# ─────────────────────────────────────────────
# Task queue (Django Q2)
# ─────────────────────────────────────────────

# ORM broker, not Redis -- deliberate 2026-08-18 decision, do not revisit
# without re-checking the reasoning below. Redis would mean a second
# process to install/monitor/keep alive on the VPS for no real gain here;
# the ORM broker needs nothing beyond the database connection this project
# already has. The one real cost is 'poll' below -- see its own comment.
Q_CLUSTER = {
    'name': 'uon_alumni',
    'orm': 'default',
    'workers': 2,
    'timeout': 90,
    # Must stay > timeout, or Q2 requeues a task before it could ever
    # finish. Two full timeout-lengths of headroom, not just one.
    'retry': 120,
    # ORM broker default is 0.2s -- confirmed via the Django Q2 docs,
    # not assumed -- which is ~5 queries/second/worker against the
    # database, continuously, forever. Fine on a normal self-hosted
    # Postgres; a real, avoidable cost on Neon specifically, which is
    # serverless (connection ceiling, usage-based billing) -- this
    # project's DB is still on Neon as of 2026-08-18, moving to the VPS
    # itself later (separate, already-decided task). Nothing queued here
    # (email/SMS/profile creation/newsletter, once migrated) is
    # sub-second-latency-sensitive, so 10s cuts that load by ~98% for
    # however long the DB stays on Neon. Safe to lower once it doesn't.
    'poll': 10,
    'save_limit': 250,
    'label': 'Task Queue',
    # Default is 0 (unlimited) -- a permanently-failing task (e.g. a
    # malformed recipient address) would otherwise requeue itself every
    # `retry` seconds forever. 5 gives real transient failures (a flaky
    # SMTP connection, a momentary DB blip) room to clear before Q2 stops
    # retrying and the failure just sits in EmailLog.error / the Failure
    # admin for a human to see.
    'max_attempts': 5,
}


# ─────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────

# Console backend (2026-08-18) -- no EMAIL_BACKEND existed at all before
# this; the one pre-existing send_mail() call site (contact-form
# notification, apps/home/views.py) was silently failing against
# Django's own default (smtp to localhost:25, nothing listening there).
# This writes the email to stdout instead of sending it, same
# "real pipeline, stub destination" shape as apps/home/payments.py's
# ManualGateway -- swap in real SMTP settings later, no code change
# needed anywhere that calls send_mail().
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'UoN Alumni Association <noreply@uonalumni.or.ke>'


# ─────────────────────────────────────────────
# SMS
# ─────────────────────────────────────────────

# 'whatsapp' (apps/home/sms.py's WhatsAppGateway) -- provider decided
# 2026-09-04 (docs/todo.md 0.4), still a logging stub: sending needs a
# verified Meta Business/WhatsApp Business Account and an approved
# Authentication template, neither of which exists yet, and the
# Association cost conversation still has to happen. Switch this one key
# once WhatsAppGateway.send() has a real implementation -- nothing
# calling send_sms() needs to change.
SMS_GATEWAY = 'whatsapp'


# ─────────────────────────────────────────────
# Password validation
# ─────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ─────────────────────────────────────────────
# Internationalisation
# ─────────────────────────────────────────────

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True


# ─────────────────────────────────────────────
# Static and media files
# ─────────────────────────────────────────────

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# STORAGES is the ONLY storage form Django reads from 5.1 onwards.
# STATICFILES_STORAGE and DEFAULT_FILE_STORAGE used to live here and were
# removed in 5.1 -- Django 5.2 ignores them silently, with no warning, so
# Cloudinary was fully configured and never actually used and WhiteNoise's
# static backend was inert. Deleted rather than left beside this dict:
# dead settings that still read as authoritative are how that went
# unnoticed. See docs/finding-L-storage-design-2026-09-03.md.
#
# Cloudinary unconditionally, both environments (2026-09-04, Association
# decision) -- media is Cloudinary everywhere, full stop, matching how
# every other project here already runs it, not a per-environment
# fallback. Nothing conditional on CLOUDINARY_CLOUD_NAME any more: local
# dev's .env already carries the same credentials as production (same
# Cloudinary account), and apps/home/models.py's RawMediaCloudinaryStorage
# import (Publication.file) has always required them to even be able to
# boot regardless -- a conditional default here was never actually
# optional in practice, just quieter about it. Test isolation is
# unaffected: every test that writes media already forces
# override_settings(STORAGES=LOCAL_STORAGES) itself (see
# apps/qr_manager/tests.py's and apps/home/tests.py's own LOCAL_STORAGES),
# which overrides this default regardless of what it says.
#
# staticfiles uses CompressedStaticFilesStorage, not the Manifest variant:
# the manifest backend raises at template-render time for any {% static %}
# reference missing from the manifest, so a skipped or failed collectstatic
# becomes a 500 on every page using that asset. Compression now, hashing
# as a later deliberate change.
STORAGES = {
    'default': {'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY', ''),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', ''),
}


# ─────────────────────────────────────────────
# Forms
# ─────────────────────────────────────────────

CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"

CRISPY_TEMPLATE_PACK = "tailwind"


# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────

if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    # Restrict CORS to known origins in production.
    # Add subdomain origins here if staff/student apps make cross-origin requests.
    CORS_ALLOWED_ORIGINS = [
        'https://uonalumni.or.ke',
        'https://www.uonalumni.or.ke',
        'https://staff.uonalumni.or.ke',
        'https://students.uonalumni.or.ke',
    ]


# ─────────────────────────────────────────────
# Subdomain routing
# ─────────────────────────────────────────────

# SUBDOMAIN_DOMAIN is the base domain the middleware strips subdomains from.
# SUBDOMAIN_URLCONFS maps each subdomain to its urlconf module.
# None key = no subdomain (bare domain or www).
# Used by: main/middleware.py and apps/home/templatetags/subdomain_urls.py

if DEBUG:
    SUBDOMAIN_DOMAIN = 'lvh.me'
    SUBDOMAIN_URLCONFS = {
        None:       'main.urls',
        'www':      'main.urls',
        'staff':    'apps.staff.site_urls',
        'students': 'apps.student.site_urls',
    }
else:
    SUBDOMAIN_DOMAIN = 'uonalumni.or.ke'
    SUBDOMAIN_URLCONFS = {
        None:       'main.urls',
        'www':      'main.urls',
        'staff':    'apps.staff.site_urls',
        'students': 'apps.student.site_urls',
    }


# Origin encoded into printed QR badges, keyed by holder type -- an
# alumni's badge must never read "staff." in the URL bar (that was the
# bug: a single QR_SCAN_ORIGIN hardcoded to the staff subdomain was used
# for every badge, staff and alumni alike). Explicit rather than derived
# from DEBUG: a QR is a permanent artifact, so the URL it carries must
# never depend on what mode the generating process happened to run in.
# See QRCode.scan_url (apps/qr_manager/models.py) for which key each
# holder type uses. Only staff/alumni exist as QR holder types today
# (QRCode has no student FK) -- add a 'student' key here alongside a
# matching holder-type branch in scan_url() if that's ever built.
if DEBUG:
    QR_SCAN_ORIGINS = {
        'staff': os.getenv('QR_SCAN_ORIGIN_STAFF', 'http://staff.lvh.me:8000'),
        'alumni': os.getenv('QR_SCAN_ORIGIN_ALUMNI', 'http://www.lvh.me:8000'),
    }
else:
    QR_SCAN_ORIGINS = {
        'staff': os.getenv('QR_SCAN_ORIGIN_STAFF', 'https://staff.uonalumni.or.ke'),
        'alumni': os.getenv('QR_SCAN_ORIGIN_ALUMNI', 'https://www.uonalumni.or.ke'),
    }

    
# ─────────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────────
#
# Google OAuth (via django-allauth) is the ONLY auth method, and the
# /accounts/ paths are shared across all subdomains: the middleware
# keeps them on ROOT_URLCONF, so the same login/logout URLs work on
# uonalumni.or.ke, staff., and students. alike.
#
# Post-login routing lives in apps/user/adapter.py:
#   - login on staff.    → Employee ensured → complete_profile or detail page
#   - login on students. → Student ensured  → (when apps.student is built)
#   - logout (anywhere)  → main site home page

# Where @login_required sends anonymous users.
# This lands on the local login page, which presents the Google
# social auth option instead of bypassing straight to Google.
LOGIN_URL = '/accounts/login/'

# Fallback redirect after login, used only when the adapter's
# get_login_redirect_url() doesn't return a subdomain-specific URL
# (i.e. logins on the main domain).
LOGIN_REDIRECT_URL = '/'

# Logout redirect is handled by CustomAccountAdapter.get_logout_redirect_url()
# (always the main site home page), so no setting is needed here.
LOGOUT_REDIRECT_URL = None

# ----- django-allauth core -----

# Google-only auth: no usernames, email is the identifier, and Google
# has already verified the address (checked in the adapter), so
# allauth's own email verification is off.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*']
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = 'none'

# ----- django-allauth social -----

# Skip the intermediate signup form and create the account directly
# from the Google profile.
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'

# If the Google email matches an existing User, log into that account
# and auto-connect the social account instead of showing the signup
# form (the ACCOUNT_UNIQUE_EMAIL conflict case). Safe regardless of
# domain restriction below -- it's Google's own OAuth verification that
# guarantees the requester owns this exact email, not which domain it's on.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Email domains allowed to sign in via Google -- enforced in
# apps/user/adapter.py's pre_social_login(), staff subdomain ONLY. Staff
# identity is verified via an institutional email, so this stays
# meaningful there. The main subdomain accepts any Google account: most
# alumni lose @uonbi.ac.ke access at graduation, so gating the public
# alumni site the same way just blocks ordinary registration.
# A list, not a single domain (2026-08-14): UoN staff aren't only issued
# bare @uonbi.ac.ke addresses -- unes.uonbi.ac.ke (University of Nairobi
# Enterprises & Services) and alumni.uonbi.ac.ke are real UoN-issued
# domains too. Add more to the env var as they come up -- no code change
# needed, just update .env and redeploy.
ALLOWED_GOOGLE_LOGIN_DOMAINS = split_env_list(
    os.getenv('ALLOWED_GOOGLE_LOGIN_DOMAINS', 'uonbi.ac.ke,unes.uonbi.ac.ke,alumni.uonbi.ac.ke')
)

# Same idea, students subdomain -- currently-enrolled students sign in
# with their @students.uonbi.ac.ke Google Workspace account, not a
# personal one (2026-08-14, scholarship-page access gate).
ALLOWED_STUDENT_LOGIN_DOMAINS = split_env_list(
    os.getenv('ALLOWED_STUDENT_LOGIN_DOMAINS', 'students.uonbi.ac.ke')
)

# Toggle the staff/students-subdomain domain restrictions for local
# development/testing. Set RESTRICT_GOOGLE_LOGIN_DOMAINS=False in .env to
# allow any Google account onto staff/students too (main already does,
# always).
RESTRICT_GOOGLE_LOGIN_DOMAINS = os.getenv(
    'RESTRICT_GOOGLE_LOGIN_DOMAINS', 'True'
).strip().lower() in ('true', '1', 'yes')

# ----- Google provider -----

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {
            'access_type': 'online',
            # Force Google's consent page so users explicitly see
            # and approve the data-sharing screen before account selection.
            'prompt': 'consent select_account',
        },
        'FETCH_USERINFO': True,
        'APP': {
            'client_id': os.getenv('GOOGLE_OAUTH_CLIENT_ID'),
            'secret': os.getenv('GOOGLE_OAUTH_CLIENT_SECRET'),
        },
    }
}

# ----- Custom adapters (redirects + Employee/Student creation) -----

ACCOUNT_ADAPTER = 'apps.user.adapter.CustomAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'apps.user.adapter.CustomSocialAccountAdapter'
# ─────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────

# Trust the X-Forwarded-Proto header set by Nginx/the load balancer.
# This tells Django the original request was HTTPS even though Gunicorn
# receives it as HTTP internally.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if not DEBUG:
    SESSION_COOKIE_SECURE = True          # session cookie only sent over HTTPS
    CSRF_COOKIE_SECURE = True             # CSRF cookie only sent over HTTPS
    SECURE_SSL_REDIRECT = True            # redirect all HTTP → HTTPS
    PREPEND_WWW = False                   # don't force www prefix
    SECURE_HSTS_SECONDS = 31536000        # 1 year HSTS
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True # HSTS covers staff., students. etc.
    SECURE_HSTS_PRELOAD = True            # eligible for browser preload lists
    SECURE_BROWSER_XSS_FILTER = True      # legacy XSS header (still useful)
    SECURE_CONTENT_TYPE_NOSNIFF = True    # prevent MIME sniffing
else:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False

# Share the session/CSRF cookies across every subdomain (staff., students.,
# www., bare domain) so one login on the main site is recognised on the
# staff/students subdomains too. Without this, Django scopes the cookie to
# the exact host that set it, so hopping subdomains always looks like a
# brand-new anonymous visit and forces a fresh Google login every time.
# Dev note: this means testing must use a *.lvh.me:8000 host — a cookie
# scoped to ".lvh.me" is invalid (and silently dropped by the browser) on
# a host like bare "localhost" that isn't a subdomain of it.
SESSION_COOKIE_DOMAIN = f".{SUBDOMAIN_DOMAIN}"
CSRF_COOKIE_DOMAIN = f".{SUBDOMAIN_DOMAIN}"


# ─────────────────────────────────────────────
# CSRF trusted origins
# ─────────────────────────────────────────────

# Django 4+ requires the full origin (scheme + host) to be listed here
# for any POST request that isn't same-origin — this includes HTMX requests
# coming from a subdomain to the main domain and vice versa.

CSRF_TRUSTED_ORIGINS = [
    'https://uonalumni.or.ke',
    'https://www.uonalumni.or.ke',
    'https://staff.uonalumni.or.ke',
    'https://students.uonalumni.or.ke',
]

if DEBUG:
    CSRF_TRUSTED_ORIGINS += [
        'http://lvh.me:8000',
        'http://www.lvh.me:8000',
        'http://staff.lvh.me:8000',
        'http://students.lvh.me:8000',
    ]


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
#
# Unhandled view exceptions (500s) are only sent to Django's default
# mail_admins handler when DEBUG=False, which does nothing here (no
# ADMINS/email backend configured), so they vanish silently. This makes
# them print to stderr instead, which systemd/gunicorn captures into
# journalctl -u uon_alumni.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}


# ─────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_THOUSAND_SEPARATOR = True