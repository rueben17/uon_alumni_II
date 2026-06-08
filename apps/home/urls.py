from django.http import HttpResponse
from django.urls import path

from apps.home.views import *

app_name = 'home'



urlpatterns = [
    path("", uon_alumni_home, name="uon_alumni_home"),
    path("history/", uon_alumni_history, name="uon_alumni_history"),

    path("uon-alumni-gallery/", uon_alumni_gallery, name="uon_alumni_gallery"),
]
