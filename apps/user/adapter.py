import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.user.models import User

logger = logging.getLogger(__name__)

ALLOWED_GOOGLE_LOGIN_DOMAINS = getattr(
    settings,
    "ALLOWED_GOOGLE_LOGIN_DOMAINS",
    ["uonbi.ac.ke"],
)

ALLOWED_STUDENT_LOGIN_DOMAINS = getattr(
    settings,
    "ALLOWED_STUDENT_LOGIN_DOMAINS",
    ["students.uonbi.ac.ke"],
)

RESTRICT_GOOGLE_LOGIN_DOMAINS = getattr(
    settings,
    "RESTRICT_GOOGLE_LOGIN_DOMAINS",
    True,
)

STAFF_URLCONF = "apps.staff.site_urls"
STUDENT_URLCONF = "apps.student.urls"


# ─────────────────────────────────────────────
# Role record helpers
# ─────────────────────────────────────────────

def _ensure_profile(user, extra_data=None):
    """
    Get or create the UserProfile for a user, optionally syncing Google
    name/photo/locale fields onto it. Person data lives once on
    UserProfile now (docs/rebuild-schema.md), not duplicated per role —
    this replaces what used to be separate given_name/family_name/
    google_photo_url copies on User and on Employee.

    Called with extra_data whenever a Google payload is actually in hand
    (new signup, existing-user login) to keep it fresh; called with none
    as a safety net wherever a role record is about to be created
    (Employee/Student's slugs read through user.profile, so it must
    exist before their first save — e.g. an admin session with no
    sociallogin in scope). A no-extra_data call never overwrites real
    data with blanks — it only creates the row if missing.
    """
    from apps.user.models import UserProfile

    profile = getattr(user, "profile", None)
    if profile is None:
        defaults = {}
        if extra_data:
            defaults = {
                "given_name": extra_data.get("given_name", ""),
                "family_name": extra_data.get("family_name", ""),
                "google_photo_url": extra_data.get("picture", ""),
                "locale": extra_data.get("locale", ""),
            }
        profile, created = UserProfile.objects.get_or_create(user=user, defaults=defaults)
        if created:
            logger.info("Created UserProfile for user %s", user.pk)

    if extra_data:
        profile.given_name = extra_data.get("given_name", profile.given_name)
        profile.family_name = extra_data.get("family_name", profile.family_name)
        profile.google_photo_url = extra_data.get("picture", profile.google_photo_url)
        profile.locale = extra_data.get("locale", profile.locale)
        profile.save()

    # Cache on the instance so later hooks in the same request
    # (redirect resolution, Employee's slug computation) don't hit the
    # DB again.
    user.profile = profile
    return profile


def _sync_google_account_fields(user, extra_data):
    """
    Sets google_sub/email_verified/auth_provider from a Google payload.

    Bug fixed 2026-08-07: this used to live inline in save_user() only,
    which runs exclusively for brand-new signups. An EXISTING account
    logging in again (e.g. one created before this code existed, or
    created directly rather than through a Google signup) went through
    pre_social_login()'s is_existing branch instead, which called
    _ensure_profile() but never this -- so those three fields stayed
    permanently blank no matter how many times the user logged in via
    Google. Now called from both places.
    """
    user.google_sub = extra_data.get("sub")
    user.email_verified = extra_data.get("email_verified", False)
    user.auth_provider = User.AuthProvider.GOOGLE
    user.save(update_fields=["google_sub", "email_verified", "auth_provider"])


def _ensure_employee(user):
    """
    Get or create the Employee record for a user. Called on every
    staff-subdomain login, so a user who signed up elsewhere still gets
    a record the first time they authenticate on staff. Idempotent.

    _ensure_profile() runs first (even with no Google data in hand) so
    there is always a UserProfile row before Employee's first save — its
    AutoSlugField reads instance.user.profile, and that failing on a
    brand-new record is a RelatedObjectDoesNotExist, not a harmless
    "failed to populate slug" warning.
    """
    from apps.staff.models import Employee

    _ensure_profile(user)

    employee = getattr(user, "employee", None)
    if employee is None:
        employee, created = Employee.objects.get_or_create(user=user)
        if created:
            logger.info("Created Employee record for user %s", user.pk)

    # Cache on the instance so later hooks in the same request
    # (redirect resolution) don't hit the DB again.
    user.employee = employee
    return employee


