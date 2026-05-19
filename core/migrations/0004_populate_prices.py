"""
Data migration: assign random coin prices to all already-published assets.

Without this, every asset that existed before the wallet feature was added
would have coin_price=0 and feel "free". This walks through every published
image (1–3 RC) and every published video (2–5 RC) and gives them a price.
"""
import random
from django.db import migrations


def populate_prices(apps, schema_editor):
    GeneratedImage = apps.get_model('core', 'GeneratedImage')
    GeneratedVideo = apps.get_model('core', 'GeneratedVideo')

    for img in GeneratedImage.objects.filter(is_published=True, coin_price=0):
        img.coin_price = random.randint(1, 3)
        img.save(update_fields=['coin_price'])

    for vid in GeneratedVideo.objects.filter(is_published=True, coin_price=0):
        vid.coin_price = random.randint(2, 5)
        vid.save(update_fields=['coin_price'])


def reverse_noop(apps, schema_editor):
    # No reverse — pricing data is non-destructive to leave in place.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_coin_price'),
    ]

    operations = [
        migrations.RunPython(populate_prices, reverse_noop),
    ]
