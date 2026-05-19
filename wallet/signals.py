"""
Signals that hook into Django's auth system.

Whenever a User row is created (registration, createsuperuser, admin "add user"),
we automatically:
  1. Create a Wallet with the welcome bonus (100 RC).
  2. Record a Transaction in the audit log so the user can see the bonus
     when they open their wallet history.
"""
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Wallet, Transaction


@receiver(post_save, sender=User)
def create_wallet_for_new_user(sender, instance, created, **kwargs):
    if not created:
        return
    # Avoid duplicates if a wallet was already created elsewhere.
    if hasattr(instance, 'wallet'):
        return
    wallet = Wallet.objects.create(user=instance, balance=Wallet.SIGNUP_BONUS)
    Transaction.objects.create(
        wallet=wallet,
        kind=Transaction.KIND_SIGNUP,
        delta=Wallet.SIGNUP_BONUS,
        balance_after=wallet.balance,
        note=f"Welcome to ReelStock! You received {Wallet.SIGNUP_BONUS} Reel Coins.",
    )
