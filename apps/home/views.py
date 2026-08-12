from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import send_mail
from django.db.models import Count, Prefetch, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from apps.home.forms import (
    AlumniProfileForm, AlumniRegistrationForm, ContactForm, MembershipUpdateForm, ScholarshipApplicationForm,
)
from apps.home.models import*
from apps.home.payments import initiate_payment
from apps.home import services
from apps.user.mixins import StaffOrSuperuserRequiredMixin

# Create your views here.







def uon_alumni_home(request):
    context = {
        "carousel_images": Images.objects.filter(show_in_carousel=True).exclude(image="").order_by("created_at"),
    }
    return render(request, "home/alumni_home.html", context)



def uon_alumni_history(request):
    return render(request, 'home/uon_alumni_history.html')


def uon_alumni_gallery(request):
    images = (
        Images.objects
        .exclude(image="")
        .select_related("article", "chapter", "event", "publication", "in_memoriam")
        .order_by("-created_at")[:60]
    )
    return render(request, 'home/uon_alumni_gallery.html', {"images": images})



def uon_alumni_exec_committee(request):
    executives = Executive.objects.all().order_by('rank')


    context = {
        "executives": executives,

    }
    # print(treasurer)
    return render(request, 'home/uon_alumni_exec_committee.html', context)


def uon_alumni_secretariat(request):
    return render(request, 'home/uon_alumni_secretariat.html', {
        "secretariat_members": Secretariat.objects.all().order_by('rank'),
    })


def uon_alumni_partners(request):
    return render(request, 'home/uon_alumni_partners.html', {
        "partners": Partner.objects.all().order_by('-created_at'),
    })


def uon_alumni_mission_vision(request):
    return render(request, 'home/uon_alumni_mission_vision.html', {
        "core_values": CoreValue.objects.filter(is_active=True).order_by('order'),
    })


def standing_page(request, page_key):
    """Generic renderer for the nav's remaining standing pages (Categories
    & Benefits, Alumni Card, Corporates, Notable Alumni, AGM, Consultancy
    & Training, Terms, Privacy, Shop) -- one route + template instead of
    nine near-identical ones. Makes every one of those links a real,
    working page today: it shows the matching Article(type=page) once an
    editor writes one, and an honest "being prepared" placeholder until
    then, rather than a 404 or a dead href="". Association content
    decisions (e.g. whether Shop ships at all) stay open; the URL not
    existing was never the actual blocker."""
    article = Article.objects.filter(
        type=Article.ArticleType.PAGE, page_key=page_key, is_published=True
    ).first()
    label = dict(Article.PageKey.choices).get(page_key, page_key.replace("-", " ").title())
    return render(request, 'home/standing_page.html', {
        "article": article,
        "page_label": label,
    })


class PublicationListView(ListView):
    """Backs both 'Downloads' (all public publications) and 'News
    Letters' (?category=newsletter) -- same query, one filter param, so
    the newsletter archive isn't a second view to keep in sync."""
    model = Publication
    template_name = "home/publication_list.html"
    context_object_name = "publications"
    paginate_by = 20

    def get_queryset(self):
        qs = Publication.objects.filter(visibility=Publication.Visibility.PUBLIC).exclude(file="")
        category = self.request.GET.get("category")
        if category:
            qs = qs.filter(category=category)
        return qs.order_by("-document_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_category"] = self.request.GET.get("category", "")
        context["categories"] = Publication.Category.choices
        return context


class JobPostingListView(ListView):
    """'Careers' -- 1.6 sells this as the student tier's primary draw
    (todo.md C.7); nominally members-only per that plan, but membership
    gating isn't built into any view yet (that's Phase 1.2/1.6 dashboard
    territory), so this is public for now like the rest of tonight's
    pages. Flagging rather than quietly deciding access control here."""
    model = JobPosting
    template_name = "home/job_posting_list.html"
    context_object_name = "job_postings"
    paginate_by = 20

    def get_queryset(self):
        return JobPosting.objects.filter(
            is_approved=True, expires_on__gte=timezone.now().date()
        ).order_by("-created_at")


