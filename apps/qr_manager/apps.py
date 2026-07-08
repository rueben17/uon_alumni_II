from django.apps import AppConfig


class QrManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.qr_manager'

    def ready(self):
        from apps.qr_manager import signals  # noqa: F401
