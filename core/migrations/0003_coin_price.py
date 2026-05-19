from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_extend'),
    ]

    operations = [
        migrations.AddField(
            model_name='generatedimage',
            name='coin_price',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='generatedvideo',
            name='coin_price',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
