# apps/user/adapter.py
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from apps.user.models import User  # your custom User model

# Email domains allowed to sign in via Google, across all subdomains
# (main, staff, students). Add 'alumni.uonbi.ac.ke' here once the ICT
# Directorate issues that extension — until then, alumni without a current
# @uonbi.ac.ke email cannot sign in.
ALLOWED_GOOGLE_LOGIN_DOMAINS = getattr(
    settings,
    'ALLOWED_GOOGLE_LOGIN_DOMAINS',
    ['uonbi.ac.ke'],
)


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter for Google OAuth that:
    - Restricts Google sign-in to ALLOWED_GOOGLE_LOGIN_DOMAINS on every
      subdomain (main, staff, students)
    - Creates/updates User with Google data (sub, email_verified, locale, hd, photo)
    - On the staff subdomain: creates/updates an Employee record linked to the User
    - On the students subdomain: will create/update a Student record (not built yet)
    - Sets auth_provider = GOOGLE

    request.subdomain is set by main.middleware.SubdomainRoutingMiddleware and is
    one of: None, 'www', 'staff', 'students'.
    """

    def pre_social_login(self, request, sociallogin):
        """
        Runs before save_user(), before any User/SocialAccount is created or
        linked. Rejects the login outright if the Google account's email
        domain isn't in ALLOWED_GOOGLE_LOGIN_DOMAINS.
        """
        email = sociallogin.account.extra_data.get('email', '')
        domain = email.split('@')[-1].lower() if '@' in email else ''

        if domain not in ALLOWED_GOOGLE_LOGIN_DOMAINS:
            messages.error(
                request,
                'Please sign in with your University of Nairobi (uonbi.ac.ke) email.',
            )
            raise ImmediateHttpResponse(redirect('account_login'))

        super().pre_social_login(request, sociallogin)

    @transaction.atomic
    def save_user(self, request, sociallogin, form=None):
        """
        Overrides the default save_user() to add our custom fields and
        create the associated Employee (staff) or Student record, depending
        on which subdomain the login happened on.
        """
        # First, let allauth create/save the basic User instance
        user = super().save_user(request, sociallogin, form)

        # Get the raw data from Google (stored in the SocialAccount)
        extra_data = sociallogin.account.extra_data

        # ----- Update User with Google-specific fields -----
        user.google_sub = extra_data.get('sub')
        user.email_verified = extra_data.get('email_verified', False)
        user.locale = extra_data.get('locale', '')
        user.hd = extra_data.get('hd', '')
        user.google_photo_url = extra_data.get('picture', '')
        user.auth_provider = User.AuthProvider.GOOGLE

        # given_name and family_name are already set by allauth's default save_user
        # (they come from details dict), but we re-fetch for safety.
        user.given_name = extra_data.get('given_name', '')
        user.family_name = extra_data.get('family_name', '')

        user.save()

        subdomain = getattr(request, 'subdomain', None)

        # ----- Create or update Employee record (staff subdomain only) -----
        if subdomain == 'staff':
            # Import Employee inside the method to avoid circular imports
            from apps.staff.models import Employee

            employee, created = Employee.objects.get_or_create(user=user)

            # Always sync the name and photo from User → Employee
            employee.given_name = user.given_name
            employee.family_name = user.family_name
            employee.google_photo_url = user.google_photo_url

            # For existing employees, we do NOT overwrite organisational fields
            # (staff_id, staff_track, department, etc.) – those are user-filled.
            # If this is a brand new employee, all those fields are already empty.

            employee.save()

        # ----- Create or update Student record (students subdomain only) -----
        # Not built yet — apps.student.models.Student doesn't exist. Stubbed
        # here so the staff/student branches stay symmetric when it's ready.
        #
        # elif subdomain == 'students':
        #     from apps.student.models import Student
        #
        #     student, created = Student.objects.get_or_create(user=user)
        #     student.given_name = user.given_name
        #     student.family_name = user.family_name
        #     student.google_photo_url = user.google_photo_url
        #     student.save()

        return user

    def get_connect_redirect_url(self, request, socialaccount):
        """
        Only called when an already-logged-in user connects an additional
        social account (not on initial signup/login). Guarded so it doesn't
        crash for users without an Employee record.
        """
        employee = getattr(socialaccount.user, 'employee', None)
        if employee is not None:
            return reverse('staff:complete_profile', kwargs={'uuid': employee.id})

        # Not built yet — apps.student.urls has no 'complete_profile' route
        # and Student isn't a real relation on User yet. Stubbed here so the
        # staff/student branches stay symmetric when it's ready.
        #
        # student = getattr(socialaccount.user, 'student', None)
        # if student is not None:
        #     return reverse('students:complete_profile', kwargs={'uuid': student.id})

        return super().get_connect_redirect_url(request, socialaccount)