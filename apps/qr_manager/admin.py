from django import forms
from django.contrib import admin, messages
from django.db.models import Count

from apps.home.models import AlumniProfile
from apps.qr_manager.models import QRCode, ScanLog, Supervisor
from apps.qr_manager.qr_admin_site import qr_admin_site
from apps.staff.models import Employee


def _regenerate_holder_badge(qr_code):
    """Rebuild and store the badge PNG for an employee- or
    alumni-linked code."""
    qr_code.generate_qr(force=True)


class EmployeeChoiceField(forms.ModelChoiceField):
    """Richer labels for the employee dropdown: name — email — unit."""

    def label_from_instance(self, obj):
        unit = obj.unit or "no unit"
        return f"{obj.user.profile.full_name} — {obj.user.email} — {unit}"


class AlumniProfileChoiceField(forms.ModelChoiceField):
    """Richer labels for the alumni dropdown: name — email."""

    def label_from_instance(self, obj):
        return f"{obj.user.profile.full_name} — {obj.user.email}"


@admin.register(QRCode)
class QRCodeAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = (
        "holder",
        "qr_type",
        "status",
        "scan_count_display",
        "unique_ip_count_display",
        "issued_at",
        "expires_at",
        "is_active",
    )
    list_filter = ("qr_type", "is_active")
    search_fields = (
        "employee__user__profile__given_name",
        "employee__user__profile__family_name",
        "employee__staff_id",
        "alumni_profile__user__profile__given_name",
        "alumni_profile__user__profile__family_name",
        "label",
    )
    readonly_fields = ("id", "token", "issued_at", "status")
    actions = ("revoke_codes", "reactivate_codes", "rotate_tokens")

    # ---------------------------------------------------------------
    # Unit scoping — a non-superuser can only manage QR codes for
    # employees in a unit they supervise (see Supervisor model).
    # Superusers are unrestricted. Alumni have no unit concept at all,
    # so alumni-linked codes fall into the same "superuser-only" bucket
    # as visitor/event codes below, not a scoping rule of their own.
    # ---------------------------------------------------------------

    def _supervisor_unit_q(self, request, prefix=""):
        """None = unrestricted (superuser). False = scoped to nothing
        (no Supervisor rows). Otherwise a Q for `prefix`."""
        if request.user.is_superuser:
            return None
        return Supervisor.unit_q_for(request.user, prefix=prefix)

    def _object_in_scope(self, request, obj):
        """Supervisors may only touch employee-linked codes in their
        own unit — visitor/event/alumni codes with no employee are
        superuser-only."""
        if obj.employee_id is None:
            return False
        q = self._supervisor_unit_q(request)
        if q is None:
            return True
        if q is False:
            return False
        return Employee.objects.filter(q, pk=obj.employee_id).exists()

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        q = self._supervisor_unit_q(request, prefix="employee__")
        if q is False:
            qs = qs.none()
        elif q is not None:
            qs = qs.filter(q)
        # Every scan is still logged individually in ScanLog (useful
        # evidence -- e.g. a badge suddenly scanned from a new IP),
        # but the changelist shouldn't make a supervisor count rows by
        # hand to answer "how many times has this been scanned".
        return qs.annotate(
            scan_count=Count("scans"),
            unique_ip_count=Count("scans__ip_address", distinct=True),
        )

    def has_add_permission(self, request):
        if not super().has_add_permission(request):
            return False
        return self._supervisor_unit_q(request) is not False

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        if obj is None or request.user.is_superuser:
            return True
        return self._object_in_scope(request, obj)

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        if obj is None or request.user.is_superuser:
            return True
        return self._object_in_scope(request, obj)

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        if obj is None or request.user.is_superuser:
            return True
        return self._object_in_scope(request, obj)

    def save_model(self, request, obj, form, change):
        """Generating on save is what makes the QRCode add form 'just
        work': create (or edit) a code with an employee or alumni
        profile attached and the badge image is built immediately — no
        separate action needed. This is the hook the old signal used
        to provide."""
        super().save_model(request, obj, form, change)
        if obj.employee_id or obj.alumni_profile_id:
            obj.generate_qr(force=True)
            self.message_user(
                request,
                f"QR badge image generated for {obj.holder.user.profile.full_name}.",
                messages.SUCCESS,
            )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # OneToOne fields route through here too. select_related keeps
        # the rich labels from firing 4 queries per employee.
        if db_field.name == "employee":
            queryset = Employee.objects.select_related(
                "user", "user__profile", "department", "service_unit", "research_unit"
            ).order_by("user__profile__family_name", "user__profile__given_name")
            q = self._supervisor_unit_q(request)
            if q is False:
                queryset = queryset.none()
            elif q is not None:
                queryset = queryset.filter(q)
            kwargs["queryset"] = queryset
            kwargs["form_class"] = EmployeeChoiceField
        elif db_field.name == "alumni_profile":
            # Superuser-only, matching _object_in_scope's treatment of
            # alumni-linked codes -- a non-superuser supervisor could
            # otherwise create one here and then immediately lose the
            # ability to view/change it.
            queryset = AlumniProfile.objects.select_related("user", "user__profile").order_by(
                "user__profile__family_name", "user__profile__given_name"
            )
            if not request.user.is_superuser:
                queryset = queryset.none()
            kwargs["queryset"] = queryset
            kwargs["form_class"] = AlumniProfileChoiceField
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Holder")
    def holder(self, obj):
        holder = obj.holder
        return holder.user.profile.full_name if holder else (obj.label or "—")

    @admin.display(description="Scans", ordering="scan_count")
    def scan_count_display(self, obj):
        return obj.scan_count

    @admin.display(description="Unique IPs", ordering="unique_ip_count")
    def unique_ip_count_display(self, obj):
        return obj.unique_ip_count

    @admin.action(description="Revoke selected QR codes")
    def revoke_codes(self, request, queryset):
        count = 0
        for qr in queryset.filter(is_active=True):
            qr.revoke()
            count += 1
        self.message_user(
            request,
            f"Revoked {count} QR code(s). (Note: scans redirect regardless "
            f"until validity enforcement is switched on in verify_scan.)",
            messages.SUCCESS,
        )

    @admin.action(description="Reactivate selected QR codes")
    def reactivate_codes(self, request, queryset):
        updated = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(
            request, f"Reactivated {updated} QR code(s).", messages.SUCCESS
        )

    @admin.action(
        description="Rotate token (lost badge) — regenerates holder's badge image"
    )
    def rotate_tokens(self, request, queryset):
        rotated = 0
        for qr in queryset:
            qr.rotate_token()
            # Keep the stored badge image in sync with the new token —
            # otherwise the holder's qr_code_image shows a QR whose
            # token no longer matches. Label-only codes store no image.
            if qr.employee_id or qr.alumni_profile_id:
                _regenerate_holder_badge(qr)
            rotated += 1
        self.message_user(
            request,
            f"Rotated {rotated} token(s). Previously printed copies now fail "
            f"the token check; holder badge images were regenerated for "
            f"reprinting.",
            messages.SUCCESS,
        )


