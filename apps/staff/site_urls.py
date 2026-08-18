from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import TemplateView

from apps.qr_manager.qr_admin_site import qr_admin_site

urlpatterns = [
    # 2026-08-18 SEO audit: staff. is noindex,nofollow site-wide, and
    # robots.txt itself must be served per-host, at this subdomain's own
    # root -- templates/robots.txt branches on request.subdomain.
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name='robots_txt'),
    path('', include('apps.staff.urls')),
    # Every badge encodes <QR_SCAN_ORIGIN>/qr/<uuid>/?t=<token> (see
    # QRCode.generate_qr) -- QR_SCAN_ORIGIN is this subdomain, so the
    # scan endpoint must be mounted here.
    path('qr/', include('apps.qr_manager.urls')),
    # Supervisors are staff members, so their dedicated admin lives on
    # this subdomain too (unlike the main /2005/ admin, which is
    # root-domain only per main/urls.py).
    path('qr-admin/', qr_admin_site.urls),
]

# Dev-only: serve media on this subdomain too. main.urls' static()
# patterns don't apply here because the middleware swaps the urlconf.
# In production Nginx serves media (or Cloudinary does), so this
# helper is a no-op there — static() returns [] when DEBUG is False.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)