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
                                  sign in via Google (defaults to uonbi.ac.ke)
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

    # Project apps
    'apps.home',
    'apps.user',
    'apps.staff',
    'apps.student',
    'apps.qr_manager',
]

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
]

ROOT_URLCONF = 'main.urls'


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
    # USE_NEON_LOCALLY is a temporary, manual escape hatch — set it in your
    # local .env when you specifically want to test against the production
    # Neon DB while keeping DEBUG=True (avoids ALLOWED_HOSTS/SSL issues on
    # lvh.me). Remove this block and the env var once testing is done.
    if os.getenv('USE_NEON_LOCALLY', 'False').lower() in ('true', '1', 'yes'):
        _db_url = os.getenv('DATABASE_URL')
        if not _db_url:
            raise RuntimeError(
                'DATABASE_URL is required when USE_NEON_LOCALLY is set'
            )
        DATABASES = {
            'default': dj_database_url.parse(
                _db_url, conn_max_age=600, conn_health_checks=True
            )
        }
    else:
        # SQLite for local development — no setup required.
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

# WhiteNoise compresses and fingerprints static files for efficient serving.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Cloudinary handles user-uploaded media in production.
# Falls back to local filesystem when CLOUDINARY_CLOUD_NAME is not set (local dev).
if os.environ.get('CLOUDINARY_CLOUD_NAME'):
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
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
        'students': 'apps.student.urls',
    }
else:
    SUBDOMAIN_DOMAIN = 'uonalumni.or.ke'
    SUBDOMAIN_URLCONFS = {
        None:       'main.urls',
        'www':      'main.urls',
        'staff':    'apps.staff.site_urls',
        'students': 'apps.student.urls',
    }


# Origin encoded into printed QR badges. Explicit rather than derived
# from DEBUG: a QR is a permanent artifact, so the URL it carries must
# never depend on what mode the generating process happened to run in.
if DEBUG:
    QR_SCAN_ORIGIN = os.getenv('QR_SCAN_ORIGIN', 'http://staff.lvh.me:8000')
else:
    QR_SCAN_ORIGIN = os.getenv('QR_SCAN_ORIGIN', 'https://staff.uonalumni.or.ke')

    
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
# form (the ACCOUNT_UNIQUE_EMAIL conflict case). Safe because only
# Google-verified UoN addresses get this far.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Email domains allowed to sign in via Google, enforced in
# apps/user/adapter.py across all subdomains (main, staff, students).
# Add 'alumni.uonbi.ac.ke' to the env var once the ICT Directorate issues
# that extension — no code change needed, just update .env and redeploy.
ALLOWED_GOOGLE_LOGIN_DOMAINS = split_env_list(
    os.getenv('ALLOWED_GOOGLE_LOGIN_DOMAINS', 'uonbi.ac.ke')
)

# Toggle domain restriction for local development/testing.
# Set RESTRICT_GOOGLE_LOGIN_DOMAINS=False in .env to allow any Google account.
RESTRICT_GOOGLE_LOGIN_DOMAINS = os.getenv('RESTRICT_GOOGLE_LOGIN_DOMAINS', 'True') == 'True'

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