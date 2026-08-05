
from django.urls import path

from apps.home.views import *

app_name = 'home'



urlpatterns = [
    path("", uon_alumni_home, name="uon_alumni_home"),
    path("history/", uon_alumni_history, name="uon_alumni_history"),
    path("executive-committee/", uon_alumni_exec_committee, name="uon_alumni_exec_committee"),

    path("uon-alumni-gallery/", uon_alumni_gallery, name="uon_alumni_gallery"),
    path("uon-alumni-register/", AlumniRegisterView.as_view(), name="uon_alumni_register"),
    path("alumni/<slug:slug>/<uuid:pk>/", AlumniProfileDetailView.as_view(), name="alumni_detail"),
    path("profile/edit/", AlumniProfileUpdateView.as_view(), name="alumni_profile_update"),
    path("profile/membership/", AlumniMembershipUpdateView.as_view(), name="alumni_membership_update"),
    path("profile/delete/", AlumniProfileDeleteView.as_view(), name="alumni_profile_delete"),
    path("uon-alumni-donate/", uon_alumni_donate, name="uon_alumni_donate"),
    path("uon-alumni-scholarship/", uon_alumni_scholarship, name="uon_alumni_scholarship"),
    path("uon-alumni-in-memoriam/", uon_alumni_in_memoriam, name="uon_alumni_in_memoriam"),
    path("uon-alumni-contact-us/", uon_alumni_contact_us, name="uon_alumni_contact_us"),

    # C.1 (todo.md): these three names are exactly what Article/Event/
    # Chapter.get_absolute_url() already reverse() against -- adding
    # them is what turns those from a NoReverseMatch 500 into a real page.
    path("news/", ArticleListView.as_view(), name="uon_alumni_article_list"),
    path("news/<slug:slug>/", ArticleDetailView.as_view(), name="uon_alumni_article_detail"),

    path("uon-alumni-walk/", EventListView.as_view(), name="uon_alumni_walk_list"),
    path("uon-alumni-walk/<slug:slug>/", EventDetailView.as_view(), name="uon_alumni_walk_detail"),

    path("chapters/", ChapterListView.as_view(), name="uon_alumni_chapter_list"),
    # Two patterns, same name: Chapter.get_absolute_url() reverses this
    # with 2 args when it has a faculty, 1 when it doesn't -- reverse()
    # picks whichever pattern's arg count matches.
    path("chapters/<slug:faculty_slug>/<slug:slug>/", ChapterDetailView.as_view(), name="uon_alumni_chapter_detail"),
    path("chapters/<slug:slug>/", ChapterDetailView.as_view(), name="uon_alumni_chapter_detail"),

    # Nav wiring (navbar/footer): the rest of the "About"/"Membership" pages.
    path("secretariat/", uon_alumni_secretariat, name="uon_alumni_secretariat"),
    path("partners/", uon_alumni_partners, name="uon_alumni_partners"),
    path("mission-vision/", uon_alumni_mission_vision, name="uon_alumni_mission_vision"),
    path("downloads/", PublicationListView.as_view(), name="uon_alumni_downloads"),
    path("careers/", JobPostingListView.as_view(), name="uon_alumni_careers"),
    # One route for every remaining standing page -- see standing_page()'s
    # own docstring for why this is generic rather than nine near-duplicates.
    path("page/<slug:page_key>/", standing_page, name="standing_page"),
]
