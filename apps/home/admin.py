from django.contrib import admin
from apps.home.models import*
from django.db.models import Count
from django.utils.html import format_html
from import_export import resources, fields
from import_export.admin import ExportMixin

from apps.home.membership_admin_site import membership_admin_site
from apps.home import services
# Register your models here.

# ─────────────────────────────────────────────
# Spreadsheet export (todo.md 1.8) -- staff/superadmin only by construction:
# this lives inside Django admin, which already requires is_staff=True to
# log in at all, same gate as every other screen here. Export-only for now
# (ExportMixin, not ImportMixin) -- the real legacy-membership *import* is
# its own Resource, still blocked on seeing the actual data file.
# ─────────────────────────────────────────────

class MembershipResource(resources.ModelResource):
    email = fields.Field(column_name='Email')
    full_name = fields.Field(column_name='Full Name')
    phone = fields.Field(column_name='Phone')
    tier_name = fields.Field(column_name='Tier')
    faculty = fields.Field(column_name='Faculty')

    class Meta:
        model = Membership
        fields = (
            'membership_number', 'email', 'full_name', 'phone', 'tier_name',
            'faculty', 'status', 'is_lifetime', 'started_on', 'expires_on',
            'subscription_amount', 'payment_frequency', 'legacy_signed',
            'card_issued', 'certificate_issued', 'created_at',
        )
        export_order = fields

    def dehydrate_email(self, obj):
        return obj.user.email

    def dehydrate_full_name(self, obj):
        profile = getattr(obj.user, 'profile', None)
        return profile.display_name if profile else ''

    def dehydrate_phone(self, obj):
        return str(obj.user.phone) if obj.user.phone else ''

    def dehydrate_tier_name(self, obj):
        return obj.tier.name if obj.tier_id else ''

    def dehydrate_faculty(self, obj):
        alumni = getattr(obj.user, 'alumni_profile', None)
        return alumni.faculty.faculty_name if alumni and alumni.faculty_id else ''


class AlumniProfileResource(resources.ModelResource):
    email = fields.Field(column_name='Email')
    full_name = fields.Field(column_name='Full Name')
    phone = fields.Field(column_name='Phone')
    faculty_name = fields.Field(column_name='Faculty')
    qualification_name = fields.Field(column_name='Qualification')
    current_membership = fields.Field(column_name='Current Membership')

    class Meta:
        model = AlumniProfile
        fields = (
            'email', 'full_name', 'phone', 'faculty_name', 'qualification_name',
            'graduation_year', 'current_employer', 'employment_position',
            'current_membership', 'is_active', 'registration_date',
        )
        export_order = fields

    def dehydrate_email(self, obj):
        return obj.user.email

    def dehydrate_full_name(self, obj):
        return obj.user.profile.display_name if hasattr(obj.user, 'profile') else ''

    def dehydrate_phone(self, obj):
        return str(obj.user.phone) if obj.user.phone else ''

    def dehydrate_faculty_name(self, obj):
        return obj.faculty.faculty_name if obj.faculty_id else ''

    def dehydrate_qualification_name(self, obj):
        return obj.qualification.name if obj.qualification_id else ''

    def dehydrate_current_membership(self, obj):
        membership = Membership.objects.current_for(obj.user)
        return f"{membership.tier.name} ({membership.get_status_display()})" if membership else ''

# ─────────────────────────────────────────────
# Faculty / Department -- moved from apps.staff.admin (2026-08-06), same
# move as the models themselves. See apps/home/models.py's docstring.
# ─────────────────────────────────────────────

class DepartmentInline(admin.TabularInline):
    model = Department
    extra = 0
    fields = ("name",)
    show_change_link = True


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_per_page = 25
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
    list_per_page = 25
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

# ─────────────────────────────────────────────
# Gallery inlines -- Images has one FK per attachable model (todo.md
# 0.3b: deliberately not a single generic FK). fk_name is explicit per
# subclass so each parent's admin only ever creates/edits rows through
# its own FK, never leaves the other four null-by-omission.
# ─────────────────────────────────────────────

class ImagesInline(admin.TabularInline):
    model = Images
    extra = 1
    fields = ['image', 'alt_text']


class ArticleImagesInline(ImagesInline):
    fk_name = 'article'


class EventImagesInline(ImagesInline):
    fk_name = 'event'


class ChapterImagesInline(ImagesInline):
    fk_name = 'chapter'


class PublicationImagesInline(ImagesInline):
    fk_name = 'publication'


