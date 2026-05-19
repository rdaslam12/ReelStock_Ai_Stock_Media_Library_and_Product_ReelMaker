"""
Data migration: every existing user gets a Wallet with the welcome bonus.

Without this, anybody who registered before the wallet feature shipped
would have no balance and the basket would crash. We back-fill the
audit log with a Transaction entry so their history makes sense.
"""
from django.db import migrations


def create_wallets_for_existing_users(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Wallet = apps.get_model('wallet', 'Wallet')
    Transaction = apps.get_model('wallet', 'Transaction')

    for user in User.objects.all():
        wallet, created = Wallet.objects.get_or_create(
            user=user, defaults={'balance': 100},
        )
        if created:
            Transaction.objects.create(
                wallet=wallet,
                kind='signup_bonus',
                delta=100,
                balance_after=wallet.balance,
                note="Welcome bonus (back-filled).",
            )


def delete_wallets(apps, schema_editor):
    Wallet = apps.get_model('wallet', 'Wallet')
    Wallet.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_wallets_for_existing_users, delete_wallets),
    ]
