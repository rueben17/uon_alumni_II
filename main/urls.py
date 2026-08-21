"""
URL configuration for main project.

Subdomains are routed via middleware to different URLconf modules:
- staff.uonalumni.or.ke → apps.staff.urls
- students.uonalumni.or.ke → apps.student.urls
- www.uonalumni.or.ke / uonalumni.or.ke / localhost → apps.home.urls

This file serves as the default/fallback URLconf.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from django.shortcuts import redirect
from django.views.generic import TemplateView
from apps.home.sitemaps import (
    UonAlumniStaticSitemap, StandingPageSitemap, ArticleSitemap, EventSitemap, ChapterSitemap,
)
from apps.home.membership_admin_site import membership_admin_site


sitemaps = {
    'static': UonAlumniStaticSitemap,
    'standing_pages': StandingPageSitemap,
    'articles': ArticleSitemap,
    'events': EventSitemap,
    'chapters': ChapterSitemap,
}


def _redirect_to_subdomain(request, subdomain, rest=''):
    # apps.staff.urls and apps.student.urls used to also be mounted here
    # directly (/staff/..., /students/...), duplicating every page also
    # served on staff.<domain>/students.<domain> -- confirmed via the SEO
    # audit (2026-08-18) that this defeated the staff subdomain's
    # noindex,nofollow rule for that duplicate copy. Redirecting instead
    # of just removing the mount keeps any old bookmarked/shared
    # /staff/... or /students/... link working, permanently pointed at
    # the one real URL for that page.
    scheme = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    port = ':' + host.split(':')[1] if ':' in host else ''
    target = f'{scheme}://{subdomain}.{settings.SUBDOMAIN_DOMAIN}{port}/{rest}'
    if request.META.get('QUERY_STRING'):
        target += f'?{request.META["QUERY_STRING"]}'
    return redirect(target, permanent=True)


def redirect_to_staff_subdomain(request, rest=''):
    return _redirect_to_subdomain(request, 'staff', rest)


def redirect_to_students_subdomain(request, rest=''):
    return _redirect_to_subdomain(request, 'students', rest)


urlpatterns = [
    # Admin and sitemaps (accessible from any subdomain)
        # Base routes with path prefixes for backward compatibility
    # (These will be overridden by middleware-based subdomain routing)

    path("2005/", admin.site.urls),
    # UoNAA Secretariat's scoped-down admin -- payment confirmation,
    # membership tier/number assignment, and #Issued Items tracking.
    path("membership-admin/", membership_admin_site.urls),
    # qr-admin/ lives on the staff subdomain instead (apps/staff/site_urls.py)
    # -- supervisors are staff members, that's where they already work.
    # qr/ itself IS mounted here too (2026-08-21, alongside its existing
    # staff-subdomain mount) -- an alumnus's badge now encodes
    # settings.QR_SCAN_ORIGINS['alumni'] (this www/bare domain), so this
    # is where that URL actually needs to resolve. verify_scan() itself
    # is holder-type-agnostic either way; only the encoded origin differs.
    path('qr/', include('apps.qr_manager.urls')),
    path('accounts/', include('allauth.urls')),
    path("", include('apps.home.urls', namespace="home")),
    # 2026-08-18 SEO audit: these used to `include()` apps.staff.urls /
    # apps.student.urls directly, duplicating every page also served on
    # the staff./students. subdomains -- see _redirect_to_subdomain()'s
    # own comment above for why that's a real problem, not just tidiness.
    re_path(r'^staff/(?P<rest>.*)$', redirect_to_staff_subdomain, name='staff_subdomain_redirect'),
    re_path(r'^students/(?P<rest>.*)$', redirect_to_students_subdomain, name='students_subdomain_redirect'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name='robots_txt'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += [
        # path("admin/", admin.site.urls),
        # path('admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
        # path('__debug__/', include(debug_toolbar.urls)),
    ]