class InMemoriamImagesInline(ImagesInline):
    fk_name = 'in_memoriam'


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'type', 'page_key', 'chapter', 'is_published', 'created_at', 'slug', 'is_feature', 'is_highlighted']
    prepopulated_fields = { 'slug': ('title',), }
    list_filter = ['type', 'is_published', 'created_at', 'is_feature', 'is_highlighted', 'chapter']
    search_fields = ['title', 'body']
    readonly_fields = ['published_at']
    list_per_page = 25
    inlines = [ArticleImagesInline]

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'event_type', 'created_at', 'date_updated']
    list_filter = ['event_type']
    prepopulated_fields = { 'slug': ('title',), }
    list_per_page = 25
    inlines = [EventImagesInline]



@admin.register(Images)
class ImagesAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['__str__', 'chapter', 'article', 'event', 'publication', 'in_memoriam', 'image', 'created_at']
    search_fields = ['article__title', 'chapter__name', 'event__title', 'publication__title']
    list_filter = [ 'chapter', 'created_at' ] #,


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['text', 'created_at']
    list_filter = [ 'created_at' ] #, 


@admin.register(CoreValue)
class CoreValueAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['name', 'order', 'is_active', 'created_at']
    list_editable = ['order', 'is_active']
    search_fields = ['name', 'description']
    prepopulated_fields = {}  # Add if you have slug field
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'order', 'is_active')
        }),
        ('Visual Elements', {
            'fields': ('svg_path', 'background_image', 'background_color'),
            'classes': ('collapse',)
        }),
    )



@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['name', 'faculty','year_launched', 'slug']
    list_filter = [ 'faculty' ] #,
    prepopulated_fields = { 'slug': ('name',)}
    inlines = [ChapterImagesInline]

@admin.register(Executive)
class ExecutiveAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['title', 'position', 'rank', 'first_name', 'middle_name', 'surname' ]

@admin.register(Secretariat)
class SecretariatAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['title', 'position', 'first_name', 'middle_name', 'surname' ]

@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_per_page = 25
    # Was not registered at all before -- content editors had no way to
    # enter a partner without a Django shell (content_todo.txt #5).
    list_display = ['title', 'relation', 'created_at']
    search_fields = ['title', 'relation']


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['title', 'category', 'visibility', 'document_date', 'is_approved']
    list_filter = ['category', 'visibility', 'is_approved']
    search_fields = ['title', 'volume', 'issue_number']
    date_hierarchy = 'document_date'
    readonly_fields = ['created_at', 'updated_at']
    inlines = [PublicationImagesInline]


@admin.register(InMemoriam)
class InMemoriamAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['given_name', 'family_name', 'birth_year', 'death_year', 'graduation_year', 'published']
    list_filter = ['published', 'faculty']
    search_fields = ['given_name', 'family_name']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [InMemoriamImagesInline]


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['title', 'company', 'is_approved', 'expires_on', 'is_live']
    list_filter = ['is_approved']
    search_fields = ['title', 'company']
    readonly_fields = ['created_at']

    @admin.display(description='Live', boolean=True)
    def is_live(self, obj):
        return obj.is_live


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['name', 'email', 'subject', 'is_read', 'created_at']
    list_filter = ['is_read']
    search_fields = ['name', 'email', 'subject', 'message']
    readonly_fields = ['name', 'email', 'subject', 'message', 'created_at']
    actions = ['mark_read']

    @admin.action(description="Mark selected messages as read")
    def mark_read(self, request, queryset):
        count = queryset.update(is_read=True)
        self.message_user(request, f"{count} message(s) marked read.")

    def has_add_permission(self, request):
        return False


class TierBenefitInline(admin.TabularInline):
    model = TierBenefit
    extra = 0
    fields = ['benefit', 'status', 'detail', 'display_order']
    ordering = ['display_order']
    # No autocomplete_fields: MembershipTierAdmin is dual-registered on
    # both the main site and membership_admin_site (below), and
    # autocomplete requires the target model's ModelAdmin on that SAME
    # site -- Benefit only has ~25 rows total, a plain <select> is fine.


@admin.register(MembershipTier)
class MembershipTierAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['name', 'fee', 'track', 'tier_type', 'duration_months', 'is_active']
    list_editable = ['fee', 'is_active']
    list_filter = ['tier_type', 'is_active']
    ordering = ['order']
    inlines = [TierBenefitInline]


