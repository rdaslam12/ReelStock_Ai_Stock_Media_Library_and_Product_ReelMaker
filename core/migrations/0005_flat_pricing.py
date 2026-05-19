"""
Data migration: re-price every published asset to the new flat values.

The first version of pricing used random ranges (images 1–3, videos 2–5).
Per project requirements, prices are now flat:
  - Images: 40 RC
  - Videos: 100 RC

This walks through every published image and video and overwrites the
coin_price with the new flat value, regardless of what was set before.
"""
from django.db import migrations


def reprice_assets(apps, schema_editor):
    GeneratedImage = apps.get_model('core', 'GeneratedImage')
    GeneratedVideo = apps.get_model('core', 'GeneratedVideo')

    # Set ALL published images to 40 RC (overwrites old random prices)
    GeneratedImage.objects.filter(is_published=True).update(coin_price=40)

    # Set ALL published videos to 100 RC
    GeneratedVideo.objects.filter(is_published=True).update(coin_price=100)


def reverse_noop(apps, schema_editor):
    # No reverse — pricing data is non-destructive to leave in place.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_populate_prices'),
    ]

    operations = [
        migrations.RunPython(reprice_assets, reverse_noop),
    ]