class ArticleListView(ListView):
    """News/features/notices -- 'page' type Articles are standing-page
    copy (History/Donate/...), fetched by page_key elsewhere, never
    listed here."""
    model = Article
    template_name = "home/article_list.html"
    context_object_name = "articles"
    paginate_by = 12

    def get_queryset(self):
        return (
            Article.objects.filter(is_published=True)
            .exclude(type=Article.ArticleType.PAGE)
            .order_by("-created_at")
        )


class ArticleDetailView(DetailView):
    model = Article
    template_name = "home/article_detail.html"
    context_object_name = "article"

    def get_queryset(self):
        return Article.objects.filter(is_published=True).exclude(type=Article.ArticleType.PAGE)


class EventListView(ListView):
    """The 'UoN Alumni Walk' page -- scoped to event_type=WALK.
    Workshop/conference/forum/training (todo.md 0.3b's addition to
    Event) get their own listing when something routes to them; nothing
    does yet, so they're deliberately excluded here rather than mixed
    into the Walk page."""
    model = Event
    template_name = "home/walk_list.html"
    context_object_name = "events"
    paginate_by = 12

    def get_queryset(self):
        return Event.objects.filter(event_type=Event.EventType.WALK).order_by("-created_at")


class EventDetailView(DetailView):
    model = Event
    template_name = "home/walk_detail.html"
    context_object_name = "event"

    def get_queryset(self):
        return Event.objects.filter(event_type=Event.EventType.WALK)


class ChapterListView(ListView):
    model = Chapter
    template_name = "home/chapter_list.html"
    context_object_name = "chapters"

    def get_queryset(self):
        return Chapter.objects.select_related("faculty").order_by("name")


class ChapterDetailView(DetailView):
    model = Chapter
    template_name = "home/chapter_detail.html"
    context_object_name = "chapter"

    def get_object(self, queryset=None):
        # faculty_slug in the URL (present only when Chapter.get_absolute_url()
        # had a faculty to build it from) is decorative -- Chapter.slug is
        # what's actually looked up, same pattern as EmployeeDetailView's
        # unit_slug in apps/staff/views.py.
        return get_object_or_404(Chapter.objects.select_related("faculty"), slug=self.kwargs["slug"])



class QualificationMapMixin:
    """
    Feeds the Faculty -> Qualification options as JSON so the template's
    JS can rebuild the Qualification <select> when Faculty changes.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Iterates the SAME select_related("faculty") queryset
        # AlumniProfileForm.__init__ already set on this field (dodging
        # the N+1 from Qualification.__str__ touching self.faculty --
        # 273 rows), rather than a third fresh query over the same data.
        # This still costs 2 Qualification queries, not 1: Django's
        # ModelChoiceIterator calls queryset.iterator() for any field
        # queryset that isn't prefetch_related (only select_related
        # here), and .iterator() is a streaming mode that never reads or
        # populates _result_cache -- so the widget's own <option> render
        # unavoidably re-queries once more, however this one's read.
        # Nowhere near the N+1 it replaced, so left as the practical
        # floor rather than restructuring around .choices to chase the
        # last query (2026-08-12 audit).
        qualification_map = {}
        for qualification in context["form"].fields["qualification"].queryset:
            qualification_map.setdefault(str(qualification.faculty_id), []).append(
                {"value": qualification.id, "label": qualification.name}
            )
        context["qualification_map"] = qualification_map
        return context


class MpesaEligibilityMixin:
    """
    Feeds which MembershipTier ids DON'T allow M-Pesa (tier.fee above
    MembershipTier.MPESA_FEE_CEILING) so the template's JS can disable
    that option client-side when an ineligible tier is picked. Purely a
    UX nicety -- the form's clean() is the actual, authoritative gate;
    this just avoids a round-trip for a combination that's guessable
    upfront.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["non_mpesa_tier_ids"] = list(
            MembershipTier.objects.filter(fee__gt=MembershipTier.MPESA_FEE_CEILING).values_list("id", flat=True)
        )
        return context


