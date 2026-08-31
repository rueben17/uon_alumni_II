from django.apps import AppConfig


class UserConfig(AppConfig):
    name = 'apps.user'

    def ready(self):
        # Connects ensure_user_profile -- see apps/user/signals.py.
        # 'apps.user' in INSTALLED_APPS auto-discovers this AppConfig,
        # so no settings change is needed for ready() to run.
        from apps.user import signals  # noqa: F401
