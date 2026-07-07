import io

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.generic import DetailView, ListView, UpdateView, View
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer

from apps.staff.forms import CompleteProfileForm
from apps.staff.models import Department, Employee, ResearchUnit, ServiceUnit


def _get_or_create_staff_employee(user):
    employee = getattr(user, "employee", None)
    if employee is not None:
        return employee

    employee, _ = Employee.objects.get_or_create(
        user=user,
        defaults={
            "given_name": user.given_name,
            "family_name": user.family_name,
            "google_photo_url": user.google_photo_url,
        },
    )
    user.employee = employee
    return employee


def staff_dashboard(request):
    return HttpResponse("Staff dashboard")


class StaffLoginView(View):
    """
    Legacy staff landing page — no templates link here anymore
    (Sign In goes to /accounts/google/login/ directly). Deletion
    candidate for the cleanup commit; kept so old links don't 404.
    """

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            employee = _get_or_create_staff_employee(request.user)
            if not employee.profile_is_complete:
                return redirect(
                    "staff:complete_profile",
                    uuid=employee.id,
                )
            return redirect(employee.get_absolute_url())
        return render(request, "staff/staff_login.html")


def staff_logout(request):
    """
    Legacy logout endpoint — kept so old links don't break, but
    behaves exactly like the shared /accounts/logout/ flow:
    log out, then land on the main site's home page.
    """
    logout(request)
    host = request.get_host()
    port = ":" + host.split(":")[1] if ":" in host else ""
    scheme = "https" if request.is_secure() else "http"
    return redirect(f"{scheme}://{settings.SUBDOMAIN_DOMAIN}{port}/")


