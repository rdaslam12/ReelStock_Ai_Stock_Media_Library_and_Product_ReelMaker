from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0003_coin_price'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Wallet
        migrations.CreateModel(
            name='Wallet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('balance', models.PositiveIntegerField(default=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='wallet',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'verbose_name': 'Wallet', 'verbose_name_plural': 'Wallets'},
        ),

        # Transaction
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[
                    ('signup_bonus', 'Welcome Bonus'),
                    ('download', 'Download Purchase'),
                    ('admin_grant', 'Coin Request Approved'),
                    ('admin_adjust', 'Manual Adjustment'),
                ], max_length=24)),
                ('delta', models.IntegerField(help_text='Positive = credit, negative = debit.')),
                ('balance_after', models.PositiveIntegerField()),
                ('note', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('wallet', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transactions',
                    to='wallet.wallet',
                )),
            ],
            options={'ordering': ['-created_at']},
        ),

        # CoinRequest
        migrations.CreateModel(
            name='CoinRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.PositiveIntegerField()),
                ('reason', models.TextField(blank=True)),
                ('status', models.CharField(choices=[
                    ('pending', 'Pending'),
                    ('approved', 'Approved'),
                    ('rejected', 'Rejected'),
                ], default='pending', max_length=12)),
                ('admin_note', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='coin_requests',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('resolved_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='resolved_coin_requests',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-created_at']},
        ),

        # BasketItem
        migrations.CreateModel(
            name='BasketItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('coin_price_snapshot', models.PositiveIntegerField(default=0)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('image', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='+',
                    to='core.generatedimage',
                )),
                ('video', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='+',
                    to='core.generatedvideo',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='basket_items',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-added_at']},
        ),
        migrations.AddConstraint(
            model_name='basketitem',
            constraint=models.UniqueConstraint(
                condition=models.Q(('image__isnull', False)),
                fields=('user', 'image'),
                name='unique_user_image_in_basket',
            ),
        ),
        migrations.AddConstraint(
            model_name='basketitem',
            constraint=models.UniqueConstraint(
                condition=models.Q(('video__isnull', False)),
                fields=('user', 'video'),
                name='unique_user_video_in_basket',
            ),
        ),
    ]