@admin.register(Benefit)
class BenefitAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['name', 'axis', 'display_order']
    list_filter = ['axis']
    search_fields = ['name', 'description']
    ordering = ['display_order']


class PaymentInline(admin.TabularInline):
    model = Payment
    fields = ['amount', 'payment_method', 'payment_status', 'payment_date']
    readonly_fields = ['amount', 'payment_method', 'payment_status', 'payment_date']
    extra = 0
    can_delete = False


class AlumniQualificationInline(admin.TabularInline):
    model = AlumniQualification
    extra = 0
    fields = ['order', 'legacy_college', 'faculty', 'qualification', 'course_name_raw', 'graduation_year']


class AlumniEmploymentRecordInline(admin.TabularInline):
    model = AlumniEmploymentRecord
    extra = 0
    fields = ['order', 'organization', 'position']


@admin.register(AlumniProfile)
class AlumniProfileAdmin(ExportMixin, admin.ModelAdmin):
    resource_class = AlumniProfileResource
    # Personal data (name/DOB/national ID/contact) lives on UserProfile
    # now, edited via the User admin's inline -- not here. Membership
    # data (tier/status/expiry/issued items) lives on Membership,
    # registered separately below.
    list_display = ['id', 'display_name', 'user_email', 'current_membership_display']
    list_filter = ['graduation_institution', 'graduation_year']
    search_fields = [
        'user__profile__given_name', 'user__profile__family_name', 'user__email',
        'user__profile__national_id', 'student_reg_no',
    ]
    readonly_fields = ['registration_date', 'last_updated']
    list_per_page = 25
    fieldsets = (
        ('User Account', {
            'fields': ('user',)
        }),
        ('Alumni Details', {
            'fields': (
                'graduation_year', 'faculty', 'qualification', 'qualification_name_raw',
                'graduation_institution', 'other_institution_name',
                'other_institution_qualification', 'name_at_graduation', 'student_reg_no',
            )
        }),
        ('Employment', {
            'fields': ('current_employer', 'employment_position')
        }),
        ('Meta', {
            'fields': ('is_active', 'registration_date', 'last_updated')
        }),
    )
    inlines = [PaymentInline, AlumniQualificationInline, AlumniEmploymentRecordInline]

    @admin.display(description='Name')
    def display_name(self, obj):
        return obj.user.profile.display_name if hasattr(obj.user, 'profile') else '—'

    @admin.display(description='Email')
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description='Current Membership')
    def current_membership_display(self, obj):
        membership = Membership.objects.current_for(obj.user)
        if membership is None:
            return '—'
        return f"{membership.tier.name} ({membership.get_status_display()})"


