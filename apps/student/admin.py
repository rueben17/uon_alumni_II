from django.contrib import admin

from apps.student.models import InterviewScoreSheet, ScholarshipApplication, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ("registration_no", "user", "faculty", "programme", "status", "year_of_study")
    list_filter = ("status", "faculty", "county")
    search_fields = (
        "registration_no", "student_email",
        "user__email", "user__profile__given_name", "user__profile__family_name",
    )
    ordering = ("registration_no",)
    autocomplete_fields = ("user", "faculty", "programme")


@admin.register(ScholarshipApplication)
class ScholarshipApplicationAdmin(admin.ModelAdmin):
    date_hierarchy = "submitted_at"
    list_per_page = 25
    list_display = (
        "registration_number", "surname", "first_name", "faculty", "department",
        "academic_level", "county_of_residence", "submitted_at",
    )
    list_filter = ("academic_level", "gender", "faculty", "county_of_residence", "submitted_at")
    search_fields = (
        "registration_number", "surname", "first_name", "middle_name", "email", "mobile_no",
    )
    ordering = ("-submitted_at",)
    autocomplete_fields = ("student", "faculty", "department")


@admin.register(InterviewScoreSheet)
class InterviewScoreSheetAdmin(admin.ModelAdmin):
    date_hierarchy = "interview_date"
    list_per_page = 25
    list_display = ("application", "evaluator", "interview_date", "verdict", "total_score_display")
    list_filter = ("verdict", "parental_status", "received_other_funding", "interview_date")
    search_fields = (
        "application__registration_number", "application__surname", "application__first_name",
        "prepared_by_name",
    )
    ordering = ("-interview_date",)
    autocomplete_fields = ("application", "evaluator")

    @admin.display(description="Total score")
    def total_score_display(self, obj):
        return f"{obj.total_score}/50"
