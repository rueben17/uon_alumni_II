from django.urls import path

from apps.qr_manager.views import verify_scan

app_name = 'qr'

urlpatterns = [
    # Mounted under qr/ in apps/staff/site_urls.py, so the full path
    # is /qr/<uuid>/ on the staff subdomain — exactly what
    # services.build_scan_url() encodes into every badge.
    path('<uuid:qr_id>/', verify_scan, name='verify'),
]