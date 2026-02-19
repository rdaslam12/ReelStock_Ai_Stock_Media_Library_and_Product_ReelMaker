"""
WSGI config for ReelStock project.

This module exposes the WSGI callable as a module‑level variable named
``application``.  Django’s built‑in development server and most
production servers use this file to serve the project’s WSGI
application【140022745920203†L163-L167】.
"""

import os

from django.core.wsgi import get_wsgi_application

# Set default settings module for WSGI
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reelstock.settings")

application = get_wsgi_application()