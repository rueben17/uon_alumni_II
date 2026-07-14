from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DetailView, UpdateView, View

from apps.home.forms import AlumniProfileForm, AlumniRegistrationForm, MembershipUpdateForm
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
    return render(request, 'home/uon_alumni_gallery.html')



def uon_alumni_exec_committee(request):
    executives = Executive.objects.all().order_by('rank')

    
    context = {
        "executives": executives,

    }
    # print(treasurer)
    return render(request, 'home/uon_alumni_exec_committee.html', context)



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
        initiate_payment(payment)

        messages.success(self.request, "Welcome! Your alumni profile is complete.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class AlumniProfileDetailView(DetailView):
    """
    Public alumni profile page — mirrors staff's EmployeeDetailView.
    """
    model = AlumniProfile
    template_name = "home/alumni_detail.html"
    context_object_name = "alumni"

    def get_object(self, queryset=None):
        return get_object_or_404(AlumniProfile, is_active=True, pk=self.kwargs["pk"])


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
    tier). Only records the request as a Payment -- actually calling
    AlumniProfile.renew_membership()/upgrade_to_lifetime() (and
    generating the membership number) happens in the Membership Admin
    site once a Secretariat member confirms the payment (see
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
        form = MembershipUpdateForm(initial={"membership_tier": alumni.current_membership_tier_id})
        pending_payment = alumni.payments.filter(
            payment_status__in=["pending", "pending_verification"]
        ).order_by("-payment_date").first()
        return render(request, self.template_name, {
            "alumni": alumni,
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
    return render(request, 'home/uon_alumni_contact_us.html')


