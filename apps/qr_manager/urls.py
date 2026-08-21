from django.urls import path

from apps.qr_manager.views import verify_scan

app_name = 'qr'

urlpatterns = [
    # Mounted under qr/ in BOTH apps/staff/site_urls.py (staff subdomain)
    # and main/urls.py (www/bare domain, 2026-08-21) -- QRCode.scan_url
    # picks settings.QR_SCAN_ORIGINS['staff'] or ['alumni'] by holder
    # type, so this same view needs to resolve identically on either
    # origin depending on whose badge got scanned.
    path('<uuid:qr_id>/', verify_scan, name='verify'),
]