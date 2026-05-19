from django.contrib import admin

from .models import AdminActionLog, TrendingOverride


@admin.register(AdminActionLog)
class AdminActionLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "admin", "target_user", "asset_type", "asset_id", "email_sent")
    list_filter = ("action", "email_sent", "created_at")
    search_fields = ("admin__username", "target_user__username", "object_label", "note")
    readonly_fields = ("created_at",)


@admin.register(TrendingOverride)
class TrendingOverrideAdmin(admin.ModelAdmin):
    list_display = ("asset_type", "get_asset_label", "order", "is_active", "updated_at")
    list_filter = ("asset_type", "is_active")
    list_editable = ("order", "is_active")
    search_fields = ("image__title", "image__prompt", "video__title", "video__product_name", "note")

    def get_asset_label(self, obj):
        return obj.get_asset() or "Missing asset"

    get_asset_label.short_description = "Asset"
