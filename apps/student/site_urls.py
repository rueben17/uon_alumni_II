from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    # Mirrors apps/staff/site_urls.py: the subdomain's root URLconf
    # include()s the app's own urls module, and that include is what
    # registers its app_name as a namespace. SUBDOMAIN_URLCONFS used to
    # point straight at apps.student.urls (until 2026-09-01), making it a
    # ROOT urlconf -- and a root urlconf's module-level app_name
    # registers nothing, so every 'student:' reverse raised
    # NoReverseMatch. See qa_500_report.md finding 8.
    #
    # robots.txt is deliberately NOT repeated here, unlike staff's:
    # apps/student/urls.py already carries its own route for it, and the
    # include serves it at the same /robots.txt path. Duplicating it
    # would shadow the namespaced route with an identical one.
    path('', include('apps.student.urls')),
]

# Dev-only: serve media on this subdomain too, same as staff's -- the
# middleware swaps the urlconf, so main.urls' static() patterns do not
# apply here. In production Nginx serves media (or Cloudinary does), so
# this is a no-op there: static() returns [] when DEBUG is False.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
