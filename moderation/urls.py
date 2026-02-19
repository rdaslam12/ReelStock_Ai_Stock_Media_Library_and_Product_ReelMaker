"""
URL patterns for the moderation application.

The moderation dashboard is available at ``/moderation/``.
"""
from django.urls import path
from . import views


urlpatterns = [
    path('', views.dashboard, name='moderation_dashboard'),
]