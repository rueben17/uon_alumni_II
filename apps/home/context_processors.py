import json

from apps.home.models import *
from datetime import*
from django.conf import settings
from django.urls import reverse
from django.utils import timezone as tz
from django.utils.timezone import now
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404


DEFAULT_PAGE_BACKGROUND_URL = (
    "https://res.cloudinary.com/doh3hvrdz/image/upload/v1786040065/"
    "Fountain_of_Knowledge_-_Prof_Yanjik_k2qvyp.png"
)
DEFAULT_TOP_BANNER_URL = (
    "https://res.cloudinary.com/doh3hvrdz/image/upload/v1/media/gallery/"
    "uploads/2026/04/27/old_pic_uon_great_court_yl18hh"
)
DEFAULT_SITE_LOGO_URL = (
    "https://res.cloudinary.com/doh3hvrdz/image/upload/q_auto/f_auto/"
    "v1781224354/UONAA_Original_Logo_Blue_1_lgwkmu.png"
)
DEFAULT_FOOTER_BACKGROUND_URL = (
    "https://res.cloudinary.com/doh3hvrdz/image/upload/v1777444013/"
    "65cb94b385f8fa001e7f6fb7_hhlhzt.jpg"
)
DEFAULT_FOOTER_LOGO_URL = (
    "https://res.cloudinary.com/doh3hvrdz/image/upload/q_auto/f_auto/"
    "v1777444403/UONAA_Original_Logo_White_xca2yr.png"
)

# Promoted to module level (2026-08-18, SEO audit) so seo()'s JSON-LD
# Organization block and contacts()'s template context read the exact
# same values -- previously these were local to contacts() only, and
# duplicating them into seo() as separate literals would have been a
# drift risk (edit one, forget the other) for facts that also feed
# structured data search engines actually validate against.
ASSOCIATION_NAME = 'University of Nairobi Alumni Association'
ASSOCIATION_WEBSITE = 'uonalumni.or.ke'
ASSOCIATION_ADDRESS = 'KOLOBOT DRIVE, OFF STATE HOUSE RD, OFF ABORETUM DRIVE.'
ASSOCIATION_POSTAL = 'P. O. BOX 30490 - 00100, NAIROBI.'


def _first_image_url(banners, field_name, default):
    """First non-empty <field_name> across every Banner row, or default
    if none has one set. Iterates an already-fetched list rather than a
    fresh .exclude(...).first() query per field -- images() needs this
    for five different fields now, and banner_images is already fetched
    for its own sake (used elsewhere), so this reuses that one query
    instead of five more.
    """
    for banner in banners:
        file = getattr(banner, field_name)
        if file:
            return file.url
    return default


def images(request):
    banner_images = list(Banner.objects.all())

    # One admin-editable image per site-wide visual instead of a
    # Cloudinary URL hardcoded into every template that uses it
    # (2026-08-14) -- see the Banner model's own comments for which
    # field maps to which visual. Each falls back to the original
    # hardcoded image so nothing changes visually until an admin
    # actually uploads a replacement.
    page_background_url = _first_image_url(banner_images, "page_background", DEFAULT_PAGE_BACKGROUND_URL)
    top_banner_url = _first_image_url(banner_images, "top_banner", DEFAULT_TOP_BANNER_URL)
    site_logo_url = _first_image_url(banner_images, "logo", DEFAULT_SITE_LOGO_URL)
    footer_background_url = _first_image_url(banner_images, "bottom_banner", DEFAULT_FOOTER_BACKGROUND_URL)
    footer_logo_url = _first_image_url(banner_images, "footer_logo", DEFAULT_FOOTER_LOGO_URL)

    return {
        "banner_images": banner_images,
        "page_background_url": page_background_url,
        "top_banner_url": top_banner_url,
        "site_logo_url": site_logo_url,
        "footer_background_url": footer_background_url,
        "footer_logo_url": footer_logo_url,
    }

# def ads(request):
#     ads = Ad.objects.all()

#     return {
#         "ads": ads
#     }



