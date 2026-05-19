from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.utils.text import slugify
import uuid
import os
from urllib.parse import urlparse


def _normalize_media_url(value):
    """Return a browser-accessible URL for stored MEDIA_ROOT paths or names."""
    raw = str(value or '').strip()
    if not raw:
        return ''
    if raw.startswith(('http://', 'https://')):
        return raw

    media_root = str(getattr(settings, 'MEDIA_ROOT', '')).rstrip('/\\')
    if media_root and raw.startswith(media_root):
        rel = os.path.relpath(raw, media_root).replace(os.sep, '/')
        return f"{settings.MEDIA_URL.rstrip('/')}/{rel.lstrip('/')}"

    normalized = raw.replace('\\', '/')
    marker = '/media/'
    if marker in normalized:
        rel = normalized.split(marker, 1)[1]
        return f"{settings.MEDIA_URL.rstrip('/')}/{rel.lstrip('/')}"

    media_url = settings.MEDIA_URL or '/media/'
    if raw.startswith(media_url):
        return raw

    media_prefix = media_url.lstrip('/')
    if media_prefix and raw.lstrip('/').startswith(media_prefix):
        return f"/{raw.lstrip('/')}"

    if raw.startswith(('generated/', 'generated_videos/', 'reel_inputs/', 'reels/')):
        return f"{settings.MEDIA_URL.rstrip('/')}/{raw.lstrip('/')}"

    return raw


def _media_name_from_url(value):
    """Return a storage-relative media name when the URL points into MEDIA_URL."""
    raw = str(value or '').strip()
    if not raw:
        return ''

    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme else raw
    url = _normalize_media_url(path)

    media_url = settings.MEDIA_URL or '/media/'
    if url.startswith(media_url):
        return url[len(media_url):].lstrip('/')
    if url.startswith('/media/'):
        return url[len('/media/'):]
    if url.startswith('media/'):
        return url[len('media/'):]
    return ''


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.CharField(max_length=300, blank=True)
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    x_handle = models.CharField(max_length=100, blank=True)
    instagram = models.CharField(max_length=100, blank=True)
    youtube = models.CharField(max_length=100, blank=True)
    tiktok = models.CharField(max_length=100, blank=True)
    needs_profile_completion = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile({self.user.username})"

    def display_name(self):
        full = f"{self.user.first_name} {self.user.last_name}".strip()
        return full or self.user.username


class GeneratedImage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='images')
    prompt = models.TextField()
    style = models.CharField(max_length=100, blank=True)
    aspect_ratio = models.CharField(max_length=20, blank=True)
    image_file = models.ImageField(upload_to='generated/', blank=True)
    image_url = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_saved = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)   # visible in Library
    title = models.CharField(max_length=200, blank=True)
    coin_price = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Image({self.user.username}, {self.created_at:%Y-%m-%d})"

    def display_title(self):
        return self.title or (self.prompt[:60] + '…' if len(self.prompt) > 60 else self.prompt)

    @property
    def media_url(self):
        if self.image_file:
            return self.image_file.url
        return _normalize_media_url(self.image_url)

    def save(self, *args, **kwargs):
        if self.is_published and not self.coin_price:
            self.coin_price = 40
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {'coin_price'}
        super().save(*args, **kwargs)


class GeneratedVideo(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='videos')
    category = models.CharField(max_length=100, blank=True)
    product_name = models.CharField(max_length=200, blank=True)
    source_image = models.ImageField(upload_to='reel_inputs/', blank=True, null=True)
    source_image_url = models.CharField(max_length=500, blank=True)
    video_url = models.CharField(max_length=1000, blank=True)
    video_file = models.FileField(upload_to='reels/', blank=True, null=True)
    request_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    duration = models.CharField(max_length=20, blank=True, default='5')
    video_style = models.CharField(max_length=100, blank=True, default='Cinematic')
    caption_style = models.CharField(max_length=40, blank=True, default='auto')
    caption_script = models.JSONField(default=list, blank=True)
    is_saved = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)  # visible in Library
    title = models.CharField(max_length=200, blank=True)
    coin_price = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Video({self.user.username}, {self.category}, {self.status})"

    def display_title(self):
        return self.title or f"{self.product_name or self.category} Reel"

    @property
    def media_url(self):
        if self.video_file and self.video_file.name:
            return self.video_file.url
        return _normalize_media_url(self.video_url)

    @property
    def playback_url(self):
        return self.media_url

    def sync_video_file_from_url(self):
        """
        Backfill video_file from a local video_url such as /media/reels/x.mp4.
        Returns True when the field was changed.
        """
        if self.video_file and self.video_file.name:
            return False
        file_name = _media_name_from_url(self.video_url)
        if not file_name:
            return False
        self.video_file.name = file_name
        return True

    @property
    def source_media_url(self):
        if self.source_image:
            return self.source_image.url
        return _normalize_media_url(self.source_image_url)

    def save(self, *args, **kwargs):
        if self.is_published and not self.coin_price:
            self.coin_price = 100
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {'coin_price'}
        super().save(*args, **kwargs)


