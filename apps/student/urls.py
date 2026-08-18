from django.urls import include, path
from django.views.generic import TemplateView
from apps.student.views import*

app_name = 'student'

urlpatterns = [
       # path('', include('apps.home.urls', namespace='home')),

       # 2026-08-18 SEO audit: students. is noindex,nofollow site-wide,
       # and robots.txt must be served per-host, at this subdomain's own
       # root -- templates/robots.txt branches on request.subdomain.
       path("robots.txt", TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name="robots_txt"),
       path("", all_uon_students, name="all_uon_students"),
       path("register/", StudentRegisterView.as_view(), name="register"),
       path("evaluate/", EvaluateApplicationView.as_view(), name="evaluate_application_list"),
       path("evaluate/<int:pk>/", EvaluateApplicationView.as_view(), name="evaluate_application"),
       path("dashboard/", ApplicantDashboardView.as_view(), name="applicant_dashboard"),
       path("dashboard/export/", ScholarshipAnalyticsExportView.as_view(), name="analytics_export"),

]