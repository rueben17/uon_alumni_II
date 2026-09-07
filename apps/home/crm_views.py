# apps/home/crm_views.py
"""
Secretariat Membership CRM -- a staff-facing console for managing alumni
memberships without the Django admin, for officers who don't live in
/membership-admin/.

Scope: full CRUD over the Membership record, centred on the Secretariat's
real jobs -- find a member, see their standing, correct the record,
record/confirm a payment (which activates the membership), and
cancel/create.

Access: every view is gated by StaffOrSuperuserRequiredMixin (same gate
as MembershipAnalyticsView) -- anonymous users get bounced to login,
authenticated non-staff get a 403.

Reuses existing infrastructure rather than duplicating it:
  - services.assign_membership_tier() to create a pending row
  - Payment.mark_as_completed() -> services.confirm_payment() to activate
  - the HTMX list/partial pattern from apps/staff/views.py:EmployeeListView
"""
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from apps.home.crm_forms import MembershipStaffForm, NewMemberForm, RecordPaymentForm
from apps.home.models import AlumniProfile, Membership, MembershipTier, Payment
from apps.user.mixins import StaffOrSuperuserRequiredMixin


def _member_queryset():
    """One place for the join every CRM view needs -- name/email live on
    user.profile, academics on user.alumni_profile."""
    return Membership.objects.select_related(
        "user", "user__profile", "tier",
        "user__alumni_profile", "user__alumni_profile__faculty",
    )


class MembershipListView(StaffOrSuperuserRequiredMixin, ListView):
    """Searchable, filterable register of memberships + headline stats.

    Mirrors EmployeeListView: an HTMX GET form re-fetches only the table
    partial (get_template_names below), so search/filter feel live but
    every URL stays bookmarkable and works without JS.
    """

    context_object_name = "memberships"
    template_name = "home/crm/membership_list.html"
    paginate_by = 20

    def _selected_status(self):
        value = self.request.GET.get("status", "").strip()
        valid = {v for v, _ in Membership.Status.choices}
        return value if value in valid else ""

    def _selected_tier_type(self):
        value = self.request.GET.get("tier_type", "").strip()
        valid = {v for v, _ in MembershipTier.TIER_TYPES}
        return value if value in valid else ""

    def get_queryset(self):
        qs = _member_queryset()

        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(user__profile__given_name__icontains=query)
                | Q(user__profile__middle_name__icontains=query)
                | Q(user__profile__family_name__icontains=query)
                | Q(user__email__icontains=query)
                | Q(membership_number__icontains=query)
            )

        status = self._selected_status()
        if status:
            qs = qs.filter(status=status)

        tier_type = self._selected_tier_type()
        if tier_type:
            qs = qs.filter(tier__tier_type=tier_type)

        return qs.order_by("-created_at")

    def get_template_names(self):
        if self.request.headers.get("HX-Request") == "true":
            return ["home/crm/_membership_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "")
        context["selected_status"] = self._selected_status()
        context["selected_tier_type"] = self._selected_tier_type()
        context["status_choices"] = Membership.Status.choices
        context["tier_type_choices"] = MembershipTier.TIER_TYPES

        # Headline stats. Cheap counts at today's scale; swap for a single
        # aggregate/values pass if the register grows large.
        base = Membership.objects.all()
        context["stats"] = {
            "total": base.count(),
            "active": base.filter(status=Membership.Status.ACTIVE).count(),
            "pending": base.filter(status=Membership.Status.PENDING).count(),
            "expired": base.filter(status=Membership.Status.EXPIRED).count(),
            "revenue": base.aggregate(s=Sum("subscription_amount"))["s"] or 0,
        }
        return context


class MemberDrawerView(StaffOrSuperuserRequiredMixin, View):
    """The slide-over detail panel, loaded into the list page via HTMX
    (hx-get). Renders a partial, not a full page."""

    def get(self, request, pk):
        membership = get_object_or_404(_member_queryset(), pk=pk)
        alumni = getattr(membership.user, "alumni_profile", None)
        payments = (
            alumni.payments.select_related("membership_tier").all()[:20]
            if alumni else []
        )
        record_form = RecordPaymentForm(initial={
            "amount": membership.tier.fee,
            "payment_method": Payment.PAYMENT_METHODS[0][0],
        })
        return render(request, "home/crm/_member_drawer.html", {
            "membership": membership,
            "alumni": alumni,
            "payments": payments,
            "record_form": record_form,
        })


class MembershipCreateView(StaffOrSuperuserRequiredMixin, View):
    """Add a brand-new member + their first (pending) membership."""

    template_name = "home/crm/membership_form.html"

    def get(self, request):
        return render(request, self.template_name, {
            "form": NewMemberForm(), "mode": "create",
        })

    def post(self, request):
        form = NewMemberForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "mode": "create"})
        user, membership = form.save()
        messages.success(
            request,
            f"{user.profile.full_name} added with a pending "
            f"{membership.tier.name}. Record a payment to activate it.",
        )
        return redirect(reverse("membership_crm:list"))


