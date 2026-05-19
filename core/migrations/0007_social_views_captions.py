from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0006_assetcomment_collection_notification_follow_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="needs_profile_completion",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="generatedimage",
            name="view_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="generatedvideo",
            name="caption_script",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="generatedvideo",
            name="caption_style",
            field=models.CharField(blank=True, default="auto", max_length=40),
        ),
        migrations.AddField(
            model_name="generatedvideo",
            name="view_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="AssetView",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("session_key", models.CharField(blank=True, db_index=True, max_length=40)),
                (
                    "asset_type",
                    models.CharField(
                        choices=[("image", "Image"), ("video", "Video")],
                        max_length=10,
                    ),
                ),
                ("asset_id", models.PositiveIntegerField()),
                ("viewed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="asset_views",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-viewed_at"],
                "indexes": [
                    models.Index(
                        fields=["asset_type", "asset_id", "viewed_at"],
                        name="core_assetv_asset_t_50a932_idx",
                    ),
                    models.Index(
                        fields=["user", "asset_type", "asset_id", "viewed_at"],
                        name="core_assetv_user_id_d62995_idx",
                    ),
                    models.Index(
                        fields=["session_key", "asset_type", "asset_id", "viewed_at"],
                        name="core_assetv_session_c162f8_idx",
                    ),
                ],
            },
        ),
    ]
