from django.apps import AppConfig


class WalletConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wallet'
    verbose_name = 'Wallet & Download Basket'

    def ready(self):
        # Connect signals so new users automatically get a Wallet with 100 coins.
        from . import signals  # noqa: F401
