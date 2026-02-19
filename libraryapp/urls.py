"""
URL patterns for the library application.

The library index is available at ``/library/``.  Detail pages for
assets and creators are routed directly from the project’s ``urls.py``
to ensure clean top‑level URLs (e.g. ``/asset/1/`` and
``/creator/alice/``).
"""
from django.urls import path
from . import views


urlpatterns = [
    path('', views.library, name='library'),
]