from django.urls import path
from . import views

urlpatterns = [
    path('', views.library, name='library'),
    path('asset/<str:asset_type>/<int:asset_id>/', views.asset_detail, name='asset_detail'),
    path('creator/<str:username>/', views.creator_profile, name='creator_profile'),
    path('api/rate/', views.rate_asset, name='rate_asset'),
    path('api/comment/', views.post_comment, name='post_comment'),
    path('api/comment/<int:comment_id>/delete/', views.delete_comment, name='delete_comment'),
    path('api/reaction/', views.toggle_reaction, name='toggle_reaction'),
    path('api/follow/', views.toggle_follow, name='toggle_follow'),
    path('feed/', views.following_feed, name='following_feed'),
    path('api/bookmark/', views.toggle_bookmark, name='toggle_bookmark'),
    path('bookmarks/', views.my_bookmarks, name='my_bookmarks'),
    path('collections/', views.my_collections, name='my_collections'),
    path('collections/<int:collection_id>/', views.collection_detail, name='collection_detail'),
    path('api/collection/create/', views.create_collection, name='create_collection'),
    path('api/collection/add/', views.add_to_collection, name='add_to_collection'),
    path('api/collection/<int:collection_id>/delete/', views.delete_collection, name='delete_collection'),
    path('api/collection/item/<int:item_id>/remove/', views.remove_from_collection, name='remove_from_collection'),
    path('trending/', views.trending, name='trending'),
    path('notifications/', views.notifications_page, name='notifications'),
    path('api/notifications/count/', views.notifications_count, name='notifications_count'),
]
