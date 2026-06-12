from django.urls import include, path
from apps.student.views import*

app_name = 'student'

urlpatterns = [
       # path('', include('apps.home.urls', namespace='home')),

       path("", all_uon_students, name="all_uon_students"), 

]