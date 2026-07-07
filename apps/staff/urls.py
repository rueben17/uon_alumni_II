from django.urls import path
from .views import (
    EmployeeListView,
    EmployeeDetailView,
    CompleteProfileView,
    ProfileUpdateView,
    ProfileDeleteView,
    StaffLoginView,
    download_staff_qr_code,
    staff_logout,
    staff_dashboard,
    staff_detail_fallback,
)

app_name = 'staff'  # required: this is what creates the staff: namespace

urlpatterns = [
    # Legacy auth endpoints — deletion candidates for the cleanup commit
    path('login/', StaffLoginView.as_view(), name='staff_login'),
    path('logout/', staff_logout, name='staff_logout'),

    path('dashboard/', staff_dashboard, name='staff_dashboard'),

    # Staff directory (list)
    path('', EmployeeListView.as_view(), name='all_uon_staff'),

    # One-time onboarding (adapter's completeness gate lands here)
    path('complete-profile/<uuid:uuid>/', CompleteProfileView.as_view(), name='complete_profile'),

    # Opt-in profile editing — session identifies the owner, no UUID
    path('profile/edit/', ProfileUpdateView.as_view(), name='profile_update'),
    path('profile/delete/', ProfileDeleteView.as_view(), name='profile_delete'),

    # Stable UUID landing page (incomplete profiles, QR target)
    path('fallback/<uuid:uuid>/', staff_detail_fallback, name='staff_detail_fallback'),

    # Canonical detail — name must stay 'staff_detail' to match get_absolute_url()
    path('<slug:unit_slug>/<slug:name_slug>/<uuid:uuid>/', EmployeeDetailView.as_view(), name='staff_detail'),
    path("<slug:staff_slug>/<uuid:pk>/download-qr/", download_staff_qr_code, name="download_staff_qr_pdf"),
]