"""
URL patterns for the core application.

This module routes the root path to the home view and exposes the
login and register pages.  It is included at the project root in
``reelstock/urls.py``.
"""
from django.urls import path
from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
]