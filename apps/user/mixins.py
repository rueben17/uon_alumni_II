from functools import wraps

from django.contrib.auth.mixins import UserPassesTestMixin
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
