"""Backfill a UserProfile for every account that predates the invariant.

apps/user/signals.py now creates one for every new User, but accounts
made before that -- by createsuperuser, the shell, or the Django admin's
add form -- still have none, and roughly twenty unguarded
`user.profile.*` reads raise RelatedObjectDoesNotExist against them.
See qa_500_report.md findings 4 and 5.

The signal closes the intake; this closes the backlog. It is deliberately
a separate migration from the code change, so it can be reviewed and run
on its own.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    """Create the missing rows, keyed on the user so it is idempotent.

    Uses the historical models, so the post_save receiver does not fire
    here -- it is connected to the real User class, not this one. That
    means no double-creation, and no dependency on app-loading order.

    No field values are supplied: given_name and family_name default to
    the empty string, and the DPA-2019 consent flags default to False.
    Inventing a name for someone during a data migration would be worse
    than leaving it blank, and apps/qr_manager/views.py's _holder_name()
    already refuses to render a card for a holder it cannot name.
    """
    User = apps.get_model("user", "User")
    UserProfile = apps.get_model("user", "UserProfile")

    missing = User.objects.filter(profile__isnull=True).values_list("pk", flat=True)
    for user_pk in missing.iterator():
        UserProfile.objects.get_or_create(user_id=user_pk)


def unbackfill(apps, schema_editor):
    """Deliberately a no-op.

    A profile created here may have been edited since, and there is no
    way to tell those apart from the ones this migration made. Deleting
    on reverse would destroy real data to undo a fix.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0001_initial"),
    ]

    operations = [
        # elidable: a fresh database never needs this, because the signal
        # creates the profile from the first account onwards.
        migrations.RunPython(backfill, unbackfill, elidable=True),
    ]
