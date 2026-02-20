"""
Views for the moderation application.

The moderation dashboard displays all assets and reports using mock data.
Administrators can imagine approving or removing assets, or banning users,
but no actions are performed in this phase.
"""
import json
import os
from django.conf import settings
from django.shortcuts import render
from django.shortcuts import redirect

def _load_json(filename):
    path = os.path.join(settings.BASE_DIR, "data", filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def admin_dashboard(request):
    assets = _load_json("assets.json")
    reports = _load_json("reports.json")
    return render(request, "moderation/dashboard.html", {"assets": assets, "reports": reports})

def admin_login(request):
    return render(request, "moderation/admin_login.html")
def admin_assets(request):
    assets = _load_json("assets.json")
    return render(request, "moderation/admin_assets.html", {"assets": assets})
def admin_reports(request):
    reports = _load_json("reports.json")
    assets = _load_json("assets.json")
    return render(request, "moderation/admin_reports.html", {"reports": reports, "assets": assets})


def mock_login(request):
    # UI-only login: set session flags
    request.session["is_logged_in"] = True
    request.session["username"] = "Towhid"  # demo name (change anything)
    return redirect("library")  # after login go to Library

def mock_logout(request):
    request.session["is_logged_in"] = False
    request.session.pop("username", None)
    return redirect("home")  # after logout go to Home (change to "library" if you want)
def account_page(request):
    return render(request, "core/account.html")