def _staff_subdomain_url(request, path):
    """
    Build an absolute URL on the staff subdomain, preserving the dev
    port. reverse(..., urlconf=STAFF_URLCONF) only returns the PATH --
    a bare redirect to that path while the browser is on a different
    subdomain (e.g. the main domain) never actually switches hosts, so
    the path 404s against whichever urlconf the current host maps to.
    """
    domain = settings.SUBDOMAIN_DOMAIN
    host = request.get_host()
    port = f":{host.split(':')[1]}" if ":" in host else ""
    scheme = "https" if request.is_secure() else "http"
    return f"{scheme}://staff.{domain}{port}{path}"


def _admin_onboarding_redirect_url(user, request):
    """
    is_staff (non-superuser) accounts must have both a complete Employee
    record and an AlumniProfile before landing in the Django admin --
    presumed to be real UoN staff granted limited admin access, so the
    same completeness gate as the staff subdomain applies. Returns the
    next URL they should be sent to, or None if both are already
    complete (caller then sends them to the admin). Employee is checked
    first -- matches the staff-subdomain completeness gate's own
    priority.

    NOT called for is_superuser accounts (2026-08-07) -- see the
    is_superuser bypass in get_login_redirect_url()/get_signup_
    redirect_url() below. A Django superuser is a dev/admin concept,
    not evidence the account belongs to actual UoN staff; routing it
    through here auto-created an empty Employee stub on every login and
    then blocked on completing it, unrelated to why a superuser needs
    admin access.
    """
    employee = _ensure_employee(user)
    if not employee.profile_is_complete:
        path = reverse(
            "staff:complete_profile",
            kwargs={"uuid": employee.id},
            urlconf=STAFF_URLCONF,
        )
        return _staff_subdomain_url(request, path)

    if not hasattr(user, "alumni_profile"):
        return reverse("home:uon_alumni_register")

    return None


def _employee_exists_for_email(email):
    from apps.staff.models import Employee

    if not email:
        return False

    return Employee.objects.filter(user__email__iexact=email).exists()


# ----- Students: no auto-created stub (2026-08-14) -----
#
# Employee has an auto-stub-then-complete flow because staff_id is
# nullable (null=True, blank=True) -- a bare get_or_create(user=user) is
# always valid there. Student.registration_no is NOT nullable and is
# unique, so a bare stub would insert "" and collide with the next
# unregistered signup's own "". Students instead follow the ALUMNI
# pattern (see AlumniRegisterView/home:uon_alumni_register): Google auth
# only creates the User/UserProfile; a real form
# (apps.student.views.StudentRegisterView) collects registration_no and
# creates the Student row in one step. get_login_redirect_url() below
# sends anyone without a Student record there instead of auto-creating
# anything.


# ─────────────────────────────────────────────
# Account adapter — redirects
# ─────────────────────────────────────────────

