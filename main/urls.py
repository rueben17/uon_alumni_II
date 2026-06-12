"""
URL configuration for main project.

Subdomains are routed via middleware to different URLconf modules:
- staff.uonalumni.or.ke → apps.staff.urls
- students.uonalumni.or.ke → apps.student.urls
- www.uonalumni.or.ke / uonalumni.or.ke / localhost → apps.home.urls

This file serves as the default/fallback URLconf.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from apps.home.sitemaps import UonAlumniStaticSitemap 


sitemaps = {'static': UonAlumniStaticSitemap}

urlpatterns = [
    # Admin and sitemaps (accessible from any subdomain)
        # Base routes with path prefixes for backward compatibility
    # (These will be overridden by middleware-based subdomain routing)
    
    path("2005/", admin.site.urls),
    path("", include('apps.home.urls', namespace="home")), 
    path("", include('apps.staff.urls', namespace="staff")), 
    path("", include('apps.student.urls', namespace="student")), 
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += [
        # path("admin/", admin.site.urls),
        # path('admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
        # path('__debug__/', include(debug_toolbar.urls)),
    ]