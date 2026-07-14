from functools import wraps

from django.shortcuts import redirect
from django.urls import reverse


def _is_admin_user(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


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
