
from django.urls import path

from apps.home.views import *

app_name = 'home'



urlpatterns = [
    path("", uon_alumni_home, name="uon_alumni_home"),
    path("history/", uon_alumni_history, name="uon_alumni_history"),
    path("executive-committee/", uon_alumni_exec_committee, name="uon_alumni_exec_committee"),

    path("uon-alumni-gallery/", uon_alumni_gallery, name="uon_alumni_gallery"),
    path("uon-alumni-register/", uon_alumni_register, name="uon_alumni_register"),
    path("uon-alumni-donate/", uon_alumni_donate, name="uon_alumni_donate"),
    path("uon-alumni-scholarship/", uon_alumni_scholarship, name="uon_alumni_scholarship"),
    path("uon-alumni-in-memoriam/", uon_alumni_in_memoriam, name="uon_alumni_in_memoriam"),
    path("uon-alumni-contact-us/", uon_alumni_contact_us, name="uon_alumni_contact_us"),
]