class EmployeeListView(LoginRequiredMixin, ListView):
    """
    Public staff directory — all active employees.
    """
    model = Employee
    template_name = "staff/all_uon_staff.html"
    context_object_name = "employees"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            Employee.objects
            .filter(is_active=True)
            .select_related(
                "user", "department", "service_unit",
                "research_unit", "position",
            )
            .order_by("family_name", "given_name")
        )

        # Live search: ?q=jane+doe
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(given_name__icontains=query)
                | Q(family_name__icontains=query)
                | Q(middle_name__icontains=query)
            )

        # Unified unit filter:
        # ?unit=department:<id> | service:<id> | research:<id>
        unit = self.request.GET.get("unit", "").strip()
        if unit and ":" in unit:
            unit_type, unit_id = unit.split(":", 1)
            if unit_type == "department":
                qs = qs.filter(department_id=unit_id)
            elif unit_type == "service":
                qs = qs.filter(service_unit_id=unit_id)
            elif unit_type == "research":
                qs = qs.filter(research_unit_id=unit_id)

        # Backward compatibility for old links that still send ?department=<id>
        department = self.request.GET.get("department", "").strip()
        if department and not unit:
            qs = qs.filter(department_id=department)

        # Filter: ?track=teaching
        track = self.request.GET.get("track", "").strip()
        if track:
            qs = qs.filter(staff_track=track)

        return qs

    def get_template_names(self):
        if self.request.headers.get("HX-Request") == "true":
            return ["staff/partials/employee_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "")
        context["selected_unit"] = self.request.GET.get("unit", "")
        context["selected_track"] = self.request.GET.get("track", "")
        context["track_choices"] = Employee.StaffTrack.choices
        departments = Department.objects.order_by("name")
        service_units = ServiceUnit.objects.order_by("name")
        research_units = ResearchUnit.objects.order_by("name")

        context["department_unit_options"] = [
            {"value": f"department:{department.id}", "label": department.name}
            for department in departments
        ]
        context["service_unit_options"] = [
            {"value": f"service:{service_unit.id}", "label": service_unit.name}
            for service_unit in service_units
        ]
        context["research_unit_options"] = [
            {"value": f"research:{research_unit.id}", "label": research_unit.name}
            for research_unit in research_units
        ]
        return context


class CompleteProfileView(LoginRequiredMixin, UpdateView):
    """
    One-time onboarding. The adapter's completeness gate sends every
    incomplete login here; once the profile is complete, this view
    bounces to ProfileUpdateView for any further edits.
    """
    model = Employee
    form_class = CompleteProfileForm
    template_name = "staff/complete_profile.html"
    context_object_name = "employee"
    pk_url_kwarg = "uuid"  # matches URL parameter

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            employee = getattr(request.user, "employee", None)
            if employee and employee.profile_is_complete:
                return redirect("staff:profile_update")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # Only allow editing the logged-in user's own profile
        return Employee.objects.filter(user=self.request.user)

    def get_success_url(self):
        # After saving, redirect to the pretty profile URL
        return self.object.get_absolute_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Your profile is complete!")
        return response


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """
    Opt-in profile editing after onboarding. Always operates on the
    logged-in user's own record — no UUID in the URL, so identity
    comes from the session and there's nothing to tamper with.
    """
    model = Employee
    form_class = CompleteProfileForm  # dedicated ProfileUpdateForm later if fields diverge
    template_name = "staff/profile_update.html"
    context_object_name = "employee"

    def get_object(self, queryset=None):
        return get_object_or_404(Employee, user=self.request.user)

    def get_success_url(self):
        # Slug may have changed (AutoSlugField recomputes on save),
        # so land on the freshly recalculated canonical URL.
        return self.object.get_absolute_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Profile updated.")
        return response


class ProfileDeleteView(LoginRequiredMixin, View):
    """
    Owner-only profile deletion with explicit confirmation.
    Deleting the Employee profile does not delete the User account.
    """

    template_name = "staff/profile_delete_confirm.html"

    def get(self, request, *args, **kwargs):
        employee = get_object_or_404(Employee, user=request.user)
        return render(request, self.template_name, {"employee": employee})

    def post(self, request, *args, **kwargs):
        employee = get_object_or_404(Employee, user=request.user)
        employee.is_active = False
        employee.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Your staff profile has been deactivated.")
        logout(request)

        host = request.get_host()
        port = ":" + host.split(":")[1] if ":" in host else ""
        scheme = "https" if request.is_secure() else "http"
        return redirect(f"{scheme}://{settings.SUBDOMAIN_DOMAIN}{port}/")


class EmployeeDetailView(DetailView):
    model = Employee
    template_name = "staff/staff_detail.html"
    context_object_name = "employee"

    def get_object(self, queryset=None):
        return get_object_or_404(
            Employee.objects
            .select_related(
                "user", "department", "service_unit",
                "research_unit", "position",
            )
            .filter(is_active=True),
            pk=self.kwargs["uuid"],
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Canonical-URL redirect (slug changed, old link, etc.).
        # Guarded to the staff subdomain: get_absolute_url() returns
        # the subdomain-relative path, which never matches the
        # /staff/-prefixed path on the main domain — comparing there
        # would redirect every request into a 404.
        # permanent=False while in active development: browsers cache
        # 301s aggressively, and slugs legitimately change on profile
        # edits. Flip to True only if slugs are ever frozen.
        if getattr(request, "subdomain", None) == "staff":
            canonical_url = self.object.get_absolute_url()
            if request.path != canonical_url:
                return redirect(canonical_url, permanent=False)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        employee = self.object

        if hasattr(employee, "publications"):
            context["publications"] = employee.publications.all()[:5]
            context["has_publications"] = employee.publications.exists()
        else:
            context["publications"] = []
            context["has_publications"] = False

        if hasattr(employee, "projects"):
            projects = employee.projects.filter(is_active=True)
            context["projects"] = projects
            context["has_projects"] = projects.exists()
        else:
            context["projects"] = []
            context["has_projects"] = False

        return context


def staff_detail_fallback(request, uuid):
    """
    Stable UUID landing page. Reached when an employee's profile is
    incomplete (get_absolute_url routes here) — including via QR
    scans, which encode this URL precisely because it never changes.
    """
    employee = get_object_or_404(Employee, id=uuid)

    return render(
        request,
        "staff/staff_detail_fallback.html",
        {
            "employee": employee,
            "can_complete": (
                request.user.is_authenticated
                and employee.user == request.user
                and not employee.profile_is_complete
            ),
        },
    )


def download_staff_qr_code(request, staff_slug, pk):
    employee = get_object_or_404(Employee, slug=staff_slug, id=pk)

    if not employee.qr_code_image:
        return HttpResponse("QR code not found", status=404)
    
    safe_name = slugify(employee.display_name) or "staff"
    file_format = request.GET.get("format", "pdf").lower()

    if file_format == "png":
        employee.qr_code_image.open("rb")
        image_bytes = employee.qr_code_image.read()
        employee.qr_code_image.close()
        response = HttpResponse(image_bytes, content_type="image/png")
        response["Content-Disposition"] = f'attachment; filename="{safe_name}_qr.png"'
        return response

    pdf_buffer = io.BytesIO()
    pdf_title = f"{employee.display_name} QR Code"
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        title=pdf_title,
        author="UoN Alumni",
    )
    elements = []

    styles = getSampleStyleSheet()
    styles["Title"].alignment = TA_CENTER
    name_title = Paragraph(employee.display_name, style=styles["Title"])
    elements.append(name_title)
    elements.append(Spacer(1, 0.12 * inch))

    unit_name = employee.unit.name if employee.unit else "Unassigned Unit"
    unit_label = Paragraph(unit_name, style=styles["Title"])
    elements.append(unit_label)
    elements.append(Spacer(1, 0.25 * inch))

    qr_path = employee.qr_code_image.path
    img = RLImage(qr_path, width=5 * inch, height=5 * inch)
    img.hAlign = "CENTER"
    elements.append(img)

    doc.build(elements)

    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{safe_name}_qr.pdf"'
    return response