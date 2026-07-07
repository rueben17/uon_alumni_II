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

RESTRICT_GOOGLE_LOGIN_DOMAINS = getattr(
    settings,
    "RESTRICT_GOOGLE_LOGIN_DOMAINS",
    True,
)

STAFF_URLCONF = "apps.staff.site_urls"
# STUDENT_URLCONF = "apps.student.site_urls"


# ─────────────────────────────────────────────
# Role record helpers
# ─────────────────────────────────────────────

def _ensure_employee(user):
    """
    Get or create the Employee record for a user, syncing Google
    profile fields onto it. Called on every staff-subdomain login,
    so a user who signed up elsewhere still gets a record the first
    time they authenticate on staff. Idempotent.

    Names are passed as creation defaults so the very first save
    already has content for AutoSlugField to slugify — otherwise the
    initial save logs "Failed to populate slug" (harmless, but noisy).
    """
    from apps.staff.models import Employee

    employee = getattr(user, "employee", None)
    if employee is None:
        employee, created = Employee.objects.get_or_create(
            user=user,
            defaults={
                "given_name": user.given_name,
                "family_name": user.family_name,
                "google_photo_url": user.google_photo_url,
            },
        )
        if created:
            logger.info("Created Employee record for user %s", user.pk)

    # Sync display fields from the User (covers the existing-record
    # case and keeps Google data fresh on every login).
    employee.given_name = user.given_name
    employee.family_name = user.family_name
    employee.google_photo_url = user.google_photo_url
    employee.save()

    # Cache on the instance so later hooks in the same request
    # (redirect resolution) don't hit the DB again.
    user.employee = employee
    return employee


def _employee_exists_for_email(email):
    from apps.staff.models import Employee

    if not email:
        return False

    return Employee.objects.filter(user__email__iexact=email).exists()


# ----- Student equivalent (uncomment once apps.student is built) -----
#
# def _ensure_student(user):
#     from apps.student.models import Student
#
#     student = getattr(user, "student", None)
#     if student is None:
#         student, created = Student.objects.get_or_create(
#             user=user,
#             defaults={
#                 "given_name": user.given_name,
#                 "family_name": user.family_name,
#                 "google_photo_url": user.google_photo_url,
#             },
#         )
#         if created:
#             logger.info("Created Student record for user %s", user.pk)
#
#     student.given_name = user.given_name
#     student.family_name = user.family_name
#     student.google_photo_url = user.google_photo_url
#     student.save()
#
#     user.student = student
#     return student


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

            # ----- Students (not built yet) -----
            #
            # elif subdomain == "students":
            #     student = getattr(user, "student", None)
            #     if student is not None:
            #         if not student.profile_is_complete:
            #             return reverse(
            #                 "students:complete_profile",
            #                 kwargs={"uuid": student.id},
            #                 urlconf=STUDENT_URLCONF,
            #             )
            #         return student.get_absolute_url()
            #     logger.warning(
            #         "Student login without Student record: user %s", user.pk
            #     )

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
            if subdomain == "staff":
                employee = getattr(user, "employee", None)
                if employee is None:
                    employee = _ensure_employee(user)

                return reverse(
                    "staff:complete_profile",
                    kwargs={"uuid": employee.id},
                    urlconf=STAFF_URLCONF,
                )

            # ----- Students (not built yet) -----
            #
            # elif subdomain == "students":
            #     student = getattr(user, "student", None)
            #     if student is not None:
            #         return reverse(
            #             "students:complete_profile",
            #             kwargs={"uuid": student.id},
            #             urlconf=STUDENT_URLCONF,
            #         )

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
        # 1. Domain restriction — applies to every subdomain.
        if RESTRICT_GOOGLE_LOGIN_DOMAINS:
            email = sociallogin.account.extra_data.get("email", "")
            domain = email.split("@")[-1].lower()

            if domain not in ALLOWED_GOOGLE_LOGIN_DOMAINS:
                messages.error(
                    request,
                    "Please sign in using your University of Nairobi email.",
                )
                raise ImmediateHttpResponse(redirect("account_login"))

        subdomain = getattr(request, "subdomain", None)
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

            # ----- Students (not built yet) -----
            #
            # if subdomain == "students":
            #     email = sociallogin.account.extra_data.get("email", "")
            #     has_student = _student_exists_for_email(email)
            #
            #     if process == "login" and not has_student:
            #         messages.warning(
            #             request,
            #             "No student profile was found for this Google account. Please sign up to start onboarding.",
            #         )
            #         raise ImmediateHttpResponse(redirect("account_signup"))
            #
            #     if process == "signup" and has_student:
            #         messages.warning(
            #             request,
            #             "This account already has a student profile. Please sign in instead.",
            #         )
            #         raise ImmediateHttpResponse(redirect("account_login"))

        # 2. Login-time record creation for EXISTING users. New users
        #    don't have a saved User yet — save_user() covers them.
        if sociallogin.is_existing:
            subdomain = getattr(request, "subdomain", None)
            user = sociallogin.user

            if subdomain == "staff":
                _ensure_employee(user)

            # ----- Students (not built yet) -----
            #
            # elif subdomain == "students":
            #     _ensure_student(user)

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

        user.google_sub = extra.get("sub")
        user.email_verified = extra.get("email_verified", False)
        user.locale = extra.get("locale", "")
        user.hd = extra.get("hd", "")
        user.google_photo_url = extra.get("picture", "")
        user.auth_provider = User.AuthProvider.GOOGLE
        user.given_name = extra.get("given_name", "")
        user.family_name = extra.get("family_name", "")
        user.save()

        subdomain = getattr(request, "subdomain", None)

        if subdomain == "staff":
            _ensure_employee(user)

        # ----- Students (not built yet) -----
        #
        # elif subdomain == "students":
        #     _ensure_student(user)

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

        # ----- Students (not built yet) -----
        #
        # if subdomain == "students":
        #     student = getattr(user, "student", None)
        #     if student is None:
        #         student = _ensure_student(user)
        #     if not student.profile_is_complete:
        #         return reverse(
        #             "students:complete_profile",
        #             kwargs={"uuid": student.id},
        #             urlconf=STUDENT_URLCONF,
        #         )
        #     return student.get_absolute_url()

        return super().get_connect_redirect_url(request, socialaccount)