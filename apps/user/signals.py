"""Signal receivers for apps.user.

First signals module in this project -- there was no existing
convention to follow (no signals.py, no AppConfig.ready(), no @receiver
anywhere), so this establishes the standard Django one: receivers live
here and are connected by importing this module from
UserConfig.ready() in apps/user/apps.py.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.user.models import User, UserProfile


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, raw=False, **kwargs):
    """Every User has a UserProfile -- an invariant, not a convention.

    UserManager.create_user does not create one (apps/user/models.py:25-36),
    so any account made by createsuperuser, the shell, the admin's add
    form or a future non-social signup previously had none, and roughly
    twenty unguarded `user.profile.*` reads raised
    RelatedObjectDoesNotExist. See qa_500_report.md findings 4 and 5.

    A post_save receiver rather than a UserManager override: the override
    only covers create_user(), and is bypassed by User.objects.create(),
    User(...).save(), the admin's add form and loaddata -- which are
    exactly the paths that produced the profile-less accounts.

    No field values are supplied. given_name and family_name are
    CharFields whose default is the empty string, so the row is valid
    with blank names; deriving a name from the e-mail local part would
    fabricate identity data, and the Google adapter fills them properly
    on first login (apps/user/adapter.py:111). The DPA-2019 consent
    flags stay False by their own defaults -- consent cannot be
    pre-granted (apps/user/models.py:203-205).

    `raw` is honoured because loaddata fires post_save before related
    tables are populated. get_or_create rather than create keeps this
    idempotent alongside the adapter, which may already have created the
    profile in the same request.
    """
    if raw or not created:
        return
    UserProfile.objects.get_or_create(user=instance)
