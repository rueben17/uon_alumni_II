from django.urls import include, path
from apps.student.views import*

app_name = 'student'

urlpatterns = [
       # path('', include('apps.home.urls', namespace='home')),

       path("", all_uon_students, name="all_uon_students"),
       path("register/", StudentRegisterView.as_view(), name="register"),
       path("evaluate/", EvaluateApplicationView.as_view(), name="evaluate_application_list"),
       path("evaluate/<int:pk>/", EvaluateApplicationView.as_view(), name="evaluate_application"),
       path("dashboard/", ApplicantDashboardView.as_view(), name="applicant_dashboard"),

]