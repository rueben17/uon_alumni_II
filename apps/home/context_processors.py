from apps.home.models import *
from datetime import*
from django.utils import timezone as tz
from django.utils.timezone import now
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404


def images(request):
    banner_images = Banner.objects.all()
    
    return {
        "banner_images": banner_images,
        
    }

# def ads(request):
#     ads = Ad.objects.all()

#     return {
#         "ads": ads
#     }



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
    else:
        base = 'https://uonalumni.or.ke'
        staff_base = 'https://staff.uonalumni.or.ke'

    # Only ever computed for an authenticated user, and each entry only
    # appears if that admin site's OWN has_permission() says yes -- so
    # the navbar always matches what a user can actually get into,
    # without duplicating each site's permission logic in the template.
    admin_links = []
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

    website = 'uonalumni.or.ke'
    email = 'alumni@uonbi.ac.ke'
    landline = '020 491 6713'
    mobile = '0724 820 908'
    address = 'KOLOBOT DRIVE, OFF STATE HOUSE RD, OFF ABORETUM DRIVE.'
    postal = 'P. O. BOX 30490 - 00100, NAIROBI.'
    mission = 'To safeguard the best interests of its members, to use the talents and resources of the Alumni and friends of the University in achieving international distinction in quality teaching, research and service.'
    vision = 'To be a leader in promoting active, visible leadership in the community and to foster interaction between alumni and students of the University of Nairobi and the industry.'
    name_title = 'University of Nairobi Alumni Association'

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
        # Standing pages -- one route (home:standing_page) behind all of
        # these, see apps/home/views.py's standing_page().
        "url_categories_benefits": f"{base}{home_url('standing_page', page_key='categories-benefits')}",
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
    }
