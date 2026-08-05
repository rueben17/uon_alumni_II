from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.home.forms import AlumniProfileForm, AlumniRegistrationForm, ContactForm, MembershipUpdateForm
from apps.home.models import*
from apps.home.payments import initiate_payment

# Create your views here.







def uon_alumni_home(request):
    
    context = {

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
        qualification_map = {}
        for qualification in Qualification.objects.select_related("faculty"):
            qualification_map.setdefault(str(qualification.faculty_id), []).append(
                {"value": qualification.id, "label": qualification.name}
            )
        context["qualification_map"] = qualification_map
        return context


class AlumniRegisterView(QualificationMapMixin, LoginRequiredMixin, CreateView):
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

        # Only records the request -- membership number/tier assignment,
        # renewal, upgrading, and everything under #Issued Items happen
        # in the Membership Admin site once a Secretariat member confirms
        # the payment (see PaymentAdmin.mark_completed in apps/home/admin.py).
        tier = form.cleaned_data["membership_tier"]
        payment = Payment.objects.create(
            alumni=self.object,
            membership_tier=tier,
            amount=tier.fee,
            payment_method=form.cleaned_data["payment_method"],
        )
        Membership.objects.create(user=self.request.user, tier=tier)
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
        context["current_membership"] = Membership.objects.current_for(self.object.user)
        context["alt_email"] = EmailAddress.objects.filter(user=self.object.user, primary=False).first()
        return context


class AlumniProfileUpdateView(QualificationMapMixin, LoginRequiredMixin, UpdateView):
    """
    Opt-in profile editing. Always operates on the logged-in user's own
    record — no pk in the URL, so identity comes from the session.
    """
    model = AlumniProfile
    form_class = AlumniProfileForm
    template_name = "home/alumni_profile_update.html"

    def get_object(self, queryset=None):
        return get_object_or_404(AlumniProfile, user=self.request.user)

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
    """
    template_name = "home/alumni_membership_update.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not hasattr(request.user, "alumni_profile"):
            return redirect("home:uon_alumni_register")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        alumni = get_object_or_404(AlumniProfile, user=request.user)
        current_membership = Membership.objects.current_for(request.user)
        form = MembershipUpdateForm(
            initial={"membership_tier": current_membership.tier_id if current_membership else None}
        )
        pending_payment = alumni.payments.filter(
            payment_status__in=["pending", "pending_verification"]
        ).order_by("-payment_date").first()
        return render(request, self.template_name, {
            "alumni": alumni,
            "current_membership": current_membership,
            "form": form,
            "pending_payment": pending_payment,
        })

    def post(self, request, *args, **kwargs):
        alumni = get_object_or_404(AlumniProfile, user=request.user)
        form = MembershipUpdateForm(request.POST)

        if not form.is_valid():
            return render(request, self.template_name, {"alumni": alumni, "form": form})

        tier = form.cleaned_data["membership_tier"]
        payment = Payment.objects.create(
            alumni=alumni,
            membership_tier=tier,
            amount=tier.fee,
            payment_method=form.cleaned_data["payment_method"],
        )
        Membership.objects.create(user=request.user, tier=tier)
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
        alumni = get_object_or_404(AlumniProfile, user=request.user)
        return render(request, self.template_name, {"alumni": alumni})

    def post(self, request, *args, **kwargs):
        alumni = get_object_or_404(AlumniProfile, user=request.user)
        alumni.is_active = False
        alumni.save(update_fields=["is_active"])
        messages.success(request, "Your alumni profile has been deactivated.")
        logout(request)
        return redirect("home:uon_alumni_home")


def uon_alumni_donate(request):
    return render(request, 'home/uon_alumni_donate.html')


def uon_alumni_scholarship(request):
    return render(request, 'home/uon_alumni_scholarship.html')


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


