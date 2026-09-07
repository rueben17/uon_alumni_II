# apps/home/tests_membership_crm.py
"""
Secretariat Membership CRM (apps/home/crm_views.py, crm_forms.py,
crm_urls.py) -- access gating, list/search/filter, the HTMX partial
swap, the CRUD surface, and query efficiency over a growing register.

Self-contained: local fixture helpers rather than importing from
apps/home/tests.py, so this module has no coupling to that file's much
larger module-level setup.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.home.models import AlumniProfile, Membership, MembershipTier, Payment

User = get_user_model()
PUBLIC_HOST = "lvh.me"


def _make_user(email, **extra):
    return User.objects.create_user(email=email, **extra)


def _staff_user(email="staff@example.com"):
    return _make_user(email, is_staff=True)


def _annual_tier(name="Full Annual Member", fee=2000, months=12):
    return MembershipTier.objects.create(
        name=name, fee=fee, tier_type="annual", duration_months=months,
    )


def _alumni_member(email, tier, status=Membership.Status.PENDING):
    """One full row: User + AlumniProfile + Membership, the shape every
    CRM view joins against."""
    user = _make_user(email)
    AlumniProfile.objects.create(user=user)
    membership = Membership.objects.create(user=user, tier=tier, status=status)
    return user, membership


class MembershipCrmAccessTests(TestCase):
    """StaffOrSuperuserRequiredMixin's actual, verified behaviour (no
    raise_exception override anywhere on it): anonymous gets Django's
    default AccessMixin redirect-to-login, an authenticated non-staff
    user gets 403, staff/superuser gets through."""

    @classmethod
    def setUpTestData(cls):
        cls.tier = _annual_tier()
        cls.plain_user = _make_user("plain@example.com")
        cls.staff_user = _staff_user()

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_authenticated_non_staff_gets_403(self):
        self.client.force_login(self.plain_user)
        response = self.client.get(reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(response.status_code, 403)

    def test_staff_gets_200(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(response.status_code, 200)


class MembershipCrmListTests(TestCase):
    """Register list -- renders, and search/status/tier filters narrow
    get_queryset() correctly."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.annual = _annual_tier(name="Full Annual Member")
        cls.life = MembershipTier.objects.create(
            name="Gold Life Member", fee=100000, tier_type="life", duration_months=0,
        )
        cls.active_user, cls.active_membership = _alumni_member(
            "wanjiku@example.com", cls.annual, status=Membership.Status.ACTIVE,
        )
        cls.active_user.profile.given_name = "Wanjiku"
        cls.active_user.profile.family_name = "Kamau"
        cls.active_user.profile.save(update_fields=["given_name", "family_name"])

        cls.pending_user, cls.pending_membership = _alumni_member(
            "otieno@example.com", cls.life, status=Membership.Status.PENDING,
        )
        cls.pending_user.profile.given_name = "Otieno"
        cls.pending_user.profile.family_name = "Omondi"
        cls.pending_user.profile.save(update_fields=["given_name", "family_name"])

    def setUp(self):
        self.client.force_login(self.staff_user)

    def test_list_renders_all_members(self):
        response = self.client.get(reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wanjiku")
        self.assertContains(response, "Otieno")

    def test_search_narrows_by_name(self):
        response = self.client.get(
            reverse("membership_crm:list"), {"q": "Wanjiku"}, HTTP_HOST=PUBLIC_HOST,
        )
        self.assertContains(response, "Wanjiku")
        self.assertNotContains(response, "Otieno")

    def test_status_filter_narrows_results(self):
        response = self.client.get(
            reverse("membership_crm:list"),
            {"status": Membership.Status.ACTIVE},
            HTTP_HOST=PUBLIC_HOST,
        )
        self.assertContains(response, "Wanjiku")
        self.assertNotContains(response, "Otieno")

    def test_tier_type_filter_narrows_results(self):
        response = self.client.get(
            reverse("membership_crm:list"), {"tier_type": "life"}, HTTP_HOST=PUBLIC_HOST,
        )
        self.assertContains(response, "Otieno")
        self.assertNotContains(response, "Wanjiku")

    def test_an_invalid_status_is_silently_ignored_not_500(self):
        """_selected_status()/_selected_tier_type() validate against the
        real choices rather than filtering on whatever the query string
        says -- a tampered/stale value must not 500."""
        response = self.client.get(
            reverse("membership_crm:list"), {"status": "not-a-real-status"}, HTTP_HOST=PUBLIC_HOST,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wanjiku")
        self.assertContains(response, "Otieno")


class MembershipCrmHtmxTests(TestCase):
    """get_template_names() -- an HX-Request returns ONLY the table
    partial, a plain request returns the full page around it."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.tier = _annual_tier()
        _alumni_member("member@example.com", cls.tier)

    def setUp(self):
        self.client.force_login(self.staff_user)

    def test_plain_request_returns_the_full_page(self):
        response = self.client.get(reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST)
        self.assertContains(response, "Total memberships")  # stats block, full page only
        self.assertContains(response, 'id="crm-table-container"')

    def test_htmx_request_returns_only_the_table_partial(self):
        response = self.client.get(
            reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST, HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, 'id="crm-table-container"')
        self.assertNotContains(response, "Total memberships")  # stats block absent


class MembershipCrmCreateTests(TestCase):
    """MembershipCreateView + NewMemberForm -- a brand-new person and a
    PENDING membership, through services.assign_membership_tier()."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.tier = _annual_tier()

    def setUp(self):
        self.client.force_login(self.staff_user)

    def test_create_makes_a_pending_membership(self):
        response = self.client.post(reverse("membership_crm:create"), {
            "given_name": "Jane", "family_name": "Doe",
            "email": "jane.doe@example.com", "tier": self.tier.pk,
        }, HTTP_HOST=PUBLIC_HOST)

        self.assertRedirects(response, reverse("membership_crm:list"))
        user = User.objects.get(email="jane.doe@example.com")
        membership = Membership.objects.get(user=user)
        self.assertEqual(membership.status, Membership.Status.PENDING)
        self.assertEqual(membership.tier, self.tier)

    def test_an_existing_email_is_rejected(self):
        _make_user("dupe@example.com")

        response = self.client.post(reverse("membership_crm:create"), {
            "given_name": "Jane", "family_name": "Doe",
            "email": "dupe@example.com", "tier": self.tier.pk,
        }, HTTP_HOST=PUBLIC_HOST)

        self.assertEqual(response.status_code, 200)  # re-rendered with the form error
        self.assertContains(response, "already exists")
        self.assertEqual(Membership.objects.count(), 0)


class NewMemberFormConsentTests(TestCase):
    """DPA 2019 caveat from README_MEMBERSHIP_CRM.md: this bypasses the
    Google-OAuth onboarding path, so consent cannot be pre-granted --
    both opt-ins must stay False."""

    def test_sms_and_email_opt_in_stay_false(self):
        from apps.home.crm_forms import NewMemberForm

        tier = _annual_tier()
        form = NewMemberForm(data={
            "given_name": "Jane", "family_name": "Doe",
            "email": "consent@example.com", "tier": tier.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)

        user, _membership = form.save()

        self.assertFalse(user.profile.sms_opt_in)
        self.assertFalse(user.profile.email_opt_in)


class MembershipCrmRecordPaymentTests(TestCase):
    """RecordPaymentView -> Payment.mark_as_completed() ->
    services.confirm_payment() -- the one door that activates a
    membership, per docs/payment-confirmation-workflow.md."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.tier = _annual_tier(fee=2000)
        cls.user, cls.membership = _alumni_member("payer@example.com", cls.tier)

    def setUp(self):
        self.client.force_login(self.staff_user)

    def test_mark_completed_activates_and_stamps_a_membership_number(self):
        response = self.client.post(
            reverse("membership_crm:record_payment", args=[self.membership.pk]),
            {"amount": "2000", "payment_method": "mpesa", "mark_completed": "on"},
            HTTP_HOST=PUBLIC_HOST,
        )

        self.assertRedirects(response, reverse("membership_crm:list"))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.ACTIVE)
        self.assertTrue(self.membership.membership_number)

    def test_leaving_mark_completed_unchecked_records_without_activating(self):
        response = self.client.post(
            reverse("membership_crm:record_payment", args=[self.membership.pk]),
            {"amount": "2000", "payment_method": "mpesa"},  # mark_completed omitted
            HTTP_HOST=PUBLIC_HOST,
        )

        self.assertRedirects(response, reverse("membership_crm:list"))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.PENDING)
        payment = Payment.objects.get(membership=self.membership)
        self.assertEqual(payment.payment_status, "pending")

    def test_a_member_with_no_alumni_profile_is_refused(self):
        """RecordPaymentView's own guard -- a payment needs an
        AlumniProfile to attach to."""
        user = _make_user("noprofile@example.com")
        membership = Membership.objects.create(user=user, tier=self.tier)

        response = self.client.post(
            reverse("membership_crm:record_payment", args=[membership.pk]),
            {"amount": "2000", "payment_method": "mpesa", "mark_completed": "on"},
            HTTP_HOST=PUBLIC_HOST,
        )

        self.assertRedirects(response, reverse("membership_crm:list"))
        membership.refresh_from_db()
        self.assertEqual(membership.status, Membership.Status.PENDING)
        self.assertFalse(Payment.objects.filter(membership=membership).exists())


class MembershipCrmConfirmPaymentTests(TestCase):
    """ConfirmPaymentView -- the drawer's "Confirm" button beside an
    already-recorded pending payment."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.tier = _annual_tier(fee=2000)
        cls.user, cls.membership = _alumni_member("confirmme@example.com", cls.tier)
        cls.payment = Payment.objects.create(
            alumni=cls.user.alumni_profile, membership=cls.membership,
            membership_tier=cls.tier, amount=2000, payment_method="mpesa",
        )

    def setUp(self):
        self.client.force_login(self.staff_user)

    def test_confirming_a_pending_payment_activates_the_membership(self):
        response = self.client.post(
            reverse("membership_crm:confirm_payment", args=[self.payment.pk]),
            {"reference": "QGR1234"}, HTTP_HOST=PUBLIC_HOST,
        )

        self.assertRedirects(response, reverse("membership_crm:list"))
        self.membership.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.ACTIVE)
        self.assertEqual(self.payment.payment_status, "completed")

    def test_confirming_an_already_completed_payment_is_a_no_op(self):
        self.payment.mark_as_completed()
        self.membership.refresh_from_db()
        activated_at = self.membership.updated_at

        response = self.client.post(
            reverse("membership_crm:confirm_payment", args=[self.payment.pk]),
            {}, HTTP_HOST=PUBLIC_HOST,
        )

        self.assertRedirects(response, reverse("membership_crm:list"))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.updated_at, activated_at)  # untouched, not re-saved


class MembershipCrmEditTests(TestCase):
    """MembershipUpdateView + MembershipStaffForm -- direct correction of
    the row, not a member-facing request."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.tier = _annual_tier()
        cls.other_tier = _annual_tier(name="Corporate Membership", fee=12000)
        cls.user, cls.membership = _alumni_member("editme@example.com", cls.tier)

    def setUp(self):
        self.client.force_login(self.staff_user)

    def test_edit_saves_a_changed_tier(self):
        response = self.client.post(
            reverse("membership_crm:edit", args=[self.membership.pk]),
            {
                "tier": self.other_tier.pk,
                "status": Membership.Status.ACTIVE,
                "membership_number": "ANNUAL/2026/0001",
                "payment_frequency": Membership.PaymentFrequency.ONCE,
            },
            HTTP_HOST=PUBLIC_HOST,
        )

        self.assertRedirects(response, reverse("membership_crm:list"))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.tier, self.other_tier)
        self.assertEqual(self.membership.status, Membership.Status.ACTIVE)


class MembershipCrmCancelTests(TestCase):
    """MembershipCancelView -- soft-cancel (status=CANCELLED), mirroring
    AlumniProfileDeleteView; the row and its history survive."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.tier = _annual_tier()
        cls.user, cls.membership = _alumni_member(
            "cancelme@example.com", cls.tier, status=Membership.Status.ACTIVE,
        )

    def setUp(self):
        self.client.force_login(self.staff_user)

    def test_get_shows_the_confirmation_page(self):
        response = self.client.get(
            reverse("membership_crm:cancel", args=[self.membership.pk]), HTTP_HOST=PUBLIC_HOST,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cancel this membership")

    def test_post_cancels_without_deleting_the_row(self):
        response = self.client.post(
            reverse("membership_crm:cancel", args=[self.membership.pk]), HTTP_HOST=PUBLIC_HOST,
        )

        self.assertRedirects(response, reverse("membership_crm:list"))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.CANCELLED)
        self.assertTrue(Membership.objects.filter(pk=self.membership.pk).exists())


class MembershipCrmQueryEfficiencyTests(TestCase):
    """No N+1: the list and drawer views' query counts must stay
    constant as the data they read grows, not scale per row."""

    @classmethod
    def setUpTestData(cls):
        cls.staff_user = _staff_user()
        cls.tier = _annual_tier()

    def setUp(self):
        self.client.force_login(self.staff_user)

    def _make_members(self, count, offset=0):
        for i in range(offset, offset + count):
            _alumni_member(f"query{i}@example.com", self.tier)

    def test_list_view_query_count_is_constant_as_membership_rows_grow(self):
        self._make_members(3)
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST)

        self._make_members(20, offset=3)  # 23 total, still one page (paginate_by=20 -> page 1 has 20)
        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse("membership_crm:list"), HTTP_HOST=PUBLIC_HOST)

        self.assertEqual(
            len(small.captured_queries), len(large.captured_queries),
            "Query count grew with row count -- select_related is missing somewhere.\n"
            f"small ({len(small.captured_queries)}): "
            + "\n".join(q["sql"][:120] for q in small.captured_queries)
            + f"\nlarge ({len(large.captured_queries)}): "
            + "\n".join(q["sql"][:120] for q in large.captured_queries),
        )

    def test_drawer_view_query_count_is_constant_as_payments_grow(self):
        user, membership = _alumni_member("drawer@example.com", self.tier)
        alumni = user.alumni_profile

        Payment.objects.create(
            alumni=alumni, membership=membership, membership_tier=self.tier,
            amount=2000, payment_method="mpesa",
        )
        with CaptureQueriesContext(connection) as small:
            self.client.get(
                reverse("membership_crm:drawer", args=[membership.pk]), HTTP_HOST=PUBLIC_HOST,
            )

        for _ in range(10):
            Payment.objects.create(
                alumni=alumni, membership=membership, membership_tier=self.tier,
                amount=200, payment_method="mpesa",
            )
        with CaptureQueriesContext(connection) as large:
            self.client.get(
                reverse("membership_crm:drawer", args=[membership.pk]), HTTP_HOST=PUBLIC_HOST,
            )

        self.assertEqual(
            len(small.captured_queries), len(large.captured_queries),
            "Drawer query count grew with payment count -- select_related is missing somewhere.",
        )
