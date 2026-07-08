# apps/staff/admin.py — updated to the CURRENT Employee model.
# Structure and conveniences kept from your old admin (date_hierarchy,
# autocomplete, counts, fieldsets); every dead field reference fixed:
#   title → honorific          first_name → given_name
#   last_name → family_name    qr_image → qr_code_image
#   email_address, address_line_1/2, supervisor, editable full_name → removed
# Position keeps .title (confirmed by system check).

from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from apps.qr_manager.models import QRCode
from apps.staff.models import (
    Department,
    Employee,
    Faculty,
    Position,
    ResearchUnit,
    ServiceUnit,
)


class DepartmentInline(admin.TabularInline):
    model = Department
    extra = 0
    fields = ("name",)
    show_change_link = True


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ("faculty_name", "department_count")
    search_fields = ("faculty_name",)
    ordering = ("faculty_name",)
    inlines = [DepartmentInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            dept_count=Count("departments")
        )

    @admin.display(description="Departments")
    def department_count(self, obj):
        return obj.dept_count


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "faculty", "employee_count")
    list_filter = ("faculty",)
    search_fields = ("name", "faculty__faculty_name")
    ordering = ("faculty__faculty_name", "name")
    autocomplete_fields = ("faculty",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            emp_count=Count("employees")
        )

    @admin.display(description="Employees")
    def employee_count(self, obj):
        return obj.emp_count


@admin.register(ServiceUnit)
class ServiceUnitAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(ResearchUnit)
class ResearchUnitAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
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
    list_per_page = 10

    list_display = (
        "staff_id",
        "user__email",
        "honorific",
        "given_name",
        "family_name",
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
        "given_name",
        "middle_name",
        "family_name",
        "user__email",
    )
    ordering = ("family_name", "given_name")
    autocomplete_fields = (
        "department",
        "service_unit",
        "research_unit",
        "position",
    )
    list_select_related = (
        "user",
        "department",
        "service_unit",
        "research_unit",
        "position",
    )

    fieldsets = (
        ("Basic Information", {
            "fields": (
                "user",
                "honorific",
                "given_name",
                "middle_name",
                "family_name",
                "national_id",
                "staff_id",
                "employment_type",
                "photo",
            ),
        }),
        ("Contact Information", {
            "fields": (
                "alt_email_address",
                "phone_number",
                "alt_phone_number",
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
            "fields": ("date_joined", "date_of_birth"),
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