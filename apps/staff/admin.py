# apps/staff/admin.py
#
# NOTE (docs/rebuild-schema.md, 2026-08-05): Employee no longer holds
# personal data (honorific/name/DOB/national ID/photo) -- that's on
# UserProfile now. EmployeeAdmin edits it via a UserProfile inline
# instead of Employee's own fields. Position keeps .title (confirmed by
# system check).

from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from apps.qr_manager.models import QRCode
from apps.staff.models import (
    Employee,
    Position,
    ResearchUnit,
    ServiceUnit,
)

# Faculty/Department admin moved to apps/home/admin.py alongside the
# models themselves (2026-08-06) -- see apps/home/models.py's docstring.


@admin.register(ServiceUnit)
class ServiceUnitAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(ResearchUnit)
class ResearchUnitAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ("title", "employee_count")
    search_fields = ("title",)
    ordering = ("title",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            emp_count=Count("employees")
        )

    @admin.display(description="Employees")
    def employee_count(self, obj):
        return obj.emp_count


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_per_page = 25

    list_display = (
        "staff_id",
        "user",
        "display_name",
        "staff_track",
        "unit",
        "qr_code_tag",
        "profile_is_complete",
        "is_active",
    )
    list_filter = (
        "staff_track",
        "employment_type",
        "is_active",
        "department",
        "position",
    )
    search_fields = (
        "staff_id",
        "user__profile__given_name",
        "user__profile__middle_name",
        "user__profile__family_name",
        "user__email",
    )
    ordering = ("user__profile__family_name", "user__profile__given_name")
    autocomplete_fields = (
        "department",
        "service_unit",
        "research_unit",
        "position",
    )
    list_select_related = (
        "user",
        "user__profile",
        "department",
        "service_unit",
        "research_unit",
        "position",
    )

    fieldsets = (
        ("Basic Information", {
            "fields": (
                "user",
                "staff_id",
                "employment_type",
            ),
        }),
        ("Organizational Structure", {
            "fields": (
                "staff_track",
                "department",
                "service_unit",
                "research_unit",
                "position",
                "academic_rank",
            ),
        }),
        ("Dates", {
            "fields": ("employed_on",),
        }),
        ("Status", {
            "fields": ("is_active", "profile_is_complete"),
        }),
        ("QR Code", {
            "fields": ("qr_code_tag", "qr_code_image"),
        }),
    )

    readonly_fields = ("profile_is_complete", "qr_code_tag")
    actions = ("generate_qr_badge",)
    # Personal data (name/DOB/national ID/photo) is edited via the User
    # admin's UserProfile inline, not here -- UserProfile has no FK to
    # Employee to inline against (only to User).

    @admin.display(description="Name")
    def display_name(self, obj):
        return obj.user.profile.display_name if hasattr(obj.user, "profile") else "—"

    # ─────────── QR badge ───────────

    @admin.display(description="QR Code")
    def qr_code_tag(self, obj):
        if obj.qr_code_image:
            url = obj.qr_code_image.url
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">'
                '<img src="{}" style="height:160px;" alt="QR badge"/></a>',
                url,
                url,
            )
        return "—"

    @admin.action(description="Generate / refresh ID badge QR")
    def generate_qr_badge(self, request, queryset):
        done, skipped = 0, 0
        for employee in queryset:
            if not employee.profile_is_complete:
                skipped += 1
                continue
            qr, _ = QRCode.objects.get_or_create(employee=employee)
            qr.generate_qr(force=True)
            done += 1
        if done:
            self.message_user(
                request, f"Generated {done} badge(s).", messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} — profile incomplete.",
                messages.WARNING,
            )