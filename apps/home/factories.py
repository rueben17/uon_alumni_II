"""factory_boy definitions for synthetic demo/load-test data.

These are used with the `.build()` strategy only (never `.create()`) --
the `generate_demo_data` management command bulk_create()s the resulting
instances itself in batches. `.create()` would issue one INSERT per
related object per person, which does not scale past a few thousand rows;
`.build()` just constructs the Python object (PKs already fill in locally
since every model here uses `default=uuid.uuid4`, not a DB-assigned pk).

Not test fixtures for the pytest/unittest suite -- apps/user/tests.py's
phone tests don't need factories. This exists solely for demo-scale data
generation.
"""
import random

import factory
from factory import fuzzy
from faker import Faker as FakerLib

from apps.home.models import AlumniProfile, Membership, Payment
from apps.user.models import CURRENT_PRIVACY_NOTICE_VERSION, Gender, Honorific, User, UserProfile

_faker = FakerLib()

HONORIFIC_BY_GENDER = {
    Gender.MALE: [Honorific.MR, Honorific.MR, Honorific.MR, Honorific.DR, Honorific.PROF, Honorific.REV],
    Gender.FEMALE: [Honorific.MRS, Honorific.MS, Honorific.MISS, Honorific.MRS, Honorific.DR, Honorific.PROF],
}


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"demo.alumnus.{n}@example.test")
    phone = factory.Sequence(lambda n: f"+254{7 if n % 5 else 1}{n % 100000000:08d}")
    email_verified = True
    phone_verified = True
    auth_provider = User.AuthProvider.EMAIL
    is_staff = False
    is_active = True


class UserProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserProfile

    gender = fuzzy.FuzzyChoice([Gender.MALE, Gender.FEMALE])
    honorific = factory.LazyAttribute(lambda o: random.choice(HONORIFIC_BY_GENDER[o.gender]))
    given_name = factory.LazyAttribute(
        lambda o: _faker.first_name_male() if o.gender == Gender.MALE else _faker.first_name_female()
    )
    family_name = factory.LazyAttribute(lambda o: _faker.last_name())
    nationality = "Kenyan"
    national_id = factory.Sequence(lambda n: str(20_000_000 + n))
    sms_opt_in = fuzzy.FuzzyChoice([True, False])
    email_opt_in = fuzzy.FuzzyChoice([True, False])
    privacy_notice_version = CURRENT_PRIVACY_NOTICE_VERSION


class AlumniProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AlumniProfile

    graduation_institution = AlumniProfile.GraduationInstitution.UON
    is_active = True


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment
