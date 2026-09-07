# apps/home/crm_urls.py
"""
URLconf for the Secretariat Membership CRM. Mounted from main/urls.py:

    path("membership-crm/", include("apps.home.crm_urls")),

Its own namespace ("membership_crm:") keeps it cleanly separable from the
public home: routes -- templates reverse e.g. {% url 'membership_crm:list' %}.
Membership.pk is a UUID, so detail/edit/cancel use <uuid:pk>; Payment.pk is
an integer, so confirm uses <int:payment_id>.
"""
from django.urls import path

from apps.home import crm_views

app_name = "membership_crm"

urlpatterns = [
    path("", crm_views.MembershipListView.as_view(), name="list"),
    path("new/", crm_views.MembershipCreateView.as_view(), name="create"),
    path("<uuid:pk>/", crm_views.MemberDrawerView.as_view(), name="drawer"),
    path("<uuid:pk>/edit/", crm_views.MembershipUpdateView.as_view(), name="edit"),
    path("<uuid:pk>/cancel/", crm_views.MembershipCancelView.as_view(), name="cancel"),
    path("<uuid:pk>/record-payment/", crm_views.RecordPaymentView.as_view(), name="record_payment"),
    path("payment/<int:payment_id>/confirm/", crm_views.ConfirmPaymentView.as_view(), name="confirm_payment"),
]
