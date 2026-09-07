# Secretariat Membership CRM — wiring & map

A staff-facing console for managing alumni memberships without the Django
admin, built against the existing models (no new tables, no migration).
Gated by `apps.user.mixins.StaffOrSuperuserRequiredMixin` — the same gate
as `MembershipAnalyticsView`.

## Files (drop-in)

| File | Purpose |
|---|---|
| `apps/home/crm_forms.py` | `MembershipStaffForm` (edit a row), `RecordPaymentForm`, `NewMemberForm` (create person + pending membership) |
| `apps/home/crm_views.py` | List, drawer (detail), create, edit, cancel, record-payment, confirm-payment — all staff-gated |
| `apps/home/crm_urls.py` | URLconf, namespace `membership_crm` |
| `templates/home/crm/membership_list.html` | Register: stats, HTMX search/filter, slide-over drawer |
| `templates/home/crm/_membership_table.html` | HTMX table partial (search/filter/pagination swap this) |
| `templates/home/crm/_member_drawer.html` | Detail drawer: identity, membership, payments, record/confirm payment |
| `templates/home/crm/membership_form.html` | Add member / edit membership |
| `templates/home/crm/membership_confirm_delete.html` | Cancel confirmation |

## The one wiring change

Add to `main/urls.py` `urlpatterns` (next to the other includes):

```python
path("membership-crm/", include("apps.home.crm_urls")),
```

That's the whole integration — the CRM then lives at
`/membership-crm/` on the main site (staff/superuser only), alongside
`/membership-admin/` and `uon-alumni-membership-analytics/`.
Reverse anywhere with `{% url 'membership_crm:list' %}`.

(If you'd rather it sit on the `staff.` subdomain, include the same
module from `apps/staff/urls.py` instead.)

## Wireframe → MVT map

| Wireframe element | Django |
|---|---|
| Members table + search + status/tier filter | `MembershipListView` (ListView) + `_membership_table.html`; filters are `?q=`, `?status=`, `?tier_type=` read in `get_queryset` |
| Live search / filter (no reload) | HTMX `hx-get` form → `get_template_names()` returns the table partial on `HX-Request` (your `EmployeeListView` pattern) |
| Row click → detail drawer | `MemberDrawerView` returns `_member_drawer.html`; row `hx-get` + `openCrmDrawer()` |
| Stat tiles | `stats` dict in `get_context_data` (`Sum('subscription_amount')`, status counts) |
| Add member | `MembershipCreateView` + `NewMemberForm` → `services.assign_membership_tier()` (pending) |
| Edit membership | `MembershipUpdateView` + `MembershipStaffForm` (tier, status, dates, number, issued flags) |
| Confirm / record payment | `RecordPaymentView` / `ConfirmPaymentView` → `Payment.mark_as_completed()` → `services.confirm_payment()` **activates** the membership |
| Delete member | `MembershipCancelView` → soft-cancel (`status=CANCELLED`), mirroring `AlumniProfileDeleteView` |

## Data notes

- **A "member" = a `Membership` row**, joined to `user.profile` (name/
  email/phone), `user.alumni_profile` (faculty, reg no, graduation), and
  `Payment`s (via `alumni.payments`).
- **Tiers/fees are DB rows** (`MembershipTier`, seeded by
  `seed_membership_tiers`), so the console never hardcodes them — the
  filter and forms read live tiers. This is why the wrong fees in the
  mock don't matter here.
- **Create caveat (DPA 2019):** `NewMemberForm` bypasses the Google-OAuth
  onboarding path, so it does **not** collect SMS/email consent —
  `sms_opt_in`/`email_opt_in` stay `False` (consent can't be pre-granted).
  The account gets an unusable password; the member links Google / sets a
  password on first login. For an existing person, edit their membership
  instead of creating a duplicate.
- **Brand blue is `#38b6ff`** (the same value already in your
  `TailwindStyledFormMixin` checkbox class); a deeper `#0E4E80` is used
  for headings/contrast.

## Try it

```bash
python manage.py runserver
# visit /membership-crm/  (logged in as a staff/superuser)
```

No migration needed. If you want the "Add member" button to open the
drawer as a slide-over form instead of a separate page, say so — it's a
small HTMX swap on top of what's here.
