"""
ASGI config for ReelStock project.

This module exposes the ASGI callable as a module‑level variable named
``application`` so that it can be discovered by ASGI servers.  It is
similar to the WSGI configuration but for asynchronous servers.  See
Django’s deployment documentation for more details【140022745920203†L163-L167】.
"""

import os

from django.core.asgi import get_asgi_application

# Set default settings module for ASGI
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reelstock.settings")

application = get_asgi_application()