class MembershipUpdateView(StaffOrSuperuserRequiredMixin, View):
    """Correct a Membership row directly (tier, status, dates, number,
    issued items) -- staff authority, not a member request."""

    template_name = "home/crm/membership_form.html"

    def get(self, request, pk):
        membership = get_object_or_404(_member_queryset(), pk=pk)
        return render(request, self.template_name, {
            "form": MembershipStaffForm(instance=membership),
            "membership": membership,
            "mode": "edit",
        })

    def post(self, request, pk):
        membership = get_object_or_404(_member_queryset(), pk=pk)
        form = MembershipStaffForm(request.POST, instance=membership)
        if not form.is_valid():
            return render(request, self.template_name, {
                "form": form, "membership": membership, "mode": "edit",
            })
        form.save()
        messages.success(request, "Membership record updated.")
        return redirect(reverse("membership_crm:list"))


class RecordPaymentView(StaffOrSuperuserRequiredMixin, View):
    """Record (and optionally confirm) a payment against a membership.

    Confirming runs Payment.mark_as_completed() -> services.confirm_payment(),
    the one door that activates the membership and stamps its number.
    """

    def post(self, request, pk):
        membership = get_object_or_404(_member_queryset(), pk=pk)
        alumni = getattr(membership.user, "alumni_profile", None)
        if alumni is None:
            messages.error(
                request,
                "This member has no alumni profile, so a payment can't be attached. "
                "Create their alumni profile first.",
            )
            return redirect(reverse("membership_crm:list"))

        form = RecordPaymentForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Payment not recorded — check the amount and method.")
            return redirect(reverse("membership_crm:list"))

        payment = Payment.objects.create(
            alumni=alumni,
            membership=membership,
            membership_tier=membership.tier,
            amount=form.cleaned_data["amount"],
            payment_method=form.cleaned_data["payment_method"],
            processed_by=request.user,
        )
        if form.cleaned_data.get("mark_completed"):
            payment.mark_as_completed(form.cleaned_data.get("reference") or None)
            messages.success(request, "Payment recorded and membership activated.")
        else:
            messages.success(request, "Payment recorded (left pending confirmation).")
        return redirect(reverse("membership_crm:list"))


class ConfirmPaymentView(StaffOrSuperuserRequiredMixin, View):
    """Confirm an already-recorded pending payment (the button beside each
    pending payment in the detail drawer)."""

    def post(self, request, payment_id):
        payment = get_object_or_404(Payment, pk=payment_id)
        if payment.is_completed:
            messages.info(request, "That payment was already completed.")
        else:
            payment.mark_as_completed(request.POST.get("reference") or None)
            messages.success(request, "Payment confirmed and membership activated.")
        return redirect(reverse("membership_crm:list"))


class MembershipCancelView(StaffOrSuperuserRequiredMixin, View):
    """Cancel a membership. Soft by default -- sets status=CANCELLED so the
    row (and its number/payment history) survives, matching how
    AlumniProfileDeleteView deactivates rather than hard-deletes. Swap the
    body for `membership.delete()` if the Association wants a hard delete.
    """

    template_name = "home/crm/membership_confirm_delete.html"

    def get(self, request, pk):
        membership = get_object_or_404(_member_queryset(), pk=pk)
        return render(request, self.template_name, {"membership": membership})

    def post(self, request, pk):
        membership = get_object_or_404(_member_queryset(), pk=pk)
        membership.status = Membership.Status.CANCELLED
        membership.save(update_fields=["status", "updated_at"])
        messages.success(request, "Membership cancelled.")
        return redirect(reverse("membership_crm:list"))
