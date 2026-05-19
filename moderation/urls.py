from django.urls import path

from . import views


urlpatterns = [
    path("", views.admin_dashboard, name="admin_dashboard"),
    path("login/", views.admin_login, name="admin_login"),
    path("logout/", views.admin_logout, name="admin_logout"),
    path("users/", views.admin_users, name="admin_users"),
    path("users/<int:user_id>/", views.admin_user_detail, name="admin_user_detail"),
    path("users/<int:user_id>/wallet-adjust/", views.admin_user_adjust_wallet, name="admin_user_adjust_wallet"),
    path("users/<int:user_id>/<str:action>/", views.admin_user_action, name="admin_user_action"),
    path("assets/", views.admin_assets, name="admin_assets"),
    path("assets/<str:asset_type>/<int:asset_id>/", views.admin_asset_detail, name="admin_asset_detail"),
    path("assets/<str:asset_type>/<int:asset_id>/update/", views.admin_asset_update, name="admin_asset_update"),
    path("assets/<str:asset_type>/<int:asset_id>/<str:action>/", views.admin_asset_action, name="admin_asset_action"),
    path("reels/", views.admin_reels, name="admin_reels"),
    path("wallets/", views.admin_wallets, name="admin_wallets"),
    path(
        "coin-requests/<int:request_id>/<str:action>/",
        views.admin_coin_request_action,
        name="admin_coin_request_action",
    ),
    path("engagement/", views.admin_engagement, name="admin_engagement"),
    path("engagement/trending/", views.admin_trending_action, name="admin_trending_action"),
    path("reports/", views.admin_reports, name="admin_reports"),
    path("tools/", views.admin_tools, name="admin_tools"),
    path("tools/featured/", views.admin_featured_action, name="admin_featured_action"),
    path("tools/blog/new/", views.admin_blog_save, name="admin_blog_create"),
    path("tools/blog/<int:post_id>/", views.admin_blog_save, name="admin_blog_save"),
    path("tools/blog/<int:post_id>/delete/", views.admin_blog_delete, name="admin_blog_delete"),
    path("tools/sync-video-files/", views.admin_sync_video_files, name="admin_sync_video_files"),
]
