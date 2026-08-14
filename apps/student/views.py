from allauth.account.adapter import get_adapter
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, TemplateView, View

from apps.student.forms import SCORE_FIELDS, InterviewScoreSheetForm, StudentRegisterForm, score_field_max
from apps.student.models import County, Gender, ScholarshipApplication, Student
from apps.user.mixins import StaffOrSuperuserRequiredMixin

# Counties past this rank in the distribution collapse into a single
# "Other" bucket on the dashboard's bar chart -- a 47-bar chart is as
# unreadable as a 47-slice pie.
COUNTY_TOP_N = 15


def all_uon_students(request):
    context = {}
    return render(request, "student/all_uon_students.html", context)


class StudentRegisterView(LoginRequiredMixin, CreateView):
    """
    One-time student sign-up. apps/user/adapter.py's login/signup
    redirect logic sends every authenticated user without a Student
    record here -- see its "Students: no auto-created stub" note for why
    this is a real form (mirroring AlumniRegisterView) rather than
    staff's auto-stub-then-complete flow.

    The @students.uonbi.ac.ke restriction is re-checked here, not just
    at the Google-login step in apps/user/adapter.py's pre_social_login():
    this view is also reachable via the bare domain's /students/ prefix
    (main/urls.py, kept for backward compatibility), which has no
    subdomain of its own for that check to key off. Re-checking here
    means the restriction holds regardless of which host served the
    page, not just the one true entry point.
    """
    model = Student
    form_class = StudentRegisterForm
    template_name = "student/register.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if hasattr(request.user, "student"):
                return redirect(self._post_register_url())

            from apps.user.adapter import ALLOWED_STUDENT_LOGIN_DOMAINS, RESTRICT_GOOGLE_LOGIN_DOMAINS

            if RESTRICT_GOOGLE_LOGIN_DOMAINS:
                domain = request.user.email.split("@")[-1].lower()
                if domain not in ALLOWED_STUDENT_LOGIN_DOMAINS:
                    messages.error(
                        request,
                        "Student sign-up needs your @students.uonbi.ac.ke Google account -- "
                        "please sign out and sign in again from the students portal.",
                    )
                    return redirect("home:uon_alumni_home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.user = self.request.user
        # The students subdomain only accepts @students.uonbi.ac.ke Google
        # accounts (dispatch() above, apps/user/adapter.py's
        # pre_social_login()) -- sign-in IS this address, so there's
        # nothing further to ask for it.
        form.instance.student_email = self.request.user.email
        response = super().form_valid(form)
        messages.success(self.request, "You're signed up! You can now apply for the scholarship.")
        return response

    def get_success_url(self):
        return self._post_register_url()

    def _post_register_url(self):
        # Set by apps.home.views.uon_alumni_scholarship for an anonymous
        # or not-yet-registered visitor -- honoured here so finishing
        # sign-up lands them back where they started, not just on the
        # generic students landing page.
        next_url = self.request.session.pop("post_login_next", None)
        if next_url and get_adapter().is_safe_url(next_url):
            return next_url
        return reverse("student:all_uon_students")


class EvaluateApplicationView(StaffOrSuperuserRequiredMixin, View):
    """
    Two-pane interview scoring screen: the applicant's uploaded PDF
    alongside InterviewScoreSheet's scoring matrix. One score sheet per
    ScholarshipApplication (OneToOne, related_name="score_sheet") --
    get-or-create semantics, not plain create, so revisiting an already-
    scored application reopens it for editing instead of erroring.

    evaluator is never a form field (InterviewScoreSheetForm excludes
    both application and evaluator) -- both are set here from the URL
    and request.user.employee respectively, never from POST data.

    pk is optional (2026-08-14, student:evaluate_application_list route)
    -- with no pk, this renders just the applicant picker with nothing
    selected yet, the landing page the new navbar link and the picker's
    own "no selection" state both need. The picker itself is always in
    context/rendered regardless, letting staff jump to a different
    applicant from the two-pane screen too.
    """
    template_name = "student/evaluate_application.html"

    def _get_application(self, pk):
        if pk is None:
            return None
        return get_object_or_404(
            ScholarshipApplication.objects.select_related("student", "faculty", "department", "score_sheet"),
            pk=pk,
        )

    def _total_possible(self):
        return sum(score_field_max(name) for name in SCORE_FIELDS)

    def _context(self, application, form):
        # Bound fields, not raw names -- {{ form.field_name }} can't
        # resolve a dynamic template variable (Django's dotted-variable
        # lookup only splits literal tokens), so the per-criterion
        # {field, max} pairs are built here in Python instead, where
        # form[name] works with a variable just fine.
        score_rows = [(form[name], score_field_max(name)) for name in SCORE_FIELDS] if form else []
        # Lightweight, single query -- only the fields the picker's
        # <option> labels need, not full application rows.
        applicants = ScholarshipApplication.objects.only(
            "id", "first_name", "surname", "registration_number"
        ).order_by("surname", "first_name")
        return {
            "application": application,
            "form": form,
            "score_rows": score_rows,
            "total_possible": self._total_possible(),
            "applicants": applicants,
        }

    def get(self, request, pk=None):
        application = self._get_application(pk)
        form = None
        if application is not None:
            score_sheet = getattr(application, "score_sheet", None)
            initial = {} if score_sheet else {"course_undertaking": application.current_course}
            form = InterviewScoreSheetForm(instance=score_sheet, initial=initial)
        return render(request, self.template_name, self._context(application, form))

    def post(self, request, pk=None):
        application = self._get_application(pk)
        if application is None:
            # Nothing to score without an applicant -- the picker's own
            # navigation (GET) is how one gets chosen; POSTing here with
            # no pk isn't a reachable path through the rendered form.
            return redirect("student:evaluate_application_list")

        score_sheet = getattr(application, "score_sheet", None)
        form = InterviewScoreSheetForm(request.POST, instance=score_sheet)

        if form.is_valid():
            evaluator = getattr(request.user, "employee", None)
            if evaluator is None:
                form.add_error(None, "Your account has no staff Employee record -- cannot record an evaluation.")
            else:
                sheet = form.save(commit=False)
                sheet.application = application
                sheet.evaluator = evaluator
                sheet.save()
                messages.success(request, f"Evaluation saved -- total score {sheet.total_score}/{self._total_possible()}.")
                return redirect("student:evaluate_application", pk=pk)

        return render(request, self.template_name, self._context(application, form))


class ApplicantDashboardView(StaffOrSuperuserRequiredMixin, TemplateView):
    """
    Applicant distribution by faculty/gender/county -- three charts,
    each backed by exactly one annotated .values().annotate(Count(...))
    query (no per-applicant Python loop). Renders fine on an empty
    ScholarshipApplication table -- .values().annotate() over zero rows
    is just an empty list, and Chart.js draws an empty axis/canvas for
    empty labels/data rather than erroring.
    """
    template_name = "student/applicant_dashboard.html"

    def _faculty_chart_data(self):
        rows = (
            ScholarshipApplication.objects.values("faculty__faculty_name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return {
            "labels": [row["faculty__faculty_name"] or "Unspecified" for row in rows],
            "counts": [row["count"] for row in rows],
        }

    def _gender_chart_data(self):
        rows = ScholarshipApplication.objects.values("gender").annotate(count=Count("id")).order_by("-count")
        labels = dict(Gender.choices)
        return {
            "labels": [labels.get(row["gender"], row["gender"]) for row in rows],
            "counts": [row["count"] for row in rows],
        }

    def _county_chart_data(self):
        rows = list(
            ScholarshipApplication.objects.values("county_of_residence")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        labels = dict(County.choices)
        # Splitting top-N from the rest below is Python work over the
        # already-aggregated result (at most 47 rows), not a loop over
        # ScholarshipApplication rows themselves -- the query above is
        # still the only trip to the database this chart makes.
        top, rest = rows[:COUNTY_TOP_N], rows[COUNTY_TOP_N:]
        chart_labels = [labels.get(row["county_of_residence"], row["county_of_residence"]) for row in top]
        chart_counts = [row["count"] for row in top]
        if rest:
            chart_labels.append("Other")
            chart_counts.append(sum(row["count"] for row in rest))
        return {"labels": chart_labels, "counts": chart_counts}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["faculty_data"] = self._faculty_chart_data()
        context["gender_data"] = self._gender_chart_data()
        context["county_data"] = self._county_chart_data()
        return context
