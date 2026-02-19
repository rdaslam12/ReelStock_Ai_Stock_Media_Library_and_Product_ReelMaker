"""
Views for the library application.

These functions load asset and creator data from JSON files in the
``data/`` directory and supply them to templates for rendering.  The
library view implements simple search, category filtering and
pagination.  Asset and creator pages display associated metadata and
related items.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List

from django.conf import settings
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse


def _load_json(filename: str) -> List[Dict[str, Any]]:
    """Load a JSON file from the data directory and return its contents."""
    path = os.path.join(settings.BASE_DIR, 'data', filename)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _load_assets() -> List[Dict[str, Any]]:
    return _load_json('assets.json')


def _load_creators() -> List[Dict[str, Any]]:
    return _load_json('creators.json')


def library(request: HttpRequest) -> HttpResponse:
    """Display a grid of published assets with search and category filters."""
    assets = _load_assets()
    # Only include published assets in the public library
    assets = [a for a in assets if a.get('published', True)]
    # Extract optional query parameters
    category_param = request.GET.get('category', '')
    search_param = request.GET.get('search', '')
    # Filter by category if provided
    filtered = assets
    if category_param and category_param.lower() != 'all':
        filtered = [a for a in filtered if a.get('category', '').lower() == category_param.lower()]
    # Filter by search text in title or tags
    if search_param:
        term = search_param.lower()
        filtered = [
            a
            for a in filtered
            if term in a.get('title', '').lower()
            or any(term in tag.lower() for tag in a.get('tags', []))
        ]
    # Pagination
    page_size = 9
    try:
        page = max(int(request.GET.get('page', '1')), 1)
    except ValueError:
        page = 1
    total = len(filtered)
    total_pages = max(math.ceil(total / page_size), 1)
    start = (page - 1) * page_size
    end = start + page_size
    page_assets = filtered[start:end]
    # Unique categories for filter UI
    categories = sorted({a.get('category', 'Uncategorized') for a in assets})
    context = {
        'assets': page_assets,
        'all_assets': assets,
        'categories': categories,
        'current_category': category_param,
        'search_query': search_param,
        'page': page,
        'total_pages': total_pages,
        'page_range': list(range(1, total_pages + 1)),
    }
    return render(request, 'libraryapp/library.html', context)


def asset_detail(request: HttpRequest, asset_id: int) -> HttpResponse:
    """Display the details of a single asset."""
    assets = _load_assets()
    asset = next((a for a in assets if a.get('id') == asset_id), None)
    creators = _load_creators()
    creator = next((c for c in creators if c.get('username') == asset.get('owner')),
                   None) if asset else None
    # Other assets by the same creator (excluding current)
    other_assets = [a for a in assets if a.get('owner') == asset.get('owner') and a.get('id') != asset_id] if asset else []
    context = {
        'asset': asset,
        'creator': creator,
        'other_assets': other_assets,
    }
    return render(request, 'libraryapp/asset_detail.html', context)


def creator_profile(request: HttpRequest, username: str) -> HttpResponse:
    """Display a creator’s public profile and published assets."""
    assets = _load_assets()
    creators = _load_creators()
    creator = next((c for c in creators if c.get('username') == username), None)
    creator_assets = [a for a in assets if a.get('owner') == username]
    context = {
        'creator': creator,
        'assets': creator_assets,
    }
    return render(request, 'libraryapp/creator_profile.html', context)