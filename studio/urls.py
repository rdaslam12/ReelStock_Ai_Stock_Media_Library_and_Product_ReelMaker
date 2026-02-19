"""
URL patterns for the studio application.

These patterns are not used directly in the project’s URL configuration
but demonstrate how the studio app might map its views.  The project
routes ``/create/`` and ``/my-assets/`` directly to the appropriate
views for cleaner URLs.
"""
from django.urls import path
from . import views


urlpatterns = [
    path('', views.create, name='create'),
    path('my-assets/', views.my_assets, name='my_assets'),
]