from django.contrib import admin
from django.utils.html import format_html
from .models import (
    UserProfile, GeneratedImage, GeneratedVideo, BlogPost, FeaturedAsset,
    AssetRating, AssetComment, CommentReaction, AssetView,
    Follow, Collection, CollectionItem, Bookmark, Notification,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'location', 'needs_profile_completion', 'created_at']
    list_filter = ['needs_profile_completion']
    search_fields = ['user__username', 'user__email', 'user__first_name']


@admin.register(GeneratedImage)
class GeneratedImageAdmin(admin.ModelAdmin):
    list_display = ['user', 'display_title_short', 'style', 'is_saved', 'is_published', 'coin_price', 'view_count', 'created_at']
    list_filter = ['is_published', 'is_saved', 'style']
    list_editable = ['is_published', 'coin_price']
    search_fields = ['user__username', 'prompt', 'title']
    readonly_fields = ['created_at', 'image_preview', 'view_count']

    def display_title_short(self, obj):
        t = obj.display_title()
        return t[:60] + '…' if len(t) > 60 else t
    display_title_short.short_description = 'Title / Prompt'

    def image_preview(self, obj):
        if obj.image_url:
            return format_html('<img src="{}" style="max-height:120px;border-radius:8px;">', obj.image_url)
        return '—'
    image_preview.short_description = 'Preview'


@admin.register(GeneratedVideo)
class GeneratedVideoAdmin(admin.ModelAdmin):
    list_display = ['user', 'category', 'product_name', 'status', 'duration', 'caption_style', 'is_saved', 'is_published', 'coin_price', 'view_count', 'created_at']
    list_filter = ['status', 'category', 'caption_style', 'is_published', 'is_saved']
    list_editable = ['is_published', 'coin_price']
    search_fields = ['user__username', 'product_name', 'title']
    readonly_fields = ['created_at', 'updated_at', 'view_count']


@admin.register(AssetView)
class AssetViewAdmin(admin.ModelAdmin):
    list_display = ('asset_type', 'asset_id', 'user', 'session_key', 'viewed_at')
    list_filter = ('asset_type', 'viewed_at')
    search_fields = ('user__username', 'session_key', 'asset_id')
    readonly_fields = ('viewed_at',)


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'author', 'is_published', 'show_on_home', 'home_order', 'created_at']
    list_filter = ['is_published', 'show_on_home', 'category']
    list_editable = ['is_published', 'show_on_home', 'home_order']
    prepopulated_fields = {'slug': ('title',)}
    search_fields = ['title', 'body', 'excerpt']
    readonly_fields = ['created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)


@admin.register(FeaturedAsset)
class FeaturedAssetAdmin(admin.ModelAdmin):
    list_display = ['asset_type', 'get_asset_label', 'order', 'created_at']
    list_editable = ['order']
    list_filter = ['asset_type']

    def get_asset_label(self, obj):
        a = obj.get_asset()
        return str(a) if a else '—'
    get_asset_label.short_description = 'Asset'


@admin.register(AssetRating)
class AssetRatingAdmin(admin.ModelAdmin):
    list_display = ('user', 'asset_type', 'asset_id', 'score', 'created_at')
    list_filter = ('asset_type', 'score')
    search_fields = ('user__username',)


@admin.register(AssetComment)
class AssetCommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'asset_type', 'asset_id', 'parent', 'body_preview', 'created_at')
    list_filter = ('asset_type',)
    search_fields = ('body', 'user__username')
    readonly_fields = ('created_at', 'updated_at')

    def body_preview(self, obj):
        return obj.body[:70] + ('…' if len(obj.body) > 70 else '')
    body_preview.short_description = 'Comment'


@admin.register(CommentReaction)
class CommentReactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'emoji', 'comment', 'created_at')
    list_filter = ('emoji',)


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ('follower', 'following', 'created_at')
    search_fields = ('follower__username', 'following__username')


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'is_public', 'created_at')
    list_filter = ('is_public',)
    search_fields = ('user__username', 'name')


@admin.register(CollectionItem)
class CollectionItemAdmin(admin.ModelAdmin):
    list_display = ('collection', 'asset_type', 'asset_id', 'added_at')


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ('user', 'asset_type', 'asset_id', 'created_at')
    search_fields = ('user__username',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'actor', 'notif_type', 'message', 'is_read', 'created_at')
    list_filter = ('notif_type', 'is_read')
    search_fields = ('recipient__username', 'actor__username', 'message', 'admin_note')
    list_editable = ('is_read',)