class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Handles post-login, post-signup, and post-logout redirects.
    allauth calls these on the ACCOUNT adapter for all login types,
    so redirect logic lives here.

    Flow (completeness-gated onboarding):
      - login on staff. with INCOMPLETE profile → complete_profile.
        This covers brand-new signups (a fresh stub is incomplete by
        definition) AND abandoners who never finished the form — no
        signup-vs-login detection needed.
      - login on staff. with COMPLETE profile → slugged detail page
        (via Employee.get_absolute_url()).
      - profile edits are opt-in via ProfileUpdateView, never forced.
      - logout (from anywhere) → main site home page.
    """

    def is_safe_url(self, url):
        """
        Allow redirects to any of our own hosts. Note that
        url_has_allowed_host_and_scheme() does EXACT host matching —
        a leading-dot wildcard like '.uonalumni.or.ke' never matches,
        so the hosts are enumerated explicitly.
        """
        base = settings.SUBDOMAIN_DOMAIN
        subdomains = [s for s in getattr(settings, "SUBDOMAIN_URLCONFS", {}) if s]
        allowed_hosts = {base} | {f"{sub}.{base}" for sub in subdomains}
        if settings.DEBUG:
            # Dev hosts carry the runserver port.
            allowed_hosts |= {f"{h}:8000" for h in set(allowed_hosts)}
        return url_has_allowed_host_and_scheme(
            url=url,
            allowed_hosts=allowed_hosts,
            require_https=not settings.DEBUG,
        )

    def get_login_redirect_url(self, request):
        """
        Every login, including auto social signups (allauth routes
        those through here, not get_signup_redirect_url). The gate is
        simply profile completeness — the Employee record itself
        tells us whether onboarding is finished.
        """
        subdomain = getattr(request, "subdomain", None)
        user = getattr(request, "user", None)
        logger.debug("Login redirect: subdomain=%s user=%s", subdomain, user)

        if user and user.is_authenticated:
            # Superusers skip the staff-onboarding gate entirely (2026-08-07):
            # is_superuser is a Django/dev-admin concept, not "this person is
            # UoN staff" -- gating it on Employee completeness was auto-
            # creating an empty Employee stub for every superuser login and
            # then blocking on it, which has nothing to do with why a
            # superuser needs admin access in the first place.
            if user.is_superuser:
                return reverse("admin:index")

            if user.is_staff:
                next_url = _admin_onboarding_redirect_url(user, request)
                return next_url or reverse("admin:index")

            if subdomain == "staff":
                employee = getattr(user, "employee", None)
                if employee is None:
                    employee = _ensure_employee(user)

                if not employee.profile_is_complete:
                    return reverse(
                        "staff:complete_profile",
                        kwargs={"uuid": employee.id},
                        urlconf=STAFF_URLCONF,
                    )
                return employee.get_absolute_url()

            elif subdomain in (None, "www"):
                if not hasattr(user, "alumni_profile"):
                    return reverse("home:uon_alumni_register")

            elif subdomain == "students":
                if not hasattr(user, "student"):
                    return reverse("student:register", urlconf=STUDENT_URLCONF)

                # Sent here by uon_alumni_scholarship() (apps/home/views.py)
                # for an anonymous visitor -- stashed in the session, not a
                # `next` GET param, because allauth's own next-param
                # handling (allauth.account.utils.get_login_redirect_url)
                # takes priority over this adapter method entirely and
                # would let it bypass the "no Student record yet" branch
                # just above.
                next_url = request.session.pop("post_login_next", None)
                if next_url and self.is_safe_url(next_url):
                    return next_url

        return super().get_login_redirect_url(request)

    def get_signup_redirect_url(self, request):
        """
        Fires only for FORM-BASED signups (auto social signups go
        through get_login_redirect_url instead). Same rule applies:
        a brand-new account is incomplete, so → onboarding.
        """
        subdomain = getattr(request, "subdomain", None)
        user = getattr(request, "user", None)

        if user and user.is_authenticated:
            # Same superuser bypass as get_login_redirect_url() above.
            if user.is_superuser:
                return reverse("admin:index")

            if user.is_staff:
                next_url = _admin_onboarding_redirect_url(user, request)
                return next_url or reverse("admin:index")

            if subdomain == "staff":
                employee = getattr(user, "employee", None)
                if employee is None:
                    employee = _ensure_employee(user)

                return reverse(
                    "staff:complete_profile",
                    kwargs={"uuid": employee.id},
                    urlconf=STAFF_URLCONF,
                )

            elif subdomain in (None, "www"):
                if not hasattr(user, "alumni_profile"):
                    return reverse("home:uon_alumni_register")

            elif subdomain == "students":
                # A brand-new signup can't have a Student record yet --
                # no existence check needed, unlike get_login_redirect_url.
                return reverse("student:register", urlconf=STUDENT_URLCONF)

        return super().get_signup_redirect_url(request)

    def get_logout_redirect_url(self, request):
        """
        Shared logout for every subdomain: always land on the main
        site's home page. Preserves the port in dev (lvh.me:8000).
        """
        base = settings.SUBDOMAIN_DOMAIN
        host = request.get_host()
        port = f":{host.split(':')[1]}" if ":" in host else ""
        scheme = "https" if request.is_secure() else "http"
        return f"{scheme}://{base}{port}/"


# ─────────────────────────────────────────────
# Social account adapter — Google specifics
# ─────────────────────────────────────────────

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Google OAuth domain restriction, User field population, and
    Employee/Student record creation keyed on the subdomain the
    login flow ran on.
    """

    def pre_social_login(self, request, sociallogin):
        subdomain = getattr(request, "subdomain", None)

        # 1. Domain restriction — staff and students only. Both identities
        # are verified via an institutional email, so this stays
        # meaningful there. The main site is a public alumni association:
        # most alumni lose @uonbi.ac.ke access at graduation, so gating it
        # here too (the previous behaviour -- "applies to every
        # subdomain") just silently blocked ordinary alumni from ever
        # registering. Any Google account may sign in on the main
        # subdomain.
        role_domains = {"staff": ALLOWED_GOOGLE_LOGIN_DOMAINS, "students": ALLOWED_STUDENT_LOGIN_DOMAINS}
        if subdomain in role_domains and RESTRICT_GOOGLE_LOGIN_DOMAINS:
            email = sociallogin.account.extra_data.get("email", "")
            domain = email.split("@")[-1].lower()

            if domain not in role_domains[subdomain]:
                messages.error(
                    request,
                    "Please sign in using your University of Nairobi email.",
                )
                raise ImmediateHttpResponse(redirect("account_login"))

        process = sociallogin.state.get("process", "login")

        # On the staff subdomain, treat login and signup as different entry
        # points. Login requires an existing Employee record; signup is the
        # onboarding path for users who do not yet have one.
        if subdomain == "staff":
            email = sociallogin.account.extra_data.get("email", "")
            has_employee = _employee_exists_for_email(email)

            if process == "login" and not has_employee:
                messages.warning(
                    request,
                    "No staff profile was found for this Google account. Please sign up to start onboarding.",
                )
                raise ImmediateHttpResponse(redirect("account_signup"))

            if process == "signup" and has_employee:
                messages.warning(
                    request,
                    "This account already has a staff profile. Please sign in instead.",
                )
                raise ImmediateHttpResponse(redirect("account_login"))

            # Students have no equivalent login-vs-signup gate: unlike
            # staff (whose Employee records may be provisioned ahead of a
            # first login), every student's very first sign-in IS their
            # signup -- is_auto_signup_allowed() below already lets any
            # domain-restricted account through either way, so there's no
            # "has no record yet, but tried to log in" case to catch here.

        # 2. Login-time record creation for EXISTING users. New users
        #    don't have a saved User yet — save_user() covers them.
        # Only staff gets a role record here: a Student can't be
        # auto-created (see the comment above _ensure_employee's Student
        # equivalent) -- get_login_redirect_url() below routes a
        # Student-less login to the registration form instead.
        if sociallogin.is_existing:
            subdomain = getattr(request, "subdomain", None)
            user = sociallogin.user
            _ensure_profile(user, sociallogin.account.extra_data)
            _sync_google_account_fields(user, sociallogin.account.extra_data)

            if subdomain == "staff":
                _ensure_employee(user)

        return super().pre_social_login(request, sociallogin)

    @transaction.atomic
    def save_user(self, request, sociallogin, form=None):
        """
        Runs ONLY when a brand-new account is created. Populates the
        User from Google and creates the role record for the
        subdomain. The fresh record is incomplete by definition, so
        the completeness gate routes them into onboarding.
        """
        user = super().save_user(request, sociallogin, form)

        extra = sociallogin.account.extra_data

        _sync_google_account_fields(user, extra)

        # Name/photo/locale live on UserProfile now, not User (docs/
        # rebuild-schema.md). `hd` (Google Workspace domain) is dropped
        # outright — already in sociallogin.account.extra_data, a model
        # column would just be a second copy that goes stale.
        _ensure_profile(user, extra)

        subdomain = getattr(request, "subdomain", None)

        if subdomain == "staff":
            _ensure_employee(user)

        return user

    def is_auto_signup_allowed(self, request, sociallogin):
        return True

    def get_connect_redirect_url(self, request, socialaccount):
        """
        Only called when an already-logged-in user connects an
        additional social account. Same completeness gate as a
        normal login.
        """
        subdomain = getattr(request, "subdomain", None)
        user = socialaccount.user

        if subdomain == "staff":
            employee = getattr(user, "employee", None)
            if employee is None:
                employee = _ensure_employee(user)
            if not employee.profile_is_complete:
                return reverse(
                    "staff:complete_profile",
                    kwargs={"uuid": employee.id},
                    urlconf=STAFF_URLCONF,
                )
            return employee.get_absolute_url()

        if subdomain == "students" and not hasattr(user, "student"):
            return reverse("student:register", urlconf=STUDENT_URLCONF)

        return super().get_connect_redirect_url(request, socialaccount)