"""
Views for the moderation application.

The moderation dashboard displays all assets and reports using mock data.
Administrators can imagine approving or removing assets, or banning users,
but no actions are performed in this phase.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from django.conf import settings
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse


def _load_json(filename: str) -> List[Dict[str, Any]]:
    path = os.path.join(settings.BASE_DIR, 'data', filename)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def dashboard(request: HttpRequest) -> HttpResponse:
    """Render the moderation dashboard with assets and reports."""
    assets = _load_json('assets.json')
    reports = _load_json('reports.json')
    context = {
        'assets': assets,
        'reports': reports,
    }
    return render(request, 'moderation/dashboard.html', context)