@admin.register(ScanLog)
class ScanLogAdmin(admin.ModelAdmin):
    list_per_page = 25
    """Read-only: scan history is evidence, not data entry. Scoped to
    a supervisor's own unit(s), same as QRCodeAdmin -- gated on
    holding a Supervisor row (or being superuser) rather than Django's
    view_scanlog permission, so no extra one-time setup step is
    needed beyond the Supervisor row itself."""

    list_display = (
        "holder",
        "holder_email",
        "holder_department",
        "result",
        "scanned_at",
        "ip_address",
        "badge_scan_count_display",
        "badge_unique_ip_count_display",
    )
    list_filter = ("result",)
    date_hierarchy = "scanned_at"
    search_fields = (
        "qrcode__employee__user__profile__given_name",
        "qrcode__employee__user__profile__family_name",
        "qrcode__employee__user__email",
    )
    list_select_related = (
        "qrcode__employee__user",
        "qrcode__employee__user__profile",
        "qrcode__employee__department",
        "qrcode__alumni_profile__user",
        "qrcode__alumni_profile__user__profile",
    )
    readonly_fields = [f.name for f in ScanLog._meta.fields]

    @admin.display(description="Scanned badge of")
    def holder(self, obj):
        if obj.qrcode and obj.qrcode.holder:
            return obj.qrcode.holder.user.profile.full_name
        if obj.qrcode:
            return obj.qrcode.label or "unassigned"
        return "— unknown QR —"

    @admin.display(description="Email")
    def holder_email(self, obj):
        if obj.qrcode and obj.qrcode.holder:
            return obj.qrcode.holder.user.email
        return "—"

    @admin.display(description="Department / Unit")
    def holder_department(self, obj):
        if obj.qrcode and obj.qrcode.employee:
            return obj.qrcode.employee.unit or "—"
        return "—"

    @admin.display(description="Badge scans total", ordering="badge_scan_count")
    def badge_scan_count_display(self, obj):
        return obj.badge_scan_count

    @admin.display(description="Badge unique IPs", ordering="badge_unique_ip_count")
    def badge_unique_ip_count_display(self, obj):
        return obj.badge_unique_ip_count

    def _is_supervisor(self, request):
        if not request.user.is_authenticated:
            return False
        return request.user.is_superuser or Supervisor.objects.filter(user=request.user).exists()

    def has_module_permission(self, request):
        return self._is_supervisor(request)

    def has_view_permission(self, request, obj=None):
        if not self._is_supervisor(request):
            return False
        if obj is None or request.user.is_superuser:
            return True
        if obj.qrcode_id is None or obj.qrcode.employee_id is None:
            return False
        q = Supervisor.unit_q_for(request.user)
        if q is False:
            return False
        return Employee.objects.filter(q, pk=obj.qrcode.employee_id).exists()

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            q = Supervisor.unit_q_for(request.user, prefix="qrcode__employee__")
            if q is False:
                qs = qs.none()
            else:
                qs = qs.filter(q)
        # Per-row context: total scans (and unique IPs) for the same
        # badge this row belongs to -- so "one log twice or thrice"
        # reads as an at-a-glance count instead of manual tallying.
        return qs.annotate(
            badge_scan_count=Count("qrcode__scans", distinct=True),
            badge_unique_ip_count=Count(
                "qrcode__scans__ip_address", distinct=True
            ),
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Supervisor)
class SupervisorAdmin(admin.ModelAdmin):
    list_per_page = 25
    """Assigns which unit a user supervises for QR code purposes. This
    model IS the access-control mechanism for QRCodeAdmin's scoping,
    so — regardless of any Django model permissions a user might be
    granted — only superusers may view or edit it."""

    list_display = ("user", "unit")
    autocomplete_fields = ("user", "department", "service_unit", "research_unit")
    search_fields = (
        "user__email",
        "department__name",
        "service_unit__name",
        "research_unit__name",
    )

    @admin.display(description="Unit")
    def unit(self, obj):
        return obj.unit or "—"

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ---------------------------------------------------------------------
# QR Supervisor site — same QRCodeAdmin (unit-scoped CRUD), plus a
# read-only unit roster so a supervisor can see who exists before
# generating a badge for them.
# ---------------------------------------------------------------------

