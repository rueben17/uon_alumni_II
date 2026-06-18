# apps/staff/admin.py
from django.contrib import admin
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.staff.models import (
    Department,
    Employee,
    Faculty,
    Position,
    ResearchUnit,
    ServiceUnit,
)

admin.site.site_header = "University of Nairobi Staff Admin"
admin.site.site_title  = "UoN Staff Admin Portal"
admin.site.index_title = "Welcome to UoN Staff Management System"


# -------------------------------------------------------------------
# Faculty
# -------------------------------------------------------------------

@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display        = ["faculty_name", "slug", "department_count"]
    list_display_links  = ["faculty_name"]
    search_fields       = ["faculty_name", "description"]
    readonly_fields     = ["slug"]
    list_per_page       = 20
    ordering            = ["faculty_name"]

    fieldsets = (
        (_("Basic Information"), {"fields": ("faculty_name", "description")}),
        (_("Slug"), {"fields": ("slug",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("departments")

    @admin.display(description=_("Departments"), ordering="departments__count")
    def department_count(self, obj):
        count = obj.departments.count()
        url = (
            reverse("admin:staff_department_changelist")
            + f"?faculty__id__exact={obj.pk}"
        )
        return format_html('<a href="{}">{}</a>', url, count)


# -------------------------------------------------------------------
# Department
# -------------------------------------------------------------------

class DepartmentInline(admin.TabularInline):
    model           = Department
    extra           = 1
    fields          = ["name", "slug", "description"]
    readonly_fields = ["slug"]
    show_change_link = True


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display       = ["name", "faculty_link", "slug", "employee_count"]
    list_display_links = ["name"]
    list_filter        = ["faculty"]
    search_fields      = ["name", "faculty__faculty_name"]
    readonly_fields    = ["slug"]
    autocomplete_fields = ["faculty"]
    list_per_page      = 20
    ordering           = ["faculty__faculty_name", "name"]

    fieldsets = (
        (_("Basic Information"), {"fields": ("name", "faculty", "description")}),
        (_("Slug"), {"fields": ("slug",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("faculty").prefetch_related("employees")

    @admin.display(description=_("Faculty"), ordering="faculty__faculty_name")
    def faculty_link(self, obj):
        url = reverse("admin:staff_faculty_change", args=[obj.faculty.pk])
        return format_html('<a href="{}">{}</a>', url, obj.faculty.faculty_name)

    @admin.display(description=_("Staff"))
    def employee_count(self, obj):
        count = obj.employees.count()
        url = (
            reverse("admin:staff_employee_changelist")
            + f"?department__id__exact={obj.pk}"
        )
        return format_html('<a href="{}">{}</a>', url, count)


# -------------------------------------------------------------------
# Service Unit
# -------------------------------------------------------------------

@admin.register(ServiceUnit)
class ServiceUnitAdmin(admin.ModelAdmin):
    list_display       = ["name", "unit_type", "slug", "employee_count"]
    list_display_links = ["name"]
    list_filter        = ["unit_type"]
    search_fields      = ["name", "description"]
    readonly_fields    = ["slug"]
    list_per_page      = 20
    ordering           = ["name"]
    actions            = ["mark_as_office", "mark_as_directorate"]

    fieldsets = (
        (_("Basic Information"), {"fields": ("name", "unit_type", "description")}),
        (_("Slug"), {"fields": ("slug",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("employees")

    @admin.display(description=_("Staff"))
    def employee_count(self, obj):
        count = obj.employees.count()
        url = (
            reverse("admin:staff_employee_changelist")
            + f"?service_unit__id__exact={obj.pk}"
        )
        return format_html('<a href="{}">{}</a>', url, count)

    @admin.action(description=_("Mark selected as Office"))
    def mark_as_office(self, request, queryset):
        updated = queryset.update(unit_type=ServiceUnit.UnitTypeChoices.OFFICE)
        self.message_user(request, _(f"{updated} unit(s) marked as Office."))

    @admin.action(description=_("Mark selected as Directorate"))
    def mark_as_directorate(self, request, queryset):
        updated = queryset.update(unit_type=ServiceUnit.UnitTypeChoices.DIRECTORATE)
        self.message_user(request, _(f"{updated} unit(s) marked as Directorate."))


# -------------------------------------------------------------------
# Research Unit
# -------------------------------------------------------------------

@admin.register(ResearchUnit)
class ResearchUnitAdmin(admin.ModelAdmin):
    list_display        = ["name", "unit_type", "parent_faculty_link", "slug", "employee_count"]
    list_display_links  = ["name"]
    list_filter         = ["unit_type", "parent_faculty"]
    search_fields       = ["name", "description"]
    readonly_fields     = ["slug"]
    autocomplete_fields = ["parent_faculty"]
    list_per_page       = 20
    ordering            = ["name"]
    actions             = ["mark_as_institute", "mark_as_centre"]

    fieldsets = (
        (_("Basic Information"), {"fields": ("name", "unit_type", "description")}),
        (
            _("Parent Faculty"),
            {
                "fields": ("parent_faculty",),
                "classes": ("collapse",),
                "description": _("Optional — only if this unit belongs to a faculty."),
            },
        ),
        (_("Slug"), {"fields": ("slug",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("parent_faculty")
            .prefetch_related("employees")
        )

    @admin.display(description=_("Parent Faculty"), ordering="parent_faculty__faculty_name")
    def parent_faculty_link(self, obj):
        if not obj.parent_faculty:
            return "—"
        url = reverse("admin:staff_faculty_change", args=[obj.parent_faculty.pk])
        return format_html('<a href="{}">{}</a>', url, obj.parent_faculty.faculty_name)

    @admin.display(description=_("Staff"))
    def employee_count(self, obj):
        count = obj.employees.count()
        url = (
            reverse("admin:staff_employee_changelist")
            + f"?research_unit__id__exact={obj.pk}"
        )
        return format_html('<a href="{}">{}</a>', url, count)

    @admin.action(description=_("Mark selected as Institute"))
    def mark_as_institute(self, request, queryset):
        updated = queryset.update(unit_type=ResearchUnit.UnitTypeChoices.INSTITUTE)
        self.message_user(request, _(f"{updated} unit(s) marked as Institute."))

    @admin.action(description=_("Mark selected as Centre"))
    def mark_as_centre(self, request, queryset):
        updated = queryset.update(unit_type=ResearchUnit.UnitTypeChoices.CENTRE)
        self.message_user(request, _(f"{updated} unit(s) marked as Centre."))


# -------------------------------------------------------------------
# Position
# -------------------------------------------------------------------

@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display       = ["title", "level", "employee_count"]
    list_display_links = ["title"]
    search_fields      = ["title", "description"]
    list_filter        = ["level"]
    ordering           = ["-level", "title"]
    list_per_page      = 20

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("employees")

    @admin.display(description=_("Staff in Position"))
    def employee_count(self, obj):
        count = obj.employees.count()
        url = (
            reverse("admin:staff_employee_changelist")
            + f"?position__id__exact={obj.pk}"
        )
        return format_html('<a href="{}">{}</a>', url, count)


# -------------------------------------------------------------------
# Employee
# -------------------------------------------------------------------

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = [
        "display_name",
        "staff_id",
        "staff_track",
        "academic_rank",
        "unit_display",
        "position",
        "employment_type",
        "is_active",
        "qr_preview",
        "photo_preview",
    ]
    list_display_links  = ["display_name"]
    list_filter         = [
        "staff_track", "academic_rank", "employment_type",
        "is_active", "department", "service_unit", "research_unit"
    ]
    search_fields       = ["given_name", "family_name", "staff_id", "user__email"]
    readonly_fields     = [
        "slug", "created_at", "updated_at", "qr_preview",
        "email_display", "photo_preview"
    ]
    autocomplete_fields = ["department", "service_unit", "research_unit", "position"]
    list_per_page       = 25
    ordering            = ["family_name", "given_name"]
    actions             = ["generate_qr_codes"]

    fieldsets = (
        (_("Account"), {
            "fields": ("user", "email_display", "staff_id", "national_id"),
        }),
        (_("Personal Details"), {
            "fields": (
                "honorific", "academic_rank",
                "given_name", "middle_name", "family_name",
                "date_of_birth",
            ),
        }),
        (_("Profile Photos"), {
            "fields": ("photo", "google_photo_url", "photo_preview"),
            "description": _("Custom uploaded photo takes precedence over Google photo."),
        }),
        (_("Contact"), {
            "fields": ("alt_email_address", "phone_number", "alt_phone_number"),
        }),
        (_("Organisational"), {
            "fields": (
                "staff_track",
                "department",
                "service_unit",
                "research_unit",
                "position",
                "employment_type",
                "date_joined",
                "is_active",
            ),
        }),
        (_("QR Code"), {
            "fields": ("qr_code_image", "qr_preview"),
            "classes": ("collapse",),
        }),
        (_("System"), {
            "fields": ("slug", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related(
                "user", "department__faculty",
                "service_unit", "research_unit", "position",
            )
        )

    # ------------------------------------------------------------------
    # Readonly display helpers
    # ------------------------------------------------------------------
    @admin.display(description=_("University Email"))
    def email_display(self, obj):
        return obj.user.email

    @admin.display(description=_("Unit"))
    def unit_display(self, obj):
        unit = obj.unit
        return str(unit) if unit else "—"

    @admin.display(description=_("QR Code"))
    def qr_preview(self, obj):
        if obj.qr_code_image:
            return format_html(
                '<img src="{}" style="height:120px; width:120px; object-fit:contain;" />',
                obj.qr_code_image.url,
            )
        return _("Not generated yet")

    @admin.display(description=_("Photo Preview"))
    def photo_preview(self, obj):
        if obj.photo and obj.photo.url:
            return format_html(
                '<img src="{}" style="height:80px; width:80px; border-radius:50%; object-fit:cover;" />',
                obj.photo.url,
            )
        if obj.google_photo_url:
            return format_html(
                '<img src="{}" style="height:80px; width:80px; border-radius:50%; object-fit:cover;" />',
                obj.google_photo_url,
            )
        return "—"

    # ------------------------------------------------------------------
    # Change-page QR button
    # ------------------------------------------------------------------
    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_generate_qr_button"] = True
        return super().change_view(request, object_id, form_url, extra_context)

    def response_change(self, request, obj):
        if "_generate_qr" in request.POST:
            self._do_generate_qr(request, obj)
            return super().response_change(request, obj)
        return super().response_change(request, obj)

    def _do_generate_qr(self, request, employee):
        from apps.qr_manager.models import QRCode
        import secrets

        if not employee.profile_is_complete:
            self.message_user(
                request,
                _("Profile is incomplete — QR code cannot be generated yet."),
                level=messages.WARNING,
            )
            return

        qr, created = QRCode.objects.get_or_create(
            employee=employee,
            defaults={"signed_token": secrets.token_urlsafe(32)},
        )
        employee._skip_qr_signal = True
        url = qr.generate_qr(request=request, force=True)
        employee._skip_qr_signal = False

        if url:
            self.message_user(request, _("QR code generated successfully."))
        else:
            self.message_user(
                request,
                _("QR code generation failed. Check logs for details."),
                level=messages.ERROR,
            )

    # ------------------------------------------------------------------
    # Bulk action
    # ------------------------------------------------------------------
    @admin.action(description=_("Generate QR codes for selected employees"))
    def generate_qr_codes(self, request, queryset):
        from apps.qr_manager.models import QRCode
        import secrets

        success, skipped = 0, 0
        for employee in queryset.select_related("user", "department__faculty", "service_unit", "research_unit"):
            if not employee.profile_is_complete:
                skipped += 1
                continue
            qr, created = QRCode.objects.get_or_create(
                employee=employee,
                defaults={"signed_token": secrets.token_urlsafe(32)},
            )
            employee._skip_qr_signal = True
            result = qr.generate_qr(request=request, force=True)
            employee._skip_qr_signal = False
            if result:
                success += 1
            else:
                skipped += 1

        self.message_user(
            request,
            _("QR codes generated: %(success)d. Skipped (incomplete profile): %(skipped)d.")
            % {"success": success, "skipped": skipped},
            level=messages.SUCCESS if success else messages.WARNING,
        )