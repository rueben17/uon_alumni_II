from functools import wraps

from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def _is_admin_user(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


class StaffOrSuperuserRequiredMixin(UserPassesTestMixin):
    """Gate for staff/superadmin-only views (e.g. membership analytics) --
    same is_staff/is_superuser check as _is_admin_user above, inverted:
    this DENIES anyone who isn't one, rather than redirecting them away
    from an alumni-facing view. Raises Django's standard 403 (via
    UserPassesTestMixin's default) for anyone else, including anonymous
    users -- not a silent redirect, since this gates actual data."""

    def test_func(self):
        return _is_admin_user(self.request.user)


def user_is_employee(user):
    """Real UoN employee, not Django-admin staff -- deliberately a
    different predicate from _is_admin_user above (2026-08-21 QA audit,
    2-AUTH): the staff directory/detail pages are for any employee, not
    just accounts with Django's is_staff/is_superuser flag, which would
    lock out ordinary (non-admin) employees. `.employee` is the
    OneToOneField's related_name (apps.staff.models.Employee.user)."""
    return user.is_authenticated and hasattr(user, "employee")


class EmployeeRequiredMixin(UserPassesTestMixin):
    """Gate for UoN-employee-only views (e.g. the staff directory/detail
    pages) -- same shape as StaffOrSuperuserRequiredMixin above, swapped
    to user_is_employee. UserPassesTestMixin's real default behavior
    (confirmed live against StaffOrSuperuserRequiredMixin during the QA
    audit, not just the docstring above): anonymous -> redirect to
    login (302); authenticated but test_func() False -> PermissionDenied
    (403)."""

    def test_func(self):
        return user_is_employee(self.request.user)


def employee_required(view_func):
    """FBV decorator with the SAME two-tier behavior as
    EmployeeRequiredMixin -- NOT django.contrib.auth.decorators
    .user_passes_test, which redirects an authenticated non-employee
    back to login too (indistinguishable from anonymous, not the 403
    this needs to actually gate data the way the CBV mixin does)."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not user_is_employee(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


class AdminRedirectMixin:
    """
    Superusers and staff (Django's is_staff/is_superuser) get bounced to
    the Django admin instead of the regular alumni-facing flow. Temporary
    blanket redirect until dedicated admin-facing views/permissions exist
    (see apps/qr_manager/qr_admin_site.py for the eventual subclassed-
    admin pattern this will follow).
    """

    def dispatch(self, request, *args, **kwargs):
        if _is_admin_user(request.user):
            return redirect(reverse("admin:index"))
        return super().dispatch(request, *args, **kwargs)


def redirect_admins_to_admin(view_func):
    """Function-view equivalent of AdminRedirectMixin."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if _is_admin_user(request.user):
            return redirect(reverse("admin:index"))
        return view_func(request, *args, **kwargs)

    return wrapped
