from django.urls import include, path
from apps.staff.views import*

app_name = 'staff'

urlpatterns = [
       # path('', include('apps.home.urls', namespace='home')),

       path("", all_uon_staff, name="all_uon_staff"),
       path('accounts/', include('allauth.urls')),
       # path('complete-profile/<uuid:uuid>/', views.complete_profile, name='complete_profile')
       # path('qr/<slug:slug>/<uuid:employee_id>/<str:token>/', views.qr_redirect, name='qr_redirect'), 

]