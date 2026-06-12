# staff/admin.py
from django.contrib import admin
from django.utils.html import format_html
from apps.staff.models import Faculty, Department, ServiceUnit, ResearchUnit

# staff/admin.py (at top)
admin.site.site_header = "University of Nairobi Alumni Admin"
admin.site.site_title = "UoN Alumni Admin Portal"
admin.site.index_title = "Welcome to UoN Alumni Management System"

# -------------------------------------------------------------------
# Faculty Admin
# -------------------------------------------------------------------
@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ['faculty_name', 'slug', 'department_count', 'id']
    list_display_links = ['faculty_name']
    search_fields = ['faculty_name', 'description']
    prepopulated_fields = {'slug': ('faculty_name',)}
    readonly_fields = ['slug']
    list_per_page = 15
    ordering = ['faculty_name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('faculty_name', 'description')
        }),
        ('Slug', {
            'fields': ('slug',),
            'classes': ('collapse',)
        }),
    )
    
    def department_count(self, obj):
        return obj.departments.count()
    department_count.short_description = 'Departments'
    department_count.admin_order_field = 'departments__count'

# -------------------------------------------------------------------
# Department Admin
# -------------------------------------------------------------------
class DepartmentInline(admin.TabularInline):
    model = Department
    extra = 1
    fields = ['name', 'slug']
    readonly_fields = ['slug']
    show_change_link = True

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'faculty_link', 'slug', 'id']
    list_display_links = ['name']
    list_filter = ['faculty']
    search_fields = ['name', 'faculty__faculty_name']
    readonly_fields = ['slug']
    autocomplete_fields = ['faculty']
    list_per_page = 15
    ordering = ['faculty__faculty_name', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'faculty', 'description')
        }),
        ('Slug', {
            'fields': ('slug',),
            'classes': ('collapse',)
        }),
    )
    
    def faculty_link(self, obj):
        return format_html('<a href="/admin/staff/faculty/{}/change/">{}</a>', 
                          obj.faculty.id, obj.faculty.faculty_name)
    faculty_link.short_description = 'Faculty'
    faculty_link.admin_order_field = 'faculty__faculty_name'

# -------------------------------------------------------------------
# Service Unit Admin
# -------------------------------------------------------------------
@admin.register(ServiceUnit)
class ServiceUnitAdmin(admin.ModelAdmin):
    list_display = ['name', 'unit_type', 'slug', 'id']
    list_display_links = ['name']
    list_filter = ['unit_type']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['slug']
    list_per_page = 15
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'unit_type', 'description')
        }),
        ('Slug', {
            'fields': ('slug',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_office', 'mark_as_directorate']
    
    def mark_as_office(self, request, queryset):
        updated = queryset.update(unit_type='OFFICE')
        self.message_user(request, f'{updated} service unit(s) marked as Office.')
    mark_as_office.short_description = 'Mark selected as Office'
    
    def mark_as_directorate(self, request, queryset):
        updated = queryset.update(unit_type='DIRECTORATE')
        self.message_user(request, f'{updated} service unit(s) marked as Directorate.')
    mark_as_directorate.short_description = 'Mark selected as Directorate'

# -------------------------------------------------------------------
# Research Unit Admin
# -------------------------------------------------------------------
@admin.register(ResearchUnit)
class ResearchUnitAdmin(admin.ModelAdmin):
    list_display = ['name', 'unit_type', 'parent_faculty_link', 'slug', 'id']
    list_display_links = ['name']
    list_filter = ['unit_type', 'parent_faculty']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['slug']
    autocomplete_fields = ['parent_faculty']
    list_per_page = 15
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'unit_type', 'description')
        }),
        ('Relationship', {
            'fields': ('parent_faculty',),
            'classes': ('collapse',),
            'description': 'Optional: If this research unit belongs to a faculty'
        }),
        ('Slug', {
            'fields': ('slug',),
            'classes': ('collapse',)
        }),
    )
    
    def parent_faculty_link(self, obj):
        if obj.parent_faculty:
            return format_html('<a href="/admin/staff/faculty/{}/change/">{}</a>', 
                              obj.parent_faculty.id, obj.parent_faculty.faculty_name)
        return '-'
    parent_faculty_link.short_description = 'Parent Faculty'
    parent_faculty_link.admin_order_field = 'parent_faculty__faculty_name'
    
    actions = ['mark_as_institute', 'mark_as_centre']
    
    def mark_as_institute(self, request, queryset):
        updated = queryset.update(unit_type='INSTITUTE')
        self.message_user(request, f'{updated} research unit(s) marked as Institute.')
    mark_as_institute.short_description = 'Mark selected as Institute'
    
    def mark_as_centre(self, request, queryset):
        updated = queryset.update(unit_type='CENTRE')
        self.message_user(request, f'{updated} research unit(s) marked as Centre.')
    mark_as_centre.short_description = 'Mark selected as Centre'