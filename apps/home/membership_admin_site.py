from django.contrib import admin


class MembershipAdminSite(admin.AdminSite):
    """
    Separate admin for the UoNAA Secretariat: payment confirmation,
    membership number/tier assignment, renewal, upgrading, and the
    membership-card/certificate/badge "issued" tracking fields -- kept
    off the main /2005/ admin so Secretariat staff aren't handed Users,
    Groups, or anything unrelated to membership administration.
    Mirrors apps/qr_manager/qr_admin_site.py's pattern.
    """
    site_header = "UoNAA Membership Admin"
    site_title = "UoNAA Membership Admin"
    index_title = "Membership Administration"

    def has_permission(self, request):
        user = request.user
        return user.is_active and user.is_staff


membership_admin_site = MembershipAdminSite(name="membership_admin")
