"""
Views for the core application.

This module defines simple function views for the home page and the
authentication pages.  The authentication pages are UI‑only; they
present forms but do not perform any authentication logic.
"""
from django.shortcuts import render


def home(request):
    """Render the home page."""
    return render(request, 'core/home.html')


def login_view(request):
    """Render the login page (UI only)."""
    return render(request, 'core/login.html')


def register_view(request):
    """Render the registration page (UI only)."""
    return render(request, 'core/register.html')