def seo(request):
    """Canonical URL + a sensible default robots directive, computed once
    per request so every page gets a correct value without repeating this
    logic in every template. base.html renders both inside overridable
    blocks (canonical_url / robots) -- a specific page (e.g. an
    authenticated or admin-adjacent view that isn't already covered by
    the subdomain-wide or pagination rules below) overrides the block
    directly rather than this processor growing per-page special cases.

    canonical_url: request.build_absolute_uri(request.path) -- deliberately
    path only (query string dropped), so a paginated/filtered URL
    canonicalizes to the same page as its plain form, one canonical per
    page as required. Uses the real request host, so it's correct on
    whichever subdomain served the request without a lookup table.

    default_robots: staff./students. subdomains are noindex, nofollow on
    every page (SEO audit decision, 2026-08-18 -- both are internal/
    enrollment-gated tooling). A paginated page beyond page 1 is noindex,
    follow. Everything else defaults to index, follow.

    organization_jsonld: pre-serialized via json.dumps(), not interpolated
    field-by-field in the template -- Django's {{ var }} auto-escaping is
    HTML escaping (turns '"' into '&quot;'), not JSON/JS escaping, which
    would silently produce invalid JSON-LD the moment any of these values
    ever contained a double quote. json.dumps() here is the correct
    escaping for a <script type="application/ld+json"> body. Uses the
    static DEFAULT_SITE_LOGO_URL, not images()'s per-request
    Banner-overridden site_logo_url -- structured data should reflect the
    association's one canonical brand logo, not whatever seasonal banner
    image happens to be set, and this avoids a second Banner query on
    every single request just for that.
    """
    canonical_url = request.build_absolute_uri(request.path)
    # Pinned to main.urls (only urlconf 'sitemap' is defined in) same as
    # every other cross-subdomain reverse() in this file -- robots.txt is
    # served on staff./students. too (apps/staff/site_urls.py,
    # apps/student/urls.py both mount templates/robots.txt), where the
    # active urlconf has no 'sitemap' name at all.
    sitemap_url = request.build_absolute_uri(reverse('sitemap', urlconf='main.urls'))

    subdomain = getattr(request, 'subdomain', None)
    if subdomain in ('staff', 'students'):
        default_robots = 'noindex, nofollow'
    elif request.GET.get('page') not in (None, '', '1'):
        default_robots = 'noindex, follow'
    else:
        default_robots = 'index, follow'

    base = 'http://lvh.me:8000' if settings.DEBUG else 'https://uonalumni.or.ke'
    organization_jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": ASSOCIATION_NAME,
        # alternateName, not a second Organization block and not merged
        # into "name" -- 2026-08-18 refinement, so the abbreviation
        # accumulates authority against the full name as the same
        # entity, rather than competing with it as a separate one.
        "alternateName": "UoNAA",
        "url": f"{base}/",
        "logo": DEFAULT_SITE_LOGO_URL,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": ASSOCIATION_ADDRESS,
            "addressLocality": "Nairobi",
            "addressCountry": "KE",
        },
    })

    return {
        'canonical_url': canonical_url,
        'default_robots': default_robots,
        'organization_jsonld': organization_jsonld,
        'sitemap_url': sitemap_url,
    }


def date_timer(request):
    date = datetime.now().strftime(" %Y ")
    date_time = datetime.now().strftime(" %B %d, %Y at %I:%M%p ")
    return {
        "date": date,
        "date_time": date_time
    }


# def contacts(request):
#     website = 'uonalumni.or.ke'
#     email = 'alumni@uonbi.ac.ke'
#     landline = '020 491 6713'
#     mobile = '0724 820 908'
#     address = 'KOLOBOT DRIVE, OFF STATE HOUSE RD, OFF ABORETUM DRIVE.'
#     postal = 'P. O. BOX 30490 - 00100, NAIROBI.'
#     mission = 'To safeguard the best interests of its members, to use the talents and resources of the Alumni and friends of the University in achieving international distinction in quality teaching, research and service.'
#     vision = 'To be a leader in promoting active, visible leadership in the community and to foster interaction between alumni and students of the University of Nairobi and the industry.'
#     name_title = 'University of Nairobi Alumni Association'

#     return {
#         "name_title": name_title,
#         "website": website,
#         "email": email,
#         "landline": landline,
#         "mobile": mobile,
#         "address": address,
#         "postal": postal,
#         "mission": mission,
#         "vision": vision,
#     }

