from django.contrib import admin, messages
from apps.home.models import*
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import format_html
from django_q.tasks import async_task
from import_export import resources, fields
from import_export.admin import ExportMixin

from apps.home.membership_admin_site import membership_admin_site
from apps.home import services
from apps.qr_manager.models import QRCode
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
            'graduation_date', 'current_employer', 'employment_position',
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
        # current_for (latest of ANY status), not current_active_for --
        # deliberate: this column renders the status alongside the tier,
        # so a row awaiting Secretariat confirmation must stay visible.
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


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    # Wasn't registered at all before -- added so Student.programme (and
    # ScholarshipApplication/AlumniProfile's own qualification fields)
    # can use autocomplete_fields, which requires the target model's own
    # ModelAdmin to define search_fields (2026-08-13).
    list_per_page = 25
    list_display = ("name", "level", "faculty")
    list_filter = ("level", "faculty")
    search_fields = ("name", "faculty__faculty_name")
    ordering = ("faculty__faculty_name", "level", "name")
    autocomplete_fields = ("faculty",)

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
    list_display = ['__str__', 'chapter', 'article', 'event', 'publication', 'in_memoriam', 'image', 'show_in_carousel', 'created_at']
    search_fields = ['article__title', 'chapter__name', 'event__title', 'publication__title']
    list_filter = [ 'chapter', 'show_in_carousel', 'created_at' ] #,


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


@admin.register(ProgramArea)
class ProgramAreaAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['name', 'order', 'is_active', 'created_at']
    list_editable = ['order', 'is_active']
    search_fields = ['name', 'description']



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
    actions = ['send_newsletter_email']

    @admin.action(description="Send by email to opted-in alumni")
    def send_newsletter_email(self, request, queryset):
        # PublicationListView (the only page that lets an alumnus actually
        # find and open a published item) hardcodes visibility=PUBLIC --
        # members/committee-only visibility isn't wired to any
        # access-controlled view yet. Emailing a link nobody can open
        # would be worse than not sending it, so that's refused here
        # rather than silently mailed out broken.
        valid = queryset.filter(
            category=Publication.Category.NEWSLETTER,
            visibility=Publication.Visibility.PUBLIC,
        )
        skipped = queryset.exclude(pk__in=valid.values_list('pk', flat=True))
        for pub in skipped:
            self.message_user(
                request,
                f"Skipped '{pub.title}' -- only public Newsletter publications can be emailed "
                f"(this one is {pub.get_category_display()} / {pub.get_visibility_display()}).",
                level=messages.WARNING,
            )

        recipients = list(
            AlumniProfile.objects.filter(
                is_active=True,
                user__is_active=True,
                user__profile__email_opt_in=True,
            ).values_list('user_id', flat=True)
        )

        for pub in valid:
            with transaction.atomic():
                publication_id = pub.pk
                for user_id in recipients:
                    transaction.on_commit(
                        lambda uid=user_id, pid=publication_id: async_task(
                            "apps.home.tasks.send_newsletter_email", pid, uid
                        )
                    )
            self.message_user(
                request,
                f"Queued newsletter email to {len(recipients)} opted-in alumni for '{pub.title}'.",
            )


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
    list_display = [
        'name', 'code', 'fee', 'track', 'tier_type', 'duration_months', 'is_active',
        'provisions_confirmed', 'fee_is_provisional',
    ]
    list_editable = ['fee', 'is_active']
    list_filter = ['tier_type', 'is_active', 'provisions_confirmed', 'holder_type']
    ordering = ['order']
    inlines = [TierBenefitInline]
    fieldsets = [
        (None, {
            'fields': ['name', 'code', 'fee', 'tier_type', 'duration_months', 'is_active', 'order', 'ladder_rank'],
        }),
        ('Constitutional provisions (Art. 8)', {
            'fields': [
                'display_order', 'holder_type', 'fee_amount', 'fee_basis', 'fee_is_provisional',
                'is_life', 'max_term_years', 'membership_cap', 'minimum_age',
                'requires_general_assembly_election', 'requires_executive_ratification',
                'can_vote_governing_body', 'can_stand_for_executive_committee',
                'eligible_for_appointment', 'constitution_reference', 'provisions_confirmed',
                'eligibility_notes',
            ],
            'description': (
                'Populated by the reconcile_constitutional_categories management command. '
                'Blank/null means the supplied Constitutional text is silent on that point for '
                'this category -- leave it that way rather than guessing a value by hand.'
            ),
        }),
    ]


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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Same N+1 fix as AlumniProfileForm.__init__ (apps/home/forms.py)
        # -- Qualification.__str__ reads self.faculty.faculty_name, so the
        # default queryset (no select_related) fires one query per row
        # while rendering every <option>, which times out the admin
        # change page over a real network DB connection (2026-08-21,
        # confirmed via production traceback: gunicorn worker aborted
        # mid-query rendering this exact dropdown).
        if db_field.name == "qualification":
            kwargs["queryset"] = Qualification.objects.select_related("faculty")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class AlumniEmploymentRecordInline(admin.TabularInline):
    model = AlumniEmploymentRecord
    extra = 0
    fields = ['order', 'organization', 'position']


