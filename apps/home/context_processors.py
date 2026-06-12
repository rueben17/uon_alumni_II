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

    if settings.DEBUG:
        base = 'http://lvh.me:8000'
    else:
        base = 'https://uonalumni.or.ke'

    website = 'uonalumni.or.ke'
    email = 'alumni@uonbi.ac.ke'
    landline = '020 491 6713'
    mobile = '0724 820 908'
    address = 'KOLOBOT DRIVE, OFF STATE HOUSE RD, OFF ABORETUM DRIVE.'
    postal = 'P. O. BOX 30490 - 00100, NAIROBI.'
    mission = 'To safeguard the best interests of its members, to use the talents and resources of the Alumni and friends of the University in achieving international distinction in quality teaching, research and service.'
    vision = 'To be a leader in promoting active, visible leadership in the community and to foster interaction between alumni and students of the University of Nairobi and the industry.'
    name_title = 'University of Nairobi Alumni Association'

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
        "url_home":        f"{base}/",
        "url_history":     f"{base}/history/",
        "url_exec":        f"{base}/executive-committee/",
        "url_gallery":     f"{base}/uon-alumni-gallery/",
        "url_register":    f"{base}/uon-alumni-register/",
        "url_donate":      f"{base}/uon-alumni-donate/",
        "url_scholarship": f"{base}/uon-alumni-scholarship/",
        "url_in_memoriam": f"{base}/uon-alumni-in-memoriam/",
        "url_contact":     f"{base}/uon-alumni-contact-us/",
    }
