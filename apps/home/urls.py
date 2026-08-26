
from django.urls import path

from apps.home.views import *

app_name = 'home'


def uon_path(suffix, view, name):
    """Prefixes every route (except the homepage itself) with
    'uon-alumni-' in exactly one place (2026-08-07) -- previously typed
    out on every path() call, which meant a rename pass had to touch
    every line. `suffix` still carries its own trailing slash and any
    <converter:kwarg> segments, same as passing straight to path()."""
    return path(f"uon-alumni-{suffix}", view, name=name)


urlpatterns = [
    path("", uon_alumni_home, name="uon_alumni_home"),
    uon_path("history/", uon_alumni_history, "uon_alumni_history"),
    uon_path("executive-committee/", uon_alumni_exec_committee, "uon_alumni_exec_committee"),

    uon_path("gallery/", uon_alumni_gallery, "uon_alumni_gallery"),
    uon_path("register/", AlumniRegisterView.as_view(), "uon_alumni_register"),
    # Grouped under one uon-alumni-profile/ prefix (2026-08-07 URL naming
    # pass) -- detail/edit/membership/delete were previously alumni/ and
    # profile/, inconsistent with the uon-alumni- convention everything
    # else here follows. Only the path strings changed, not the `name=`s,
    # so every {% url %}/reverse() call site keeps working unchanged --
    # only context_processors.py's hardcoded literals needed updating
    # (now reverse()-based instead, so this can't drift again).
    uon_path("profile/<slug:slug>/<uuid:pk>/", AlumniProfileDetailView.as_view(), "alumni_detail"),
    uon_path("profile/<slug:slug>/<uuid:pk>/edit/", AlumniProfileUpdateView.as_view(), "alumni_profile_update"),
    uon_path("profile/<slug:slug>/<uuid:pk>/membership/", AlumniMembershipUpdateView.as_view(), "alumni_membership_update"),
    uon_path("profile/<slug:slug>/<uuid:pk>/delete/", AlumniProfileDeleteView.as_view(), "alumni_profile_delete"),
    uon_path(
        "profile/<slug:slug>/<uuid:pk>/download-qr/",
        download_alumni_qr_code, "alumni_qr_download",
    ),
    uon_path(
        "profile/<slug:slug>/<uuid:pk>/payments/<int:payment_id>/receipt/",
        download_payment_receipt, "payment_receipt_download",
    ),
    uon_path("membership-analytics/", MembershipAnalyticsView.as_view(), "membership_analytics"),
    uon_path("membership-categories/", MembershipCategoriesView.as_view(), "membership_categories"),
    uon_path("donate/", uon_alumni_donate, "uon_alumni_donate"),
    uon_path("scholarship/", uon_alumni_scholarship, "uon_alumni_scholarship"),
    uon_path("in-memoriam/", uon_alumni_in_memoriam, "uon_alumni_in_memoriam"),
    uon_path("contact-us/", uon_alumni_contact_us, "uon_alumni_contact_us"),

    # "Find my profile" pre-login claim flow (2026-08-20) -- search ->
    # email OTP -> connect on next Google login. See apps.home.views'
    # ProfileClaim* views and apps.user.adapter's pre_social_login().
    uon_path("claim-profile/", ProfileClaimSearchView.as_view(), "uon_alumni_claim_search"),
    uon_path("claim-profile/verify/", ProfileClaimVerifyView.as_view(), "uon_alumni_claim_verify"),
    uon_path("claim-profile/continue/", ProfileClaimContinueView.as_view(), "uon_alumni_claim_continue"),

    # C.1 (todo.md): these three names are exactly what Article/Event/
    # Chapter.get_absolute_url() already reverse() against -- adding
    # them is what turns those from a NoReverseMatch 500 into a real page.
    uon_path("news/", ArticleListView.as_view(), "uon_alumni_article_list"),
    uon_path("news/<slug:slug>/", ArticleDetailView.as_view(), "uon_alumni_article_detail"),

    uon_path("walk/", EventListView.as_view(), "uon_alumni_walk_list"),
    uon_path("walk/<slug:slug>/", EventDetailView.as_view(), "uon_alumni_walk_detail"),

    uon_path("chapters/", ChapterListView.as_view(), "uon_alumni_chapter_list"),
    # Two patterns, same name: Chapter.get_absolute_url() reverses this
    # with 2 args when it has a faculty, 1 when it doesn't -- reverse()
    # picks whichever pattern's arg count matches.
    uon_path("chapters/<slug:faculty_slug>/<slug:slug>/", ChapterDetailView.as_view(), "uon_alumni_chapter_detail"),
    uon_path("chapters/<slug:slug>/", ChapterDetailView.as_view(), "uon_alumni_chapter_detail"),

    # Nav wiring (navbar/footer): the rest of the "About"/"Membership" pages.
    uon_path("secretariat/", uon_alumni_secretariat, "uon_alumni_secretariat"),
    uon_path("partners/", uon_alumni_partners, "uon_alumni_partners"),
    uon_path("mission-vision/", uon_alumni_mission_vision, "uon_alumni_mission_vision"),
    uon_path("downloads/", PublicationListView.as_view(), "uon_alumni_downloads"),
    uon_path("careers/", JobPostingListView.as_view(), "uon_alumni_careers"),
    # One route for every remaining standing page -- see standing_page()'s
    # own docstring for why this is generic rather than nine near-duplicates.
    uon_path("page/<slug:page_key>/", standing_page, "standing_page"),
    # The Alumni Digital ID application form lives ON this SAME standing
    # page (2026-08-21, explicit correction -- not a separate page under
    # /profile/.../), just with the alumni's slug+pk appended so
    # standing_page() knows whose profile to attach the uploaded photo
    # to. page_key is injected as a fixed kwarg (not parsed from the
    # URL) since this route is digital-id-specific -- bypasses
    # uon_path() directly since that helper has no room for extra kwargs.
    path(
        "uon-alumni-page/digital-id/<slug:slug>/<uuid:pk>/",
        standing_page, {"page_key": "digital-id"}, name="alumni_digital_id_apply",
    ),
    # Old pre-rename slugged path (2026-08-21) -- the bare
    # /uon-alumni-page/alumni-card/ URL is already caught by the generic
    # page/<page_key>/ route's own redirect (standing_page()'s
    # page_key == "alumni-card" branch), but that generic route has no
    # <slug>/<pk> segments, so the slugged variant needs its own path to
    # even reach the view at all instead of 404ing before the redirect
    # logic ever runs.
    path(
        "uon-alumni-page/alumni-card/<slug:slug>/<uuid:pk>/",
        standing_page, {"page_key": "alumni-card"}, name="alumni_digital_id_apply_legacy",
    ),
]