class DigitalIDStatusFilter(admin.SimpleListFilter):
    """digital_id_active alone (the old list_filter entry) can't tell
    "never applied" from "applied, awaiting Secretariat review" -- both
    show as False. This distinguishes them so the pending queue is
    actually findable from the list view (2026-08-21), instead of
    needing to open every row individually to check."""
    title = "Digital ID Status"
    parameter_name = "digital_id_status"

    def lookups(self, request, model_admin):
        return [
            ("no_photo", "No photo submitted"),
            ("pending", "Pending review"),
            ("approved", "Approved"),
        ]

    def queryset(self, request, queryset):
        no_photo = Q(digital_id_photo="") | Q(digital_id_photo__isnull=True)
        if self.value() == "no_photo":
            return queryset.filter(no_photo)
        if self.value() == "pending":
            return queryset.exclude(no_photo).filter(digital_id_active=False)
        if self.value() == "approved":
            return queryset.filter(digital_id_active=True)
        return queryset


@admin.register(AlumniProfile)
class AlumniProfileAdmin(ExportMixin, admin.ModelAdmin):
    resource_class = AlumniProfileResource
    # Personal data (name/DOB/national ID/contact) lives on UserProfile
    # now, edited via the User admin's inline -- not here. Membership
    # data (tier/status/expiry/issued items) lives on Membership,
    # registered separately below.
    list_display = ['id', 'display_name', 'user_email', 'current_membership_display', 'digital_id_status', 'digital_id_active']
    list_filter = ['graduation_institution', 'graduation_date', DigitalIDStatusFilter]
    search_fields = [
        'user__profile__given_name', 'user__profile__family_name', 'user__email',
        'user__profile__national_id', 'student_reg_no',
    ]
    readonly_fields = ['registration_date', 'last_updated', 'qr_code_tag']
    list_per_page = 25
    list_editable = ['digital_id_active']
    actions = ['generate_qr_badge', 'approve_digital_id_photo']
    fieldsets = (
        ('User Account', {
            'fields': ('user',)
        }),
        ('Alumni Details', {
            'fields': (
                'graduation_date', 'faculty', 'qualification', 'qualification_name_raw',
                'graduation_institution', 'other_institution_name',
                'other_institution_qualification', 'name_at_graduation', 'student_reg_no',
            )
        }),
        ('Employment', {
            'fields': ('current_employer', 'employment_position')
        }),
        # Digital alumni ID (QR) -- advertised membership benefit,
        # mirrors apps/staff/admin.py's EmployeeAdmin "QR Code" section:
        # generate/regenerate via the action below (or by attaching this
        # alumnus to a QRCode directly in the QR admin), qr_code_image
        # stays editable here in case it ever needs manual replacement.
        # digital_id_photo (2026-08-21) is self-service now -- alumni
        # apply via standing_page()'s digital-id branch (apps/home/urls.py's
        # "alumni_digital_id_apply" route) -- but only actually
        # displays once digital_id_active is checked here (or via the
        # "Approve selected Alumni Digital ID photos" action below);
        # list_filter above is how a Secretariat member finds the pending
        # queue.
        ('Alumni Digital ID', {
            'fields': ('digital_id_photo', 'digital_id_active', 'qr_code_tag', 'qr_code_image'),
        }),
        ('Meta', {
            'fields': ('is_active', 'registration_date', 'last_updated')
        }),
    )
    inlines = [PaymentInline, AlumniQualificationInline, AlumniEmploymentRecordInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Same fix as AlumniQualificationInline above, for this model's
        # own top-level qualification field.
        if db_field.name == "qualification":
            kwargs["queryset"] = Qualification.objects.select_related("faculty")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description='Name')
    def display_name(self, obj):
        return obj.user.profile.display_name if hasattr(obj.user, 'profile') else '—'

    @admin.display(description='Email')
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description='Current Membership')
    def current_membership_display(self, obj):
        # current_for (latest of ANY status), not current_active_for --
        # deliberate: this is the list the Secretariat works from, and it
        # renders the status, so pending requests must stay visible here.
        membership = Membership.objects.current_for(obj.user)
        if membership is None:
            return '—'
        return f"{membership.tier.name} ({membership.get_status_display()})"

    @admin.display(description="Digital ID Status")
    def digital_id_status(self, obj):
        if not obj.digital_id_photo:
            return format_html('<span style="color:#6b7280;">No photo</span>')
        if obj.digital_id_active:
            return format_html('<span style="color:#15803d;font-weight:600;">Approved</span>')
        return format_html('<span style="color:#92730a;font-weight:600;">Pending review</span>')

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

    @admin.action(description="Generate / refresh Alumni Digital ID (QR)")
    def generate_qr_badge(self, request, queryset):
        done = 0
        for alumni in queryset:
            qr, _ = QRCode.objects.get_or_create(alumni_profile=alumni)
            qr.generate_qr(force=True)
            done += 1
        if done:
            self.message_user(request, f"Generated {done} QR badge(s).", messages.SUCCESS)

    @admin.action(description="Approve selected Alumni Digital ID photos")
    def approve_digital_id_photo(self, request, queryset):
        # Only rows with an actual photo uploaded -- approving an empty
        # field is meaningless (digital_id_photo_url falls back to the
        # general profile photo regardless of this flag when unset).
        updated = queryset.exclude(digital_id_photo='').update(digital_id_active=True)
        self.message_user(request, f"Approved {updated} Alumni Digital ID photo(s).", messages.SUCCESS)


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

        Installment plans anchor next_installment_due to TODAY -- the
        moment this action runs, i.e. Secretariat confirmation -- not to
        payment.payment_date (2026-08-21). payment_date defaults to when
        the member submitted the payment request, which can sit pending
        for days/weeks before the Secretariat gets to it; anchoring the
        payout schedule to that submission timestamp instead of the
        actual confirmation could make an installment read as already
        overdue the moment it activates. Lump-sum activate_membership()
        below is untouched -- only the installment path was asked for.
        """
        updated = 0
        today = timezone.now().date()
        for payment in queryset.select_related('alumni__user', 'membership_tier', 'membership'):
            payment.mark_as_completed()
            tier = payment.membership_tier
            if not tier:
                continue

            if payment.membership_id:
                services.record_installment_payment(payment.membership, payment.amount, payment_date=today)
            else:
                payment_date = payment.payment_date.date() if payment.payment_date else None
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


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_display = ['id', 'email_type', 'related_object_id', 'recipient_email', 'sent_at', 'created_at']
    list_filter = ['email_type']
    search_fields = ['related_object_id', 'recipient_email', 'error']
    readonly_fields = ['email_type', 'related_object_id', 'recipient_email', 'sent_at', 'error', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProfileClaimVerification)
class ProfileClaimVerificationAdmin(admin.ModelAdmin):
    """Read-only, same shape as EmailLogAdmin -- these rows are audit
    trail for the "find my profile" claim flow (apps.home.views'
    ProfileClaim* views), never hand-edited."""
    list_per_page = 25
    list_display = ['id', 'user', 'channel', 'status', 'attempts', 'ip_address', 'created_at', 'expires_at']
    list_filter = ['status', 'channel']
    search_fields = ['user__email', 'ip_address']
    readonly_fields = [
        'id', 'user', 'channel', 'code_hash', 'status', 'attempts', 'ip_address',
        'created_at', 'expires_at', 'verified_at',
    ]

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
