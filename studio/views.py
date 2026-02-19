"""
Views for the studio (creation) application.

The studio currently provides UI‑only pages for generating new assets
and listing the user’s own assets.  It reads from the same JSON
files used by the library to simulate published and unpublished
assets.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from django.conf import settings
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse


def _load_assets() -> List[Dict[str, Any]]:
    path = os.path.join(settings.BASE_DIR, 'data', 'assets.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def create(request: HttpRequest) -> HttpResponse:
    """Render the prompt‑based generation and product upload page."""
    return render(request, 'studio/create.html')


def my_assets(request: HttpRequest) -> HttpResponse:
    """Render the dashboard of the current user's generated assets."""
    # In lieu of authentication, assume the first creator in our JSON is the
    # current user.  In a real application, you would use request.user.
    assets = _load_assets()
    # Determine current user: pick owner of the first asset or default to None
    current_user = assets[0].get('owner') if assets else None
    draft_assets = [a for a in assets if a.get('owner') == current_user and not a.get('published', True)]
    published_assets = [a for a in assets if a.get('owner') == current_user and a.get('published', True)]
    context = {
        'current_user': current_user,
        'draft_assets': draft_assets,
        'published_assets': published_assets,
    }
    return render(request, 'studio/my_assets.html', context)