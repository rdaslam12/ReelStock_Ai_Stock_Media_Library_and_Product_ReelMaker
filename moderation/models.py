from django.conf import settings
from django.db import models

from core.models import GeneratedImage, GeneratedVideo


class AdminActionLog(models.Model):
    ACTION_ASSET_DELETED = "asset_deleted"
    ACTION_ASSET_UNPUBLISHED = "asset_unpublished"
    ACTION_ASSET_MODERATED = "asset_moderated"
    ACTION_COINS_ADDED = "coins_added"
    ACTION_COINS_REMOVED = "coins_removed"
    ACTION_USER_DEACTIVATED = "user_deactivated"
    ACTION_USER_REACTIVATED = "user_reactivated"
    ACTION_STAFF_GRANTED = "staff_granted"
    ACTION_STAFF_REVOKED = "staff_revoked"
    ACTION_SUPERUSER_GRANTED = "superuser_granted"
    ACTION_SUPERUSER_REVOKED = "superuser_revoked"
    ACTION_COIN_REQUEST_APPROVED = "coin_request_approved"
    ACTION_COIN_REQUEST_REJECTED = "coin_request_rejected"
    ACTION_CONTENT_UPDATED = "content_updated"
    ACTION_CHOICES = [
        (ACTION_ASSET_DELETED, "Asset deleted"),
        (ACTION_ASSET_UNPUBLISHED, "Asset unpublished"),
        (ACTION_ASSET_MODERATED, "Asset moderated"),
        (ACTION_COINS_ADDED, "Coins added"),
        (ACTION_COINS_REMOVED, "Coins removed"),
        (ACTION_USER_DEACTIVATED, "User deactivated"),
        (ACTION_USER_REACTIVATED, "User reactivated"),
        (ACTION_STAFF_GRANTED, "Staff granted"),
        (ACTION_STAFF_REVOKED, "Staff revoked"),
        (ACTION_SUPERUSER_GRANTED, "Superuser granted"),
        (ACTION_SUPERUSER_REVOKED, "Superuser revoked"),
        (ACTION_COIN_REQUEST_APPROVED, "Coin request approved"),
        (ACTION_COIN_REQUEST_REJECTED, "Coin request rejected"),
        (ACTION_CONTENT_UPDATED, "Content updated"),
    ]

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_actions_performed",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_actions_received",
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    asset_type = models.CharField(max_length=10, blank=True)
    asset_id = models.PositiveIntegerField(null=True, blank=True)
    object_label = models.CharField(max_length=220, blank=True)
    note = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    email_sent = models.BooleanField(default=False)
    email_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["target_user", "created_at"]),
            models.Index(fields=["asset_type", "asset_id"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} by {self.admin or 'system'}"


class TrendingOverride(models.Model):
    ASSET_IMAGE = "image"
    ASSET_VIDEO = "video"
    ASSET_CHOICES = [(ASSET_IMAGE, "Image"), (ASSET_VIDEO, "Video")]

    asset_type = models.CharField(max_length=10, choices=ASSET_CHOICES)
    image = models.ForeignKey(GeneratedImage, null=True, blank=True, on_delete=models.CASCADE)
    video = models.ForeignKey(GeneratedVideo, null=True, blank=True, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset_type", "image"],
                condition=models.Q(image__isnull=False),
                name="unique_trending_image_override",
            ),
            models.UniqueConstraint(
                fields=["asset_type", "video"],
                condition=models.Q(video__isnull=False),
                name="unique_trending_video_override",
            ),
        ]

    def __str__(self):
        asset = self.get_asset()
        return f"Trending {self.asset_type}: {asset or 'missing asset'}"

    def get_asset(self):
        return self.image if self.asset_type == self.ASSET_IMAGE else self.video