class BlogPost(models.Model):
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    category = models.CharField(max_length=100, blank=True, default='Updates')
    excerpt = models.TextField(max_length=400, blank=True)
    body = models.TextField()
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='blog_posts')
    is_published = models.BooleanField(default=True)
    show_on_home = models.BooleanField(default=True)
    home_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['home_order', '-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)
            slug = base
            n = 1
            while BlogPost.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


ASSET_TYPE_CHOICES = [('image', 'Image'), ('video', 'Video')]


class AssetView(models.Model):
    """A lightweight unique-ish page view event for public asset detail pages."""
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='asset_views',
    )
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    asset_id = models.PositiveIntegerField()
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['asset_type', 'asset_id', 'viewed_at']),
            models.Index(fields=['user', 'asset_type', 'asset_id', 'viewed_at']),
            models.Index(fields=['session_key', 'asset_type', 'asset_id', 'viewed_at']),
        ]

    def __str__(self):
        who = self.user.username if self.user_id else self.session_key or 'anonymous'
        return f"View({who}, {self.asset_type}#{self.asset_id})"


class AssetRating(models.Model):
    """One rating per user per published asset."""
    SCORE_CHOICES = [(i, str(i)) for i in range(1, 6)]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ratings')
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    asset_id = models.PositiveIntegerField()
    score = models.PositiveSmallIntegerField(choices=SCORE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'asset_type', 'asset_id'],
                name='unique_rating_per_user_asset',
            )
        ]

    def __str__(self):
        return f"Rating({self.user.username}, {self.asset_type}#{self.asset_id}, {self.score})"


class AssetComment(models.Model):
    """Persistent comments on an image or video, with one level of replies."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    asset_id = models.PositiveIntegerField()
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='replies',
    )
    body = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment({self.user.username}, {self.asset_type}#{self.asset_id})"

    @property
    def is_reply(self):
        return self.parent_id is not None


class CommentReaction(models.Model):
    """Emoji reaction on a comment."""
    EMOJI_CHOICES = ['👍', '❤️', '😂', '😮', '🔥', '👏']

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comment_reactions')
    comment = models.ForeignKey(AssetComment, on_delete=models.CASCADE, related_name='reactions')
    emoji = models.CharField(max_length=10, default='👍')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'comment', 'emoji'],
                name='unique_reaction_per_user_comment_emoji',
            )
        ]

    def __str__(self):
        return f"Reaction({self.user.username}, {self.emoji}, comment#{self.comment_id})"


class Follow(models.Model):
    """A user follows another creator."""
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following')
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['follower', 'following'], name='unique_follow')
        ]

    def __str__(self):
        return f"{self.follower.username} follows {self.following.username}"


class Collection(models.Model):
    """A named board where users can save published assets."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='collections')
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Collection({self.user.username}: {self.name})"


class CollectionItem(models.Model):
    """An asset saved inside a collection."""
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name='items')
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    asset_id = models.PositiveIntegerField()
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.UniqueConstraint(
                fields=['collection', 'asset_type', 'asset_id'],
                name='unique_collection_item',
            )
        ]

    def __str__(self):
        return f"Item({self.collection.name}, {self.asset_type}#{self.asset_id})"


class Bookmark(models.Model):
    """One-click personal bookmark for a published asset."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookmarks')
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    asset_id = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'asset_type', 'asset_id'],
                name='unique_bookmark',
            )
        ]

    def __str__(self):
        return f"Bookmark({self.user.username}, {self.asset_type}#{self.asset_id})"


class Notification(models.Model):
    NOTIF_COMMENT = 'comment'
    NOTIF_REPLY = 'reply'
    NOTIF_FOLLOW = 'follow'
    NOTIF_ADMIN = 'admin_action'
    NOTIF_CHOICES = [
        (NOTIF_COMMENT, 'Comment on your asset'),
        (NOTIF_REPLY, 'Reply to your comment'),
        (NOTIF_FOLLOW, 'New follower'),
        (NOTIF_ADMIN, 'Admin action'),
    ]

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    actor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_notifications')
    notif_type = models.CharField(max_length=20, choices=NOTIF_CHOICES)
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES, blank=True)
    asset_id = models.PositiveIntegerField(null=True, blank=True)
    comment = models.ForeignKey(AssetComment, null=True, blank=True, on_delete=models.SET_NULL)
    message = models.CharField(max_length=255, blank=True)
    admin_note = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification({self.recipient.username}, {self.notif_type})"

    def get_message(self):
        if self.notif_type == self.NOTIF_ADMIN and self.message:
            return self.message
        actor_name = self.actor.get_full_name() or self.actor.username
        if self.notif_type == self.NOTIF_COMMENT:
            return f"{actor_name} commented on your asset"
        if self.notif_type == self.NOTIF_REPLY:
            return f"{actor_name} replied to your comment"
        if self.notif_type == self.NOTIF_FOLLOW:
            return f"{actor_name} started following you"
        return "New notification"


class FeaturedAsset(models.Model):
    """Superuser picks which published images/videos appear on the homepage."""
    ASSET_IMAGE = 'image'
    ASSET_VIDEO = 'video'
    ASSET_CHOICES = [(ASSET_IMAGE, 'Image'), (ASSET_VIDEO, 'Video')]

    asset_type = models.CharField(max_length=10, choices=ASSET_CHOICES)
    image = models.ForeignKey(GeneratedImage, null=True, blank=True, on_delete=models.CASCADE)
    video = models.ForeignKey(GeneratedVideo, null=True, blank=True, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-created_at']

    def __str__(self):
        if self.asset_type == self.ASSET_IMAGE and self.image:
            return f"Featured Image: {self.image}"
        if self.asset_type == self.ASSET_VIDEO and self.video:
            return f"Featured Video: {self.video}"
        return f"FeaturedAsset #{self.pk}"

    def get_asset(self):
        return self.image if self.asset_type == self.ASSET_IMAGE else self.video