@admin.register(Membership)
class MembershipAdmin(ExportMixin, admin.ModelAdmin):
    resource_class = MembershipResource
    list_per_page = 25
    list_display = [
        'user', 'tier', 'status', 'is_lifetime', 'expires_on',
        'membership_number', 'payment_frequency', 'amount_paid_display',
        'balance_due_display', 'overdue_display', 'legacy_signed',
    ]
    list_filter = ['status', 'is_lifetime', 'tier', 'payment_frequency', 'legacy_signed']
    search_fields = ['user__email', 'user__profile__given_name', 'user__profile__family_name', 'membership_number']
    readonly_fields = ['created_at', 'updated_at', 'balance_due_display']
    actions = ['issue_membership_card', 'mark_as_lifetime']

    @admin.display(description='Paid')
    def amount_paid_display(self, obj):
        return f"KES {obj.amount_paid}"

    @admin.display(description='Balance Due')
    def balance_due_display(self, obj):
        return f"KES {obj.balance_due}" if obj.is_installment_plan else '—'

    @admin.display(description='Overdue', boolean=True)
    def overdue_display(self, obj):
        return obj.is_overdue

    @admin.action(description="Issue membership card to selected")
    def issue_membership_card(self, request, queryset):
        count = queryset.update(card_issued=True)
        self.message_user(request, f"{count} membership card(s) marked as issued.")

    @admin.action(description="Mark as lifetime members")
    def mark_as_lifetime(self, request, queryset):
        count = queryset.update(is_lifetime=True, expires_on=None)
        self.message_user(request, f"{count} member(s) marked as lifetime.")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['id', 'alumni', 'amount', 'payment_method', 'payment_status', 'payment_date']
    list_filter = ['payment_status', 'payment_method']
    search_fields = [
        'transaction_reference', 'alumni__user__profile__given_name',
        'alumni__user__profile__family_name', 'alumni__user__email',
    ]
    readonly_fields = ['transaction_reference', 'created_at', 'updated_at']
    autocomplete_fields = ['membership']
    actions = ['mark_completed', 'mark_failed', 'mark_pending_verification', 'mark_refunded']
    fieldsets = (
        ('Alumni & Tier', {
            'fields': ('alumni', 'membership_tier', 'membership')
        }),
        ('Payment Info', {
            'fields': ('amount', 'payment_method', 'payment_status', 'transaction_reference')
        }),
        ('M-Pesa Details', {
            'fields': ('mpesa_number', 'mpesa_receipt_number'),
            'classes': ('collapse',)
        }),
        ('Card Details', {
            'fields': ('card_last_four',),
            'classes': ('collapse',)
        }),
        ('Bank Transfer Details', {
            'fields': ('bank_name', 'bank_reference'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('payment_date', 'completion_date', 'created_at', 'updated_at')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )

    def mark_completed(self, request, queryset):
        """
        Confirm payment, then update the Membership row the payment was
        for via the 1.3 service layer (apps/home/services.py) -- the one
        door, rather than mutating fields or calling the model methods
        directly. Two paths:

        - payment.membership is set (installment payments -- apps/home/views.py
          links this explicitly now): services.record_installment_payment(),
          which accumulates amount_paid and activates on the first call
          without assuming the full tier fee was paid.
        - payment.membership is unset (lump-sum payments, or older rows that
          predate the FK): fall back to the original lookup-by-(user,tier,
          pending) then services.activate_membership(), same as before.

        Either path now also supersedes whatever was previously ACTIVE for
        that user and carries its membership_number forward, handled
        inside the service layer rather than here.

        Skips payments with no membership_tier set (shouldn't happen given
        how Payment rows are created, but nothing to apply if it is).
        """
        updated = 0
        for payment in queryset.select_related('alumni__user', 'membership_tier', 'membership'):
            payment.mark_as_completed()
            tier = payment.membership_tier
            if not tier:
                continue
            payment_date = payment.payment_date.date() if payment.payment_date else None

            if payment.membership_id:
                services.record_installment_payment(payment.membership, payment.amount, payment_date=payment_date)
            else:
                user = payment.alumni.user
                membership = Membership.objects.filter(
                    user=user, tier=tier, status=Membership.Status.PENDING
                ).order_by('-created_at').first()
                if membership is None:
                    membership = Membership.objects.create(user=user, tier=tier)
                services.activate_membership(membership, payment_date=payment_date)
            updated += 1
        self.message_user(request, f"{updated} payment(s) marked completed and membership updated.")
    mark_completed.short_description = "Mark selected payments as completed (and update membership)"

    def mark_failed(self, request, queryset):
        for payment in queryset:
            payment.mark_as_failed()
        self.message_user(request, f"{queryset.count()} payment(s) marked failed.")
    mark_failed.short_description = "Mark selected payments as failed"

    def mark_pending_verification(self, request, queryset):
        for payment in queryset:
            payment.mark_as_pending_verification()
        self.message_user(request, f"{queryset.count()} payment(s) marked pending verification.")
    mark_pending_verification.short_description = "Mark selected payments as pending verification"

    def mark_refunded(self, request, queryset):
        for payment in queryset:
            payment.mark_as_refunded()
        self.message_user(request, f"{queryset.count()} payment(s) marked refunded.")
    mark_refunded.short_description = "Mark selected payments as refunded"

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['id', 'payment', 'transaction_type', 'status_code', 'created_at']
    list_filter = ['transaction_type']
    search_fields = ['payment__transaction_reference', 'error_message']
    readonly_fields = ['payment', 'transaction_type', 'request_data', 'response_data', 'status_code', 'error_message', 'created_at']
    
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────
# UoNAA Secretariat's Membership Admin (mounted at /membership-admin/,
# see main/urls.py) -- payment confirmation, membership tier/number
# assignment, renewal, upgrading, and the #Issued Items tracking fields,
# without handing Secretariat staff the full /2005/ admin (Users,
# Groups, etc). Same ModelAdmin classes as the default admin above.
# ─────────────────────────────────────────────
membership_admin_site.register(Payment, PaymentAdmin)
membership_admin_site.register(MembershipTier, MembershipTierAdmin)
membership_admin_site.register(AlumniProfile, AlumniProfileAdmin)
membership_admin_site.register(Membership, MembershipAdmin)
membership_admin_site.register(PaymentTransaction, PaymentTransactionAdmin)
