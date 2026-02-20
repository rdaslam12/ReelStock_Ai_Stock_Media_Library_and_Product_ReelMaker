"""
URL patterns for the moderation application.

The moderation dashboard is available at ``/moderation/``.
"""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.admin_dashboard, name="admin_dashboard"),
    path("login/", views.admin_login, name="admin_login"),
    path("assets/", views.admin_assets, name="admin_assets"),
    path("reports/", views.admin_reports, name="admin_reports"),
    path("mock-login/", views.mock_login, name="mock_login"),
    path("mock-logout/", views.mock_logout, name="mock_logout"),
    path("account/", views.account_page, name="account"),

]
