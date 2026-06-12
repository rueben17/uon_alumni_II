from django.urls import include, path
from apps.staff.views import*

app_name = 'staff'

urlpatterns = [
       # path('', include('apps.home.urls', namespace='home')),

       path("", all_uon_staff, name="all_uon_staff"), 

]