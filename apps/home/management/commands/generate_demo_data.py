"""
Generate synthetic demo-scale AlumniProfile/Membership/Payment data for
local load-testing and dashboard demos. NOT real data -- every generated
User lives under the @example.test email domain so a later cleanup pass
can find and delete this batch without touching real accounts.

Local sqlite only by construction (refuses to run against any other DB
engine): this is disposable synthetic volume, and Neon is what the live
site actually serves from -- see docs/todo.md's still-open VPS/Neon
hosting note. Never point this at a shared database.

Timeline rules (Association decisions 2026-08-08):
  - AlumniProfile.graduation_year spans the University's own history,
    1970-2026, weighted toward more recent decades (enrollment grew over
    time -- a flat distribution across 56 years would be unrealistic).
  - Membership.started_on can only fall from 2005 onward -- UoNAA itself
    didn't exist before then -- and never before the person's own
    graduation year.
  - Non-lifetime tiers (Annual/Student/Honorary/Corporate) renew on a
    12-month cycle -- a member active for N years gets N Membership rows,
    not one. A single lump-sum row per person understated how many real
    payment events a multi-year annual member represents, and inflated
    the apparent per-row scale of "revenue" relative to what a real
    once-a-year fee produces. Each person's renewal dates are staggered
    (random per-person anchor day), not synchronized to a single date.

Uses factory_boy's `.build()` strategy only (no DB hits per instance);
this command does the actual bulk_create()ing in batches. Every model
here has a client-side UUID pk (`default=uuid.uuid4`), so FKs can be
wired up in memory before anything is written -- no dependency on the
DB handing back generated pks.
"""
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.home.factories import (
    AlumniProfileFactory,
    MembershipFactory,
    PaymentFactory,
    UserFactory,
    UserProfileFactory,
)
from apps.home.models import AlumniProfile, Faculty, Membership, MembershipTier, Payment, Qualification
from apps.user.models import User, UserProfile

UONAA_FOUNDED = date(2005, 1, 1)
TODAY = date.today()

# (tier name -> relative weight) -- ONLY the tiers an ordinary alumnus
# self-selects, pyramid-shaped: cheap/common dominates, and it drops off
# sharply as price rises. Full Annual + Student together are the vast
# majority; Life tiers are a real minority even at the cheap (Bronze) end.
TIER_WEIGHTS = {
    "Full Annual Member": 70,
    "Student Annual Membership": 10,
    "Bronze Life Member": 12,
    "Silver Life Member": 6,
    "Gold Life Member": 2,
}

# Tiers that do NOT scale with alumni headcount -- organizations
# (Corporate), conferred distinctions (Honorary), and ultra-premium
# one-time tiers (Platinum/Diamond) are each a small, roughly fixed pool
# in any real association, not a percentage of the member base. Weighting
# them at 5% of --count each (2026-08-10) put ~2,500 people paying KES
# 500,000/250,000 one-time into the dataset -- 63% of total revenue from
# 10% of members, which no real alumni association looks like. Counts are
# real-world-plausible absolute numbers, independent of --count.
FIXED_POOL_TIERS = {
    "Corporate Membership": 120,
    "Honorary Member": 60,
    "Diamond Life Membership": 80,
    "Platinum Life Membership": 40,
}

STATUS_WEIGHTS = {
    Membership.Status.ACTIVE: 55,
    Membership.Status.EXPIRED: 30,
    Membership.Status.PENDING: 10,
    Membership.Status.CANCELLED: 5,
}

# How many consecutive annual renewals a non-lifetime member has behind
# them -- most members are recent, a long tail renews for years. Average
# ~2.4 years, capped by however long they've actually been eligible to
# join (see max_years in the loop).
RENEWAL_YEARS_WEIGHTS = {1: 40, 2: 24, 3: 14, 4: 9, 5: 6, 6: 4, 7: 2, 8: 1}

# Installment plans only make sense once real money is involved -- Annual/
# Student are cheap enough to pay outright. Only ever applied to a
# person's CURRENT (most recent) row -- past renewal years are settled,
# fully-paid history.
INSTALLMENT_ELIGIBLE_TYPES = {"life", "corporate"}
INSTALLMENT_TAKE_RATE = 0.35  # share of eligible current-row members actually paying in installments

