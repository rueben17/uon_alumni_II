from allauth.account.adapter import get_adapter
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import CreateView

from apps.student.forms import StudentRegisterForm
from apps.student.models import Student


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
