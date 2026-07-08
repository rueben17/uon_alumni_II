from django.contrib import admin

from apps.qr_manager.models import Supervisor


class QRSupervisorAdminSite(admin.AdminSite):
    """A separate, minimal admin — only QR codes and a read-only unit
    roster — so a unit supervisor never sees Users, Groups, or the
    rest of the main admin. Login is gated on holding a Supervisor
    row; the usual Django model permissions (granted via the "QR
    Supervisors" group) still govern what they can actually do with
    QR codes once inside.
    """

    # Fallbacks only -- each_context() below replaces these per-request
    # with the logged-in user's actual unit(s), since site_header/
    # site_title/index_title are static class attributes in Django
    # and can't otherwise say "Plant Science & Crop Protection".
    site_header = "QR Supervisor Admin"
    site_title = "QR Supervisor Admin"
    index_title = "Your unit"

    def has_permission(self, request):
        user = request.user
        if not (user.is_active and user.is_staff):
            return False
        if user.is_superuser:
            return True
        return Supervisor.objects.filter(user=user).exists()

    def _unit_label(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return "QR Supervisor Admin"
        if user.is_superuser:
            # A superuser isn't scoped to one unit -- say so plainly,
            # so it's never mistaken for a specific unit's site.
            return "All Units (Superuser)"
        units = [
            str(role.unit)
            for role in Supervisor.objects.filter(user=user).select_related(
                "department", "service_unit", "research_unit"
            )
            if role.unit
        ]
        return " / ".join(units) if units else "QR Supervisor Admin"

    def each_context(self, request):
        context = super().each_context(request)
        unit_label = self._unit_label(request)
        context["site_header"] = f"{unit_label} — QR Admin"
        context["site_title"] = f"{unit_label} QR Admin"
        context["index_title"] = unit_label
        return context


qr_admin_site = QRSupervisorAdminSite(name="qr_admin")