AGE_AT_GRADUATION_BY_LEVEL = {
    "phd": (28, 40),
    "fellowship": (32, 48),
    "masters": (24, 32),
    "pgd": (23, 30),
    "bachelors": (21, 26),
    "diploma": (19, 24),
    None: (21, 27),
}


def _random_date(start, end):
    if end <= start:
        return start
    return start + timedelta(days=random.randint(0, (end - start).days))


def _aware(d):
    """Payment.payment_date/completion_date are DateTimeField; passing bare
    date objects triggers naive-datetime warnings under USE_TZ=True."""
    return timezone.make_aware(datetime.combine(d, time.min))


def _pick_payment_method(tier):
    methods, weights = ["credit_card", "bank_transfer"], [30, 40]
    if tier.allows_mpesa:
        methods.append("mpesa")
        weights.append(50)
    return random.choices(methods, weights=weights, k=1)[0]


class Command(BaseCommand):
    help = "Generate synthetic demo-scale AlumniProfile/Membership/Payment data (local sqlite only)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=150_000, help="Number of individual alumni to generate.")
        parser.add_argument("--batch-size", type=int, default=500, help="bulk_create batch size per model.")

    def handle(self, *args, **options):
        engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite3" not in engine:
            raise CommandError(
                f"Refusing to run against non-sqlite engine ({engine}). This command is for "
                "local demo data only -- see docs/todo.md's VPS/Neon hosting note. Unset "
                "USE_NEON_LOCALLY and re-run."
            )

        count = options["count"]
        batch_size = options["batch_size"]

        faculties = list(Faculty.objects.all())
        if not faculties:
            raise CommandError("No Faculty rows found -- run seed_university_structure first.")
        quals_by_faculty = defaultdict(list)
        for q in Qualification.objects.all():
            quals_by_faculty[q.faculty_id].append(q)

        all_needed_names = set(TIER_WEIGHTS) | set(FIXED_POOL_TIERS)
        tiers_by_name = {t.name: t for t in MembershipTier.objects.filter(name__in=all_needed_names)}
        missing = all_needed_names - set(tiers_by_name)
        if missing:
            raise CommandError(f"Missing seeded tiers: {missing} -- run seed_membership_tiers first.")
        tier_choices = [tiers_by_name[name] for name in TIER_WEIGHTS]
        tier_weights = [TIER_WEIGHTS[t.name] for t in tier_choices]

        status_choices = list(STATUS_WEIGHTS.keys())
        status_weights = list(STATUS_WEIGHTS.values())
        renewal_year_choices = list(RENEWAL_YEARS_WEIGHTS.keys())
        renewal_year_weights = list(RENEWAL_YEARS_WEIGHTS.values())

        year_counters = {}

        def next_membership_number(year):
            if year not in year_counters:
                year_counters[year] = Membership.objects.filter(membership_number__endswith=f"/{year}").count()
            year_counters[year] += 1
            return f"UoNAA/{year_counters[year]:06d}/{year}"

        self.stdout.write(f"Generating {count:,} synthetic alumni into {settings.DATABASES['default']['NAME']}...")

        users, profiles, alumni_rows, membership_rows, payment_rows = [], [], [], [], []
        totals = {"users": 0, "memberships": 0, "payments": 0}

        def flush():
            with transaction.atomic():
                User.objects.bulk_create(users, batch_size=batch_size)
                UserProfile.objects.bulk_create(profiles, batch_size=batch_size)
                AlumniProfile.objects.bulk_create(alumni_rows, batch_size=batch_size)
                Membership.objects.bulk_create(membership_rows, batch_size=batch_size)
                Payment.objects.bulk_create(payment_rows, batch_size=batch_size)
            totals["users"] += len(users)
            totals["memberships"] += len(membership_rows)
            totals["payments"] += len(payment_rows)
            users.clear()
            profiles.clear()
            alumni_rows.clear()
            membership_rows.clear()
            payment_rows.clear()

        def build_row(user, alumni, tier, status, started_on, membership_number, is_installment):
            """One Membership row + its matching Payment(s). Shared by the
            lifetime (single-row) path and each year of the annual-renewal
            path below. `is_installment` is decided by the CALLER, once,
            before `status` is finalized (2026-08-10 correction) -- this
            used to roll its own dice internally, independently of
            `status`, which could and did produce a fully-paid lump-sum
            Life membership marked EXPIRED. The real app has no code path
            that can ever produce that: a lump-sum Life row has no
            expires_on and nothing that could lapse it -- only an
            installment plan that stalled before paying off can
            legitimately be EXPIRED."""
            is_lifetime = tier.is_lifetime()
            expires_on = None if is_lifetime else tier.get_expiry_date(started_on)
            frequency = (
                random.choice([Membership.PaymentFrequency.MONTHLY, Membership.PaymentFrequency.QUARTERLY,
                                Membership.PaymentFrequency.ANNUALLY])
                if is_installment else Membership.PaymentFrequency.ONCE
            )

            if not is_installment:
                amount_paid = tier.fee
                next_installment_due = None
            else:
                fraction = random.uniform(0.2, 1.0) if status == Membership.Status.ACTIVE else random.uniform(0.1, 0.6)
                amount_paid = (tier.fee * Decimal(str(round(fraction, 4)))).quantize(Decimal("0.01"))
                freq_days = Membership.INSTALLMENT_FREQUENCY_DAYS[frequency]
                if status == Membership.Status.ACTIVE and amount_paid < tier.fee:
                    due = started_on + timedelta(days=freq_days * random.randint(1, 6))
                    next_installment_due = min(due, TODAY + timedelta(days=180))
                else:
                    next_installment_due = None

            membership = MembershipFactory.build(
                user=user, tier=tier, status=status, started_on=started_on, expires_on=expires_on,
                is_lifetime=is_lifetime, membership_number=membership_number, payment_frequency=frequency,
                subscription_amount=tier.fee, amount_paid=amount_paid, next_installment_due=next_installment_due,
                legacy_signed=False,
            )
            membership_rows.append(membership)

            if not is_installment:
                payment_rows.append(PaymentFactory.build(
                    alumni=alumni, membership=membership, membership_tier=tier,
                    amount=amount_paid, payment_method=_pick_payment_method(tier),
                    payment_status="completed", payment_date=_aware(started_on), completion_date=_aware(started_on),
                ))
            elif amount_paid > 0:
                k = random.randint(2, 5)
                per = (amount_paid / k).quantize(Decimal("0.01"))
                installments = [per] * (k - 1)
                installments.append(amount_paid - per * (k - 1))
                freq_days = Membership.INSTALLMENT_FREQUENCY_DAYS[frequency]
                for i, inst_amount in enumerate(installments):
                    if inst_amount <= 0:
                        continue
                    pay_date = min(started_on + timedelta(days=freq_days * i), TODAY)
                    payment_rows.append(PaymentFactory.build(
                        alumni=alumni, membership=membership, membership_tier=tier,
                        amount=inst_amount, payment_method=_pick_payment_method(tier),
                        payment_status="completed", payment_date=_aware(pay_date), completion_date=_aware(pay_date),
                    ))

        def generate_person(forced_tier=None):
            # Weighted toward recent decades -- enrollment grew over the
            # University's history, so a flat 1970-2026 spread would read
            # as wrong the moment anyone looks at the by-year breakdown.
            graduation_year = int(random.triangular(1970, 2026, 2016))

            faculty = random.choice(faculties)
            quals = quals_by_faculty.get(faculty.id) or []
            qualification = random.choice(quals) if quals else None
            level = qualification.level if qualification else None

            age = random.randint(*AGE_AT_GRADUATION_BY_LEVEL.get(level, AGE_AT_GRADUATION_BY_LEVEL[None]))
            dob_year = graduation_year - age
            dob = _random_date(date(dob_year, 1, 1), date(dob_year, 12, 31))

            user = UserFactory.build()
            profile = UserProfileFactory.build(user=user, date_of_birth=dob)
            slug = slugify(f"{profile.honorific} {profile.given_name} {profile.family_name}")
            alumni = AlumniProfileFactory.build(
                user=user, graduation_year=graduation_year, faculty=faculty,
                qualification=qualification, slug=slug,
            )

            tier = forced_tier or random.choices(tier_choices, weights=tier_weights, k=1)[0]
            status = random.choices(status_choices, weights=status_weights, k=1)[0]
            earliest_join = max(UONAA_FOUNDED, date(graduation_year, 1, 1))

            if status == Membership.Status.PENDING or earliest_join >= TODAY:
                # First-time applicant -- nothing activated yet, no renewal
                # history to simulate (mirrors the real registration flow).
                membership = MembershipFactory.build(
                    user=user, tier=tier, status=Membership.Status.PENDING, membership_number=None,
                    payment_frequency=Membership.PaymentFrequency.ONCE,
                    subscription_amount=tier.fee, amount_paid=Decimal("0"), legacy_signed=False,
                )
                membership_rows.append(membership)
                payment_rows.append(PaymentFactory.build(
                    alumni=alumni, membership=membership, membership_tier=tier,
                    amount=tier.fee, payment_method=_pick_payment_method(tier),
                    payment_status="pending", payment_date=_aware(TODAY),
                ))
            elif tier.is_lifetime():
                # One-time fee, no renewal -- a Life membership is paid
                # once, UNLESS it's on a stalled installment plan (the
                # only real way a Life-tier row can legitimately be
                # EXPIRED -- a fully-paid lump sum never can, since it has
                # no expires_on to lapse). Decide the coin flip HERE, once,
                # so it's consistent with `status` below rather than a
                # second independent roll inside build_row().
                is_installment = (
                    tier.tier_type in INSTALLMENT_ELIGIBLE_TYPES and random.random() < INSTALLMENT_TAKE_RATE
                )
                if status == Membership.Status.EXPIRED and not is_installment:
                    status = Membership.Status.ACTIVE
                started_on = _random_date(earliest_join, TODAY)
                build_row(user, alumni, tier, status, started_on,
                          next_membership_number(started_on.year), is_installment=is_installment)
            else:
                # Annual-cycle tier: real renewal history, one row per year
                # actually paid -- not one lump-sum row for the whole
                # membership lifetime. First-join date is uniform across
                # the person's whole eligible window (same as the lifetime
                # branch above), NOT clustered near earliest_join -- that
                # earlier version piled every pre-2005 graduate's first
                # join into UoNAA's first ~10 months of existence, an
                # unrealistic mass-signup spike (2026-08-10 correction:
                # 16% of all rows landed in 2005 alone). Renewal years then
                # count forward from whenever they actually joined.
                first_join = _random_date(earliest_join, TODAY)
                max_years = max(1, (TODAY - first_join).days // 365 + 1)
                years = min(
                    random.choices(renewal_year_choices, weights=renewal_year_weights, k=1)[0], max_years
                )
                for i in range(years):
                    row_started = min(first_join + timedelta(days=365 * i), TODAY)
                    is_final_year = i == years - 1
                    row_status = status if is_final_year else Membership.Status.EXPIRED
                    # An annual-cycle tier always has a real expires_on, so
                    # EXPIRED is legitimate here regardless of lump-sum vs
                    # installment (unlike the lifetime branch above) --
                    # only the final row can be on a plan at all, matching
                    # build_row()'s old allow_installment semantics.
                    is_installment = (
                        is_final_year and tier.tier_type in INSTALLMENT_ELIGIBLE_TYPES
                        and random.random() < INSTALLMENT_TAKE_RATE
                    )
                    # Each row still gets its own membership_number even
                    # though the 1.3 service layer (built 2026-08-10) now
                    # supports carrying one forward -- this generator
                    # bulk_creates directly and doesn't go through
                    # apps.home.services, so there's nothing to carry it
                    # forward from at this point in the loop.
                    build_row(user, alumni, tier, row_status, row_started, next_membership_number(row_started.year),
                              is_installment=is_installment)

            users.append(user)
            profiles.append(profile)
            alumni_rows.append(alumni)

            if len(users) >= batch_size:
                flush()
                if totals["users"] % (batch_size * 20) == 0:
                    self.stdout.write(f"  ...{totals['users']:,} / {count:,}")

        for n in range(count):
            generate_person()

        for tier_name, pool_count in FIXED_POOL_TIERS.items():
            self.stdout.write(f"Generating {pool_count:,} {tier_name} entries (fixed pool)...")
            for n in range(pool_count):
                generate_person(forced_tier=tiers_by_name[tier_name])

        if users:
            flush()

        self.stdout.write(self.style.SUCCESS(
            f"Done: {totals['users']:,} alumni, {totals['memberships']:,} memberships, "
            f"{totals['payments']:,} payments."
        ))
