from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path('', include('apps.staff.urls')),
]

# Dev-only: serve media on this subdomain too. main.urls' static()
# patterns don't apply here because the middleware swaps the urlconf.
# In production Nginx serves media (or Cloudinary does), so this
# helper is a no-op there — static() returns [] when DEBUG is False.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)