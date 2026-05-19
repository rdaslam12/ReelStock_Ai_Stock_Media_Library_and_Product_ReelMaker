from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add is_published + title to GeneratedImage
        migrations.AddField(
            model_name='generatedimage',
            name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='generatedimage',
            name='title',
            field=models.CharField(blank=True, max_length=200),
        ),
        # Add is_published + title to GeneratedVideo
        migrations.AddField(
            model_name='generatedvideo',
            name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='generatedvideo',
            name='title',
            field=models.CharField(blank=True, max_length=200),
        ),
        # BlogPost model
        migrations.CreateModel(
            name='BlogPost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=300)),
                ('slug', models.SlugField(blank=True, max_length=320, unique=True)),
                ('category', models.CharField(blank=True, default='Updates', max_length=100)),
                ('excerpt', models.TextField(blank=True, max_length=400)),
                ('body', models.TextField()),
                ('is_published', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='blog_posts', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        # FeaturedAsset model
        migrations.CreateModel(
            name='FeaturedAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset_type', models.CharField(choices=[('image', 'Image'), ('video', 'Video')], max_length=10)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('image', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    to='core.generatedimage')),
                ('video', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    to='core.generatedvideo')),
            ],
            options={'ordering': ['order', '-created_at']},
        ),
    ]