def contacts(request):
    from django.conf import settings
    from django.contrib import admin as default_admin
    from django.urls import reverse

    from apps.home.membership_admin_site import membership_admin_site
    from apps.qr_manager.qr_admin_site import qr_admin_site

    # Explicit urlconf="main.urls" on every reverse() below: this context
    # processor runs on every subdomain, and without pinning it reverse()
    # would use whatever urlconf is active for the CURRENT request (e.g.
    # apps.staff.site_urls on the staff subdomain, which has no 'home'
    # namespace) instead of always resolving against the urlconf that
    # actually defines these routes. Same reasoning as AlumniProfile's
    # get_absolute_url() (apps/home/models.py).
    def home_url(name, **kwargs):
        return reverse(f"home:{name}", kwargs=kwargs or None, urlconf="main.urls")

    if settings.DEBUG:
        base = 'http://lvh.me:8000'
        staff_base = 'http://staff.lvh.me:8000'
        students_base = 'http://students.lvh.me:8000'
    else:
        base = 'https://uonalumni.or.ke'
        staff_base = 'https://staff.uonalumni.or.ke'
        students_base = 'https://students.uonalumni.or.ke'

    # Only ever computed for an authenticated user, and each entry only
    # appears if that admin site's OWN has_permission() says yes -- so
    # the navbar always matches what a user can actually get into,
    # without duplicating each site's permission logic in the template.
    admin_links = []
    # UoN Alumni Scholarships: its own submenu inside the Admin dropdown
    # (2026-08-14), not flat entries alongside Django Admin/Membership
    # Admin/etc. -- both views are gated by the same
    # StaffOrSuperuserRequiredMixin (apps/user/mixins.py) as Membership
    # Analytics above, no separate admin site to defer permission to,
    # so checked directly here exactly like that one already is.
    scholarship_admin_links = []
    if request.user.is_authenticated:
        if default_admin.site.has_permission(request):
            admin_links.append({"label": "Django Admin", "url": f"{base}/2005/"})
        if membership_admin_site.has_permission(request):
            admin_links.append({"label": "Membership Admin", "url": f"{base}/membership-admin/"})
        if qr_admin_site.has_permission(request):
            admin_links.append({"label": "QR Admin", "url": f"{staff_base}/qr-admin/"})
        # Same is_staff/is_superuser check as StaffOrSuperuserRequiredMixin
        # (apps/user/mixins.py), which is what actually gates the view --
        # not a real "admin site" with its own has_permission(), just a
        # plain view, so checked directly here instead.
        if request.user.is_staff or request.user.is_superuser:
            admin_links.append({"label": "Membership Analytics", "url": f"{base}{home_url('membership_analytics')}"})
            # Hardcoded paths, not reverse(urlconf="main.urls"), same reason
            # as QR Admin above -- apps.student.urls (the 'student'
            # namespace) is only ever mounted via the students-subdomain
            # middleware (SUBDOMAIN_URLCONFS), never included into
            # main.urls, so a 'student:' reverse pinned to main.urls always
            # raises NoReverseMatch (confirmed live, 2026-08-19: crashed
            # this context processor -- which runs on every page -- for
            # every staff/superuser request site-wide).
            scholarship_admin_links = [
                {"label": "Evaluate Applicants", "url": f"{students_base}/evaluate/"},
                {"label": "Charts", "url": f"{students_base}/dashboard/"},
            ]

    website = ASSOCIATION_WEBSITE
    email = 'alumni@uonbi.ac.ke'
    landline = '020 491 6713'
    mobile = '0724 820 908'
    address = ASSOCIATION_ADDRESS
    postal = ASSOCIATION_POSTAL
    mission = 'To safeguard the best interests of its members, to use the talents and resources of the Alumni and friends of the University in achieving international distinction in quality teaching, research and service.'
    vision = 'To be a leader in promoting active, visible leadership in the community and to foster interaction between alumni and students of the University of Nairobi and the industry.'
    name_title = ASSOCIATION_NAME

    # url_membership_update: empty string (not a URL) unless the user has
    # actually paid at some point -- an active OR expired Membership, not
    # just a still-pending one from registering but never being confirmed.
    # Decided 2026-08-07: "Upgrade Membership" implies there's an existing
    # membership to upgrade/renew; someone who's never had a payment
    # confirmed should register first, not land on this form. The
    # navbar link only renders when this is non-empty (templates/snippets/
    # navbar.html); AlumniMembershipUpdateView.dispatch() enforces the
    # same rule server-side, so this isn't just UI-level hiding.
    if request.user.is_authenticated:
        alumni_profile = getattr(request.user, 'alumni_profile', None)
        if alumni_profile:
            url_my_profile = f"{base}{alumni_profile.get_absolute_url()}"
            has_paid_membership = Membership.objects.filter(user=request.user).exclude(
                status=Membership.Status.PENDING
            ).exists()
            url_membership_update = f"{base}{alumni_profile.get_membership_update_url()}" if has_paid_membership else ""
        else:
            url_my_profile = f"{base}{home_url('uon_alumni_register')}"
            url_membership_update = ""
    else:
        # Relative, like the Sign Out link below -- /accounts/ paths are
        # shared across every subdomain regardless of which urlconf is active.
        url_my_profile = "/accounts/google/login/"
        url_membership_update = ""

    return {
        "name_title": name_title,
        "website": website,
        "email": email,
        "landline": landline,
        "mobile": mobile,
        "address": address,
        "postal": postal,
        "mission": mission,
        "vision": vision,
        # Every home-app URL below goes through home_url() (reverse(), pinned
        # to main.urls) rather than a hardcoded string -- a renamed/moved
        # path in apps/home/urls.py updates these automatically instead of
        # silently going stale (2026-08-07; this is what caused the
        # url_membership_update 404 before it was fixed the same way).
        "url_home":        f"{base}/",
        "url_history":     f"{base}{home_url('uon_alumni_history')}",
        "url_exec":        f"{base}{home_url('uon_alumni_exec_committee')}",
        "url_secretariat": f"{base}{home_url('uon_alumni_secretariat')}",
        "url_chapters":    f"{base}{home_url('uon_alumni_chapter_list')}",
        "url_partners":    f"{base}{home_url('uon_alumni_partners')}",
        "url_mission_vision": f"{base}{home_url('uon_alumni_mission_vision')}",
        "url_walk":        f"{base}{home_url('uon_alumni_walk_list')}",
        "url_articles":    f"{base}{home_url('uon_alumni_article_list')}",
        "url_gallery":     f"{base}{home_url('uon_alumni_gallery')}",
        "url_register":    f"{base}{home_url('uon_alumni_register')}",
        "url_donate":      f"{base}{home_url('uon_alumni_donate')}",
        "url_scholarship": f"{base}{home_url('uon_alumni_scholarship')}",
        "url_in_memoriam": f"{base}{home_url('uon_alumni_in_memoriam')}",
        "url_contact":     f"{base}{home_url('uon_alumni_contact_us')}",
        "url_my_profile":  url_my_profile,
        "url_membership_update": url_membership_update,
        "url_downloads":   f"{base}{home_url('uon_alumni_downloads')}",
        "url_newsletters": f"{base}{home_url('uon_alumni_downloads')}?category=newsletter",
        "url_careers":     f"{base}{home_url('uon_alumni_careers')}",
        # Categories & Benefits is a real data-driven page now (2026-08-11,
        # MembershipCategoriesView) -- not routed through standing_page
        # like the rest below, which are still Article-content placeholders.
        "url_categories_benefits": f"{base}{home_url('membership_categories')}",
        # Standing pages -- one route (home:standing_page) behind all of
        # these, see apps/home/views.py's standing_page().
        "url_alumni_card":         f"{base}{home_url('standing_page', page_key='alumni-card')}",
        "url_corporates":          f"{base}{home_url('standing_page', page_key='corporates')}",
        "url_notable_alumni":      f"{base}{home_url('standing_page', page_key='notable-alumni')}",
        "url_agm":                 f"{base}{home_url('standing_page', page_key='agm')}",
        "url_consultancy_training": f"{base}{home_url('standing_page', page_key='consultancy-training')}",
        "url_terms":               f"{base}{home_url('standing_page', page_key='terms')}",
        "url_privacy":             f"{base}{home_url('standing_page', page_key='privacy')}",
        "url_cookies":             f"{base}{home_url('standing_page', page_key='cookies')}",
        "url_shop":                f"{base}{home_url('standing_page', page_key='shop')}",
        "admin_links": admin_links,
        "scholarship_admin_links": scholarship_admin_links,
    }