class SupervisorEmployeeAdmin(admin.ModelAdmin):
    list_per_page = 25
    """Read-only roster, scoped to the supervisor's own unit. Editing
    Employee records happens in the main staff admin, not here. Gated
    on holding a Supervisor row rather than Django's 'staff' app
    permissions — this site is intentionally self-contained."""

    list_display = ("display_name", "staff_id", "unit", "has_qr_code", "is_active")
    search_fields = ("user__profile__given_name", "user__profile__family_name", "staff_id", "user__email")
    list_select_related = ("user", "user__profile", "department", "service_unit", "research_unit")
    ordering = ("user__profile__family_name", "user__profile__given_name")

    def _is_supervisor(self, request):
        if not request.user.is_authenticated:
            return False
        return request.user.is_superuser or Supervisor.objects.filter(user=request.user).exists()

    def has_module_permission(self, request):
        return self._is_supervisor(request)

    def has_view_permission(self, request, obj=None):
        return self._is_supervisor(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        q = Supervisor.unit_q_for(request.user)
        if q is False:
            return qs.none()
        return qs.filter(q)

    @admin.display(description="Has QR Code", boolean=True)
    def has_qr_code(self, obj):
        return bool(obj.qr_code_image)

    @admin.display(description="Name")
    def display_name(self, obj):
        return obj.user.profile.display_name if hasattr(obj.user, "profile") else "—"


qr_admin_site.register(QRCode, QRCodeAdmin)
qr_admin_site.register(Employee, SupervisorEmployeeAdmin)
qr_admin_site.register(ScanLog, ScanLogAdmin)