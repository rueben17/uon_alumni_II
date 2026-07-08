from django import forms
from django.contrib import admin, messages

from apps.qr_manager.models import QRCode, ScanLog, Supervisor
from apps.qr_manager.qr_admin_site import qr_admin_site
from apps.staff.models import Employee


def _regenerate_employee_badge(qr_code):
    """Rebuild and store the badge PNG for an employee-linked code."""
    qr_code.generate_qr(force=True)


class EmployeeChoiceField(forms.ModelChoiceField):
    """Richer labels for the employee dropdown: name — email — unit."""

    def label_from_instance(self, obj):
        unit = obj.unit or "no unit"
        return f"{obj.full_name} — {obj.email} — {unit}"


@admin.register(QRCode)
class QRCodeAdmin(admin.ModelAdmin):
    list_display = (
        "holder",
        "qr_type",
        "status",
        "issued_at",
        "expires_at",
        "is_active",
    )
    list_filter = ("qr_type", "is_active")
    search_fields = (
        "employee__given_name",
        "employee__family_name",
        "employee__staff_id",
        "label",
    )
    readonly_fields = ("id", "token", "issued_at", "status")
    actions = ("revoke_codes", "reactivate_codes", "rotate_tokens")

    # ---------------------------------------------------------------
    # Unit scoping — a non-superuser can only manage QR codes for
    # employees in a unit they supervise (see Supervisor model).
    # Superusers are unrestricted.
    # ---------------------------------------------------------------

    def _supervisor_unit_q(self, request, prefix=""):
        """None = unrestricted (superuser). False = scoped to nothing
        (no Supervisor rows). Otherwise a Q for `prefix`."""
        if request.user.is_superuser:
            return None
        return Supervisor.unit_q_for(request.user, prefix=prefix)

    def _object_in_scope(self, request, obj):
        """Supervisors may only touch employee-linked codes in their
        own unit — visitor/event codes with no employee are
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
        if q is None:
            return qs
        if q is False:
            return qs.none()
        return qs.filter(q)

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
        work': create (or edit) a code with an employee attached and
        the badge image is built immediately — no separate action
        needed. This is the hook the old signal used to provide."""
        super().save_model(request, obj, form, change)
        if obj.employee_id:
            obj.generate_qr(force=True)
            self.message_user(
                request,
                f"QR badge image generated for {obj.employee.full_name}.",
                messages.SUCCESS,
            )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # OneToOne fields route through here too. select_related keeps
        # the rich labels from firing 4 queries per employee.
        if db_field.name == "employee":
            queryset = Employee.objects.select_related(
                "user", "department", "service_unit", "research_unit"
            ).order_by("family_name", "given_name")
            q = self._supervisor_unit_q(request)
            if q is False:
                queryset = queryset.none()
            elif q is not None:
                queryset = queryset.filter(q)
            kwargs["queryset"] = queryset
            kwargs["form_class"] = EmployeeChoiceField
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Holder")
    def holder(self, obj):
        return obj.employee.full_name if obj.employee else (obj.label or "—")

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
        description="Rotate token (lost badge) — regenerates employee badge image"
    )
    def rotate_tokens(self, request, queryset):
        rotated = 0
        for qr in queryset:
            qr.rotate_token()
            # Keep the stored badge image in sync with the new token —
            # otherwise Employee.qr_code_image shows a QR whose token
            # no longer matches. Non-employee codes store no image.
            if qr.employee_id:
                _regenerate_employee_badge(qr)
            rotated += 1
        self.message_user(
            request,
            f"Rotated {rotated} token(s). Previously printed copies now fail "
            f"the token check; employee badge images were regenerated for "
            f"reprinting.",
            messages.SUCCESS,
        )


@admin.register(ScanLog)
class ScanLogAdmin(admin.ModelAdmin):
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
    )
    list_filter = ("result",)
    date_hierarchy = "scanned_at"
    search_fields = (
        "qrcode__employee__given_name",
        "qrcode__employee__family_name",
        "qrcode__employee__user__email",
    )
    list_select_related = (
        "qrcode__employee__user",
        "qrcode__employee__department",
    )
    readonly_fields = [f.name for f in ScanLog._meta.fields]

    @admin.display(description="Scanned badge of")
    def holder(self, obj):
        if obj.qrcode and obj.qrcode.employee:
            return obj.qrcode.employee.full_name
        if obj.qrcode:
            return obj.qrcode.label or "unassigned"
        return "— unknown QR —"

    @admin.display(description="Email")
    def holder_email(self, obj):
        if obj.qrcode and obj.qrcode.employee:
            return obj.qrcode.employee.user.email
        return "—"

    @admin.display(description="Department / Unit")
    def holder_department(self, obj):
        if obj.qrcode and obj.qrcode.employee:
            return obj.qrcode.employee.unit or "—"
        return "—"

    def _is_supervisor(self, request):
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
        if request.user.is_superuser:
            return qs
        q = Supervisor.unit_q_for(request.user, prefix="qrcode__employee__")
        if q is False:
            return qs.none()
        return qs.filter(q)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Supervisor)
class SupervisorAdmin(admin.ModelAdmin):
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
    """Read-only roster, scoped to the supervisor's own unit. Editing
    Employee records happens in the main staff admin, not here. Gated
    on holding a Supervisor row rather than Django's 'staff' app
    permissions — this site is intentionally self-contained."""

    list_display = ("full_name", "staff_id", "unit", "has_qr_code", "is_active")
    search_fields = ("given_name", "family_name", "staff_id", "user__email")
    list_select_related = ("user", "department", "service_unit", "research_unit")
    ordering = ("family_name", "given_name")

    def _is_supervisor(self, request):
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


qr_admin_site.register(QRCode, QRCodeAdmin)
qr_admin_site.register(Employee, SupervisorEmployeeAdmin)
qr_admin_site.register(ScanLog, ScanLogAdmin)