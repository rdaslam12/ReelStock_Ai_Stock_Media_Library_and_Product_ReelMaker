from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0002_backfill_wallets'),
    ]

    operations = [
        migrations.AddField(
            model_name='coinrequest',
            name='payment_method',
            field=models.CharField(
                choices=[
                    ('paypal', 'PayPal'),
                    ('applepay', 'Apple Pay'),
                    ('googlepay', 'Google Pay'),
                ],
                default='paypal',
                max_length=16,
                verbose_name='Payment Method',
            ),
        ),
        migrations.AddField(
            model_name='coinrequest',
            name='transaction_id',
            field=models.CharField(
                blank=True,
                help_text='Payment transaction or confirmation reference provided by the user.',
                max_length=100,
                verbose_name='Transaction ID',
            ),
        ),
        migrations.AddField(
            model_name='coinrequest',
            name='usd_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=8,
                verbose_name='USD Amount Paid',
            ),
        ),
    ]
