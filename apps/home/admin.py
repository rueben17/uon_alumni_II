from django.contrib import admin
from apps.home.models import*
from django.db.models import Count
from django.contrib.auth.models import User
from django.utils.html import format_html

from apps.home.membership_admin_site import membership_admin_site
# Register your models here.

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'chapter', 'created_at', 'slug', 'is_feature', 'is_highlighted']
    prepopulated_fields = { 'slug': ('title',), }
    list_filter = ['created_at', 'is_feature', 'is_highlighted', 'chapter']
    search_fields = ['title', 'body']
    list_per_page = 6

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at', 'date_updated']
    prepopulated_fields = { 'slug': ('title',), }
    list_per_page = 6



@admin.register(Images)
class ImagesAdmin(admin.ModelAdmin):
    list_display = ['chapter', 'article', 'image', 'created_at']
    search_fields = ['article__title',]
    list_filter = [ 'chapter', 'created_at' ] #, 


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ['text', 'created_at']
    list_filter = [ 'created_at' ] #, 


@admin.register(CoreValue)
class CoreValueAdmin(admin.ModelAdmin):
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
    list_display = ['name', 'faculty','year_launched', 'slug']
    list_filter = [ 'faculty' ] #,
    prepopulated_fields = { 'slug': ('name',)} 

@admin.register(Executive)
class ExecutiveAdmin(admin.ModelAdmin):
    list_display = ['title', 'position', 'rank', 'first_name', 'middle_name', 'surname' ]

@admin.register(Secretariat)
class SecretariatAdmin(admin.ModelAdmin):
    list_display = ['title', 'position', 'first_name', 'middle_name', 'surname' ]

@admin.register(MembershipTier)
class MembershipTierAdmin(admin.ModelAdmin):
    list_display = ['name', 'fee', 'tier_type', 'duration_months', 'is_active']
    list_editable = ['fee', 'is_active']
    list_filter = ['tier_type', 'is_active']


class PaymentInline(admin.TabularInline):
    model = Payment
    fields = ['amount', 'payment_method', 'payment_status', 'payment_date']
    readonly_fields = ['amount', 'payment_method', 'payment_status', 'payment_date']
    extra = 0
    can_delete = False


@admin.register(AlumniProfile)
class AlumniProfileAdmin(admin.ModelAdmin):
    list_display = ['id', 'first_name', 'surname', 'email']
    list_filter = ['current_membership_tier', 'is_lifetime_member', 'membership_card_issued', 'graduation_year']
    search_fields = ['first_name', 'surname', 'email', 'id_passport_no', 'student_reg_no', 'membership_number']
    readonly_fields = ['registration_date', 'last_updated']
    actions = ['issue_membership_card', 'mark_as_lifetime']
    list_per_page = 20
    fieldsets = (
        ('User Account', {
            'fields': ('user',)
        }),
        ('Personal Information', {
            'fields': ('title', 'surname', 'first_name', 'middle_name', 'maiden_name',
                       'gender', 'date_of_birth', 'id_passport_no', 'nationality')
        }),
        ('Contact Details', {
            'fields': ('postal_address', 'postal_code', 'city', 'phone_mobile', 'phone_alt', 'email')
        }),
        ('Alumni Details', {
            'fields': ('graduation_year', 'faculty', 'student_reg_no')
        }),
        ('Membership', {
            'fields': ('current_membership_tier', 'membership_expiry', 'is_lifetime_member', 'membership_number',
                       'membership_card_issued', 'certificate_issued', 'certificate_sent', 'certificate_generated_at', 'lapel_badge_issued')
        }),
        ('Preferences & Meta', {
            'fields': ('receive_newsletter', 'receive_sms_alerts', 'is_active', 'registration_date', 'last_updated')
        }),
    )
    inlines = [PaymentInline]

    def user_link(self, obj):
        return format_html('<a href="/admin/auth/user/{}/change/">{}</a>', obj.user.id, obj.user.username)
    user_link.short_description = 'Username'

    def membership_valid_badge(self, obj):
        if obj.is_membership_valid:
            return format_html('<span style="color:green;">✓ Valid</span>')
        return format_html('<span style="color:red;">✗ Expired</span>')
    membership_valid_badge.short_description = 'Membership Status'

    def issue_membership_card(self, request, queryset):
        """
        This method runs when you select "Issue membership card to selected"
        `queryset` contains all the selected AlumniProfile objects
        """
        count = queryset.update(membership_card_issued=True)
        self.message_user(request, f"{count} membership card(s) marked as issued.")
    
    # This is the label that appears in the dropdown
    issue_membership_card.short_description = "Issue membership card to selected"

    def mark_as_lifetime(self, request, queryset):
        """
        This method runs when you select "Mark as lifetime members"
        """
        count = queryset.update(is_lifetime_member=True, membership_expiry=None)
        self.message_user(request, f"{count} member(s) marked as lifetime.")
    
    mark_as_lifetime.short_description = "Mark as lifetime members"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'alumni', 'amount', 'payment_method', 'payment_status', 'payment_date']
    list_filter = ['payment_status', 'payment_method']
    search_fields = ['transaction_reference', 'alumni__first_name', 'alumni__surname', 'alumni__email']
    readonly_fields = ['transaction_reference', 'created_at', 'updated_at']
    actions = ['mark_completed', 'mark_failed', 'mark_pending_verification', 'mark_refunded']
    fieldsets = (
        ('Alumni & Tier', {
            'fields': ('alumni', 'membership_tier')
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
        Confirm payment, then actually apply the membership change the
        payment was for -- assigns/renews the tier (and, for a new or
        different tier, generates the membership number) via the
        AlumniProfile methods the money is meant to unlock. Skips
        payments with no membership_tier set (shouldn't happen given how
        Payment rows are created, but nothing to apply if it is).
        """
        updated = 0
        for payment in queryset.select_related('alumni', 'membership_tier'):
            payment.mark_as_completed()
            tier = payment.membership_tier
            if not tier:
                continue
            alumni = payment.alumni
            if tier.is_lifetime() and alumni.current_membership_tier_id != tier.id:
                alumni.upgrade_to_lifetime(tier)
            else:
                alumni.renew_membership(tier)
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
membership_admin_site.register(PaymentTransaction, PaymentTransactionAdmin)
