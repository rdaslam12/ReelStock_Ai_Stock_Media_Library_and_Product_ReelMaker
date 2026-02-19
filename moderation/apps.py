from django.apps import AppConfig


class ModerationConfig(AppConfig):
    """Configuration for the moderation application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'moderation'