class AlumniRegisterView(MpesaEligibilityMixin, QualificationMapMixin, LoginRequiredMixin, CreateView):
    """
    One-time alumni onboarding. The login/signup adapter sends every
    user without an AlumniProfile here (apps/user/adapter.py); once
    registered, this view redirects to the home page for any further
    visits (see dispatch()).
    """
    model = AlumniProfile
    form_class = AlumniRegistrationForm
    template_name = "home/uon_alumni_register.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and hasattr(request.user, "alumni_profile"):
            return redirect("home:uon_alumni_home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)

        # DPA 2019 consent: form.privacy_consent already gated submission
        # (required=True), so reaching here means it was checked. Stamp
        # when and against which version -- never inferred, never
        # backdated, and never overwritten on a later profile edit (this
        # view only runs once, at registration).
        from apps.user.models import CURRENT_PRIVACY_NOTICE_VERSION
        profile = self.request.user.profile
        profile.consent_given_at = timezone.now()
        profile.privacy_notice_version = CURRENT_PRIVACY_NOTICE_VERSION
        profile.save(update_fields=["consent_given_at", "privacy_notice_version"])

        # Only records the request -- membership number/tier assignment,
        # renewal, upgrading, and everything under #Issued Items happen
        # in the Membership Admin site once a Secretariat member confirms
        # the payment (see PaymentAdmin.mark_completed in apps/home/admin.py).
        # Membership created first so Payment.membership can link directly
        # to it -- installment payments need that (apps/home/models.py's
        # record_installment_payment); a lump-sum "Once" payment still
        # covers the full tier.fee in one shot, same as before.
        tier = form.cleaned_data["membership_tier"]
        frequency = form.cleaned_data["payment_frequency"]
        amount = form.cleaned_data.get("installment_amount") or tier.fee
        membership = services.assign_membership_tier(self.request.user, tier, payment_frequency=frequency)
        payment = Payment.objects.create(
            alumni=self.object,
            membership=membership,
            membership_tier=tier,
            amount=amount,
            payment_method=form.cleaned_data["payment_method"],
        )
        initiate_payment(payment)

        messages.success(self.request, "Welcome! Your alumni profile is complete.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class AlumniProfileDetailView(DetailView):
    """
    Public alumni profile page — mirrors staff's EmployeeDetailView.
    Personal fields live on UserProfile/User now, not AlumniProfile
    (docs/rebuild-schema.md), and membership is its own model — the
    template reads through alumni.user.profile.* and the
    current_membership context var added here, not delegation properties
    on AlumniProfile (todo.md guiding decision).
    """
    model = AlumniProfile
    template_name = "home/alumni_detail.html"
    context_object_name = "alumni"

    def get_object(self, queryset=None):
        return get_object_or_404(
            AlumniProfile.objects.select_related("user", "user__profile"),
            is_active=True, pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        from allauth.account.models import EmailAddress

        context = super().get_context_data(**kwargs)
        current_membership = Membership.objects.current_for(self.object.user)
        context["current_membership"] = current_membership
        context["alt_email"] = EmailAddress.objects.filter(user=self.object.user, primary=False).first()
        # Only what this member actually has -- not the full tier matrix
        # (that's the separate Categories & Benefits page). Excluded/
        # not-applicable rows would just be a list of things they don't
        # get, which has no place on someone's own profile. Shaped to
        # match snippets/tiers.html's expectations (new_benefits/
        # previous_tier_name on the tier itself, a `tiers` list to loop
        # over) so this page renders through the same shared card
        # component as the public tier comparison and Corporate, instead
        # of a third hand-rolled copy of the same markup.
        if current_membership:
            tier = current_membership.tier
            tier.previous_tier_name = None
            tier.new_benefits = (
                tier.tier_benefits
                .filter(status=TierBenefit.Status.INCLUDED)
                .select_related("benefit")
                .order_by("display_order")
            )
            context["current_membership_tiers"] = [tier]
        return context


class MembershipCategoriesView(TemplateView):
    """Public tier x benefit comparison (2026-08-11) -- the "Categories &
    Benefits" nav link now points here instead of the empty standing_page
    placeholder (see context_processors.py's url_categories_benefits).

    Tiers with no TierBenefit rows at all are excluded rather than shown
    empty -- today that's just Honorary Member (conferred, not purchased;
    the 2026-08-10 tier-audit's source data never covered it, so nothing
    was ever seeded for it). Corporate is queried and rendered separately
    from the individual ladder, not appended as "tier 11" -- it's a
    parallel institutional track per the audit's own rules.
    """
    template_name = "home/membership_categories.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        included_qs = (
            TierBenefit.objects.filter(status=TierBenefit.Status.INCLUDED)
            .select_related("benefit")
            .order_by("display_order")
        )
        tiers = (
            MembershipTier.objects.filter(is_active=True, tier_benefits__isnull=False)
            .exclude(tier_type="registered")
            .distinct()
            .order_by("fee")
            .prefetch_related(Prefetch("tier_benefits", queryset=included_qs, to_attr="included_benefits"))
        )
        individual_tiers = [t for t in tiers if not t.is_corporate]
        context["individual_tiers"] = individual_tiers
        corporate_tiers = [t for t in tiers if t.is_corporate]
        context["corporate_tiers"] = corporate_tiers

        # Individual tiers are a monotonic ladder by fee (each a superset
        # of the one below, per the 2026-08-10 tier-audit's own design
        # rule) -- showing every tier's FULL benefit list repeats most of
        # it verbatim from the tier below. Instead, diff each tier
        # against the one immediately cheaper: a benefit only counts as
        # "new" if it wasn't there before, OR it was there with a
        # DIFFERENT qualifier (e.g. mentor status upgrading from "mentee"
        # to "mentor" is a real change even though the benefit itself
        # already existed) -- a same-id/same-detail match is genuinely
        # unchanged and gets dropped from this tier's list. tier.name is
        # attached as tier.previous_tier_name so the template can render
        # "Everything in X, plus:"; the cheapest tier has no previous, so
        # it just shows its own list.
        previous_by_id = {}
        for i, tier in enumerate(individual_tiers):
            tier.previous_tier_name = individual_tiers[i - 1].name if i > 0 else None
            tier.new_benefits = [
                tb for tb in tier.included_benefits
                if previous_by_id.get(tb.benefit_id) != tb.detail
            ]
            previous_by_id = {tb.benefit_id: tb.detail for tb in tier.included_benefits}

        # Corporate isn't a rung on the individual ladder, so there's no
        # "previous tier" to diff against -- it just shows its own full
        # benefit list. Setting these here (rather than branching in the
        # template) lets snippets/tiers.html stay ignorant of which track
        # it's rendering.
        for tier in corporate_tiers:
            tier.previous_tier_name = None
            tier.new_benefits = tier.included_benefits

        # Rendered in one shared grid (see membership_categories.html) so
        # Corporate lands in whatever row the individual ladder's last row
        # left open, instead of forcing its own row below.
        context["all_tiers"] = individual_tiers + corporate_tiers

        return context


@login_required
def download_payment_receipt(request, slug, pk, payment_id):
    """Serve a payment's acknowledgement receipt as a downloadable file.

    STUBBED (2026-08-10): no receipt-generation mechanism exists anywhere
    in this codebase yet -- confirmed nothing under 'receipt'/'reportlab'-
    for-receipts before wiring this up. Per the UX/UI spec's own stop
    condition ("if receipt generation does not already exist, stop and
    ask before adding it"), this deliberately does NOT fabricate PDF
    generation. Returns 501 so the button/URL is real and the template
    never hits NoReverseMatch, but the actual file response is pending
    confirmation of where/how receipts should be produced.
    """
    from django.http import HttpResponse

    alumni = get_object_or_404(AlumniProfile, pk=pk, user=request.user)
    payment = get_object_or_404(Payment, pk=payment_id, alumni=alumni)
    return HttpResponse(
        "Receipt download isn't wired up yet -- pending confirmation of how receipts are generated.",
        status=501,
    )


class AlumniProfileUpdateView(QualificationMapMixin, LoginRequiredMixin, UpdateView):
    """
    Opt-in profile editing. The URL carries slug+pk now (readability --
    matches alumni_detail's pattern), but ownership is still enforced by
    filtering on user=request.user alongside it: someone editing the URL's
    UUID to another member's profile gets a 404, not someone else's form.
    """
    model = AlumniProfile
    form_class = AlumniProfileForm
    template_name = "home/alumni_profile_update.html"

    def get_object(self, queryset=None):
        return get_object_or_404(AlumniProfile, pk=self.kwargs["pk"], user=self.request.user)

    def get_success_url(self):
        return self.object.get_absolute_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Profile updated.")
        return response


class AlumniMembershipUpdateView(LoginRequiredMixin, View):
    """
    Request a renewal or a move to a different tier (including a lifetime
    tier). Records the request as a Payment plus a pending Membership row
    (see apps/home/models.py's Membership) -- actually activating it
    (and generating the membership number) happens in the Membership
    Admin site once a Secretariat member confirms the payment (see
    PaymentAdmin.mark_completed in apps/home/admin.py), same as
    registration.

    Restricted to already-paid-up members (2026-08-07): at least one
    ACTIVE or EXPIRED Membership, not just the still-pending one from
    registering. Someone who's never had a payment confirmed has nothing
    to renew/upgrade yet -- enforced here, not just by hiding the navbar
    link (apps/home/context_processors.py), since the URL is guessable.
    """
    template_name = "home/alumni_membership_update.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not hasattr(request.user, "alumni_profile"):
            return redirect("home:uon_alumni_register")
        if request.user.is_authenticated and hasattr(request.user, "alumni_profile"):
            has_paid_membership = Membership.objects.filter(user=request.user).exclude(
                status=Membership.Status.PENDING
            ).exists()
            if not has_paid_membership:
                messages.info(
                    request,
                    "Your membership is still pending confirmation. You'll be able to renew or "
                    "upgrade here once the Secretariat confirms your first payment.",
                )
                return redirect(request.user.alumni_profile.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        alumni = get_object_or_404(AlumniProfile, pk=kwargs["pk"], user=request.user)
        current_membership = Membership.objects.current_for(request.user)
        form = MembershipUpdateForm(
            initial={"membership_tier": current_membership.tier_id if current_membership else None}
        )
        pending_payment = alumni.payments.filter(
            payment_status__in=["pending", "pending_verification"]
        ).order_by("-payment_date").first()
        non_mpesa_tier_ids = list(
            MembershipTier.objects.filter(fee__gt=MembershipTier.MPESA_FEE_CEILING).values_list("id", flat=True)
        )
        return render(request, self.template_name, {
            "alumni": alumni,
            "current_membership": current_membership,
            "form": form,
            "pending_payment": pending_payment,
            "non_mpesa_tier_ids": non_mpesa_tier_ids,
        })

    def post(self, request, *args, **kwargs):
        alumni = get_object_or_404(AlumniProfile, pk=kwargs["pk"], user=request.user)

        # Guard against a second overlapping request: submitting twice
        # (double-click, or coming back before the Secretariat has acted)
        # used to silently create a second pending Membership+Payment pair
        # with nothing to prevent BOTH from later being confirmed --
        # ending up with two simultaneously-active memberships for one
        # person, with current_for() only ever showing the newer one and
        # the older one silently forgotten. Block instead of guessing at
        # what "reuse the existing request" should even mean (change its
        # tier? its amount? that's real business-rule work, not a
        # mechanical fix) -- same reasoning as why 1.3's service layer
        # isn't built yet.
        if Membership.objects.filter(user=request.user, status=Membership.Status.PENDING).exists():
            messages.warning(
                request,
                "You already have a membership request awaiting Secretariat confirmation. "
                "Contact the Secretariat if you need to change it before it's processed.",
            )
            return redirect(alumni.get_membership_update_url())

        form = MembershipUpdateForm(request.POST)

        if not form.is_valid():
            return render(request, self.template_name, {"alumni": alumni, "form": form})

        tier = form.cleaned_data["membership_tier"]
        frequency = form.cleaned_data["payment_frequency"]
        amount = form.cleaned_data.get("installment_amount") or tier.fee
        membership = services.assign_membership_tier(request.user, tier, payment_frequency=frequency)
        payment = Payment.objects.create(
            alumni=alumni,
            membership=membership,
            membership_tier=tier,
            amount=amount,
            payment_method=form.cleaned_data["payment_method"],
        )
        initiate_payment(payment)

        messages.success(request, "Request recorded. Your membership updates once the Secretariat confirms the payment.")
        return redirect(alumni.get_absolute_url())


class AlumniProfileDeleteView(LoginRequiredMixin, View):
    """
    Owner-only profile deactivation with explicit confirmation.
    Deactivating the AlumniProfile does not delete the User account.
    """
    template_name = "home/alumni_profile_delete_confirm.html"

    def get(self, request, *args, **kwargs):
        alumni = get_object_or_404(AlumniProfile, pk=kwargs["pk"], user=request.user)
        return render(request, self.template_name, {"alumni": alumni})

    def post(self, request, *args, **kwargs):
        alumni = get_object_or_404(AlumniProfile, pk=kwargs["pk"], user=request.user)
        alumni.is_active = False
        alumni.save(update_fields=["is_active"])
        messages.success(request, "Your alumni profile has been deactivated.")
        logout(request)
        return redirect("home:uon_alumni_home")


class MembershipAnalyticsView(StaffOrSuperuserRequiredMixin, TemplateView):
    """
    Staff/superadmin-only membership analytics (todo.md 1.9) -- Chart.js
    dashboard over Membership/AlumniProfile/Faculty. Deliberately separate
    from AlumniProfileDetailView's self-service dashboard: this is
    leadership reporting across *all* members, not one member's own view.

    Ships aggregates as JSON in the template context (json_script'd) rather
    than a separate API endpoint -- there is no other consumer yet, and a
    same-request context var is one less moving part than a fetch() round
    trip for data that's cheap to compute per page load at today's scale.
    """
    template_name = "home/membership_analytics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        by_tier = list(
            Membership.objects.values("tier__name")
            .annotate(count=Count("id"), revenue=Sum("subscription_amount"))
            .order_by("-count")
        )
        by_status = list(
            Membership.objects.values("status")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        by_faculty = list(
            Membership.objects.exclude(user__alumni_profile__faculty__isnull=True)
            .values("user__alumni_profile__faculty__faculty_name")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        monthly_revenue = list(
            Membership.objects.exclude(started_on__isnull=True)
            .annotate(month=TruncMonth("started_on"))
            .values("month")
            .annotate(revenue=Sum("subscription_amount"))
            .order_by("month")
        )
        signed_counts = list(
            Membership.objects.values("legacy_signed").annotate(count=Count("id"))
        )

        total_members = Membership.objects.count()

        # Raw per-row breakdowns for the table-view twin beside each chart
        # (todo.md 1.9 follow-up, 2026-08-08) -- a bar/line chart alone can't
        # carry more than one measure at a glance (count *and* revenue *and*
        # share of total), and past ~7 categories a table reads better than
        # a chart anyway. Built from the same querysets above, not a second
        # round-trip to the DB.
        context["tier_table"] = [
            {
                "name": row["tier__name"] or "—",
                "count": row["count"],
                "revenue": row["revenue"] or 0,
                "pct": (row["count"] / total_members * 100) if total_members else 0,
            }
            for row in by_tier
        ]
        context["revenue_table"] = [
            {"month": row["month"], "revenue": row["revenue"] or 0}
            for row in monthly_revenue
        ]

        context["chart_data"] = {
            "by_tier": {
                "labels": [row["tier__name"] or "—" for row in by_tier],
                "counts": [row["count"] for row in by_tier],
                "revenue": [float(row["revenue"] or 0) for row in by_tier],
            },
            "by_status": {
                "labels": [dict(Membership.Status.choices).get(row["status"], row["status"]) for row in by_status],
                "counts": [row["count"] for row in by_status],
            },
            "by_faculty": {
                "labels": [row["user__alumni_profile__faculty__faculty_name"] for row in by_faculty],
                "counts": [row["count"] for row in by_faculty],
            },
            "monthly_revenue": {
                "labels": [row["month"].strftime("%b %Y") for row in monthly_revenue],
                "revenue": [float(row["revenue"] or 0) for row in monthly_revenue],
            },
            "signed_coverage": {
                "signed": next((row["count"] for row in signed_counts if row["legacy_signed"]), 0),
                "unsigned": next((row["count"] for row in signed_counts if not row["legacy_signed"]), 0),
            },
        }
        context["total_members"] = total_members
        context["total_revenue"] = Membership.objects.aggregate(total=Sum("subscription_amount"))["total"] or 0
        return context


def uon_alumni_donate(request):
    return render(request, 'home/uon_alumni_donate.html')


def uon_alumni_scholarship(request):
    """Public, no login required -- applicants are current undergraduate
    students, not necessarily existing alumni-portal accounts. Same
    GET-display/POST-validate/messages.success/redirect pattern as
    uon_alumni_contact_us() below; request.FILES is needed here for
    physical_copy, which uon_alumni_contact_us's form doesn't have.

    department_map feeds the Faculty -> Department cascading dropdown --
    same shape/pattern as QualificationMapMixin's qualification_map
    (this is a function view, not a CBV, so built inline rather than via
    that mixin, but the template JS is the same rebuild-on-change logic).

    Query cost (found via a load-time audit, 2026-08-12 -- this page
    alone was taking 11s+ server-side in production): prefetch_related
    from the Faculty side fetches every Faculty (1 query) plus every
    Department in one batched query (1 more), and that same cached
    queryset is reused below for the faculty field's own <option> list
    instead of a third, separate Faculty.objects.all(). The department
    field still needs its own queryset (Django renders its <option>s
    independently of the JS-driven rebuild, as a no-JS fallback), but
    WITH select_related("faculty") -- Department.__str__ reads
    self.faculty.faculty_name, so without it, rendering that field's
    62 <option> labels fired 62 separate Faculty lookups. That N+1,
    not the map-building query, was almost certainly the real cost.
    """
    form = ScholarshipApplicationForm(request.POST or None, request.FILES or None)

    # Assign before reading back, not after: ModelChoiceField.queryset's
    # setter calls .all() on whatever it's given, cloning it -- iterate
    # a queryset first and assign it second, and the clone the setter
    # produces starts uncached again regardless. Assigning the
    # still-lazy queryset first and reading it back via the field means
    # this loop and the widget's own render iterate the same object.
    #
    # That object-sharing is *necessary* but only sufficient here
    # because this field carries prefetch_related: Django's
    # ModelChoiceIterator calls queryset.iterator() for any field
    # queryset that isn't prefetch_related, and .iterator() is a
    # streaming mode that never reads or populates _result_cache --
    # so this exact pattern, tried on QualificationMapMixin's
    # select_related-only (no prefetch_related) qualification field,
    # still cost a second query there. Don't copy this pattern onto a
    # select_related-only field expecting the same payoff.
    form.fields["faculty"].queryset = Faculty.objects.prefetch_related("departments").order_by("faculty_name")
    form.fields["department"].queryset = Department.objects.select_related("faculty").order_by("name")

    department_map = {
        str(faculty.id): [
            {"value": department.id, "label": department.name}
            for department in faculty.departments.all()
        ]
        for faculty in form.fields["faculty"].queryset
    }

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            "Thanks for applying -- your scholarship application has been received.",
        )
        return redirect("home:uon_alumni_scholarship")
    return render(request, 'home/uon_alumni_scholarship.html', {"form": form, "department_map": department_map})


def uon_alumni_in_memoriam(request):
    return render(request, 'home/uon_alumni_in_memoriam.html')

def uon_alumni_contact_us(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        contact_message = form.save()
        _notify_contact_message(contact_message)
        messages.success(request, "Thanks for reaching out — we've received your message.")
        return redirect("home:uon_alumni_contact_us")
    return render(request, 'home/uon_alumni_contact_us.html', {"form": form})


def _notify_contact_message(contact_message):
    """Best-effort email notification. The message is already safely
    persisted as a ContactMessage row regardless of whether this
    succeeds -- EMAIL_BACKEND isn't configured yet (no SMTP settings in
    main/settings.py), so locally/today this will just no-op. Wrapped so
    a delivery failure never turns into a 500 on top of an already-saved
    submission."""
    try:
        send_mail(
            subject=f"[UoNAA Contact] {contact_message.subject or 'New message'}",
            message=f"From: {contact_message.name} <{contact_message.email}>\n\n{contact_message.message}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=["alumni@uonbi.ac.ke"],
            fail_silently=True,
        )
    except Exception:
        pass


