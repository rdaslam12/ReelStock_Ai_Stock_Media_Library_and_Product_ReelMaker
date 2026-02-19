"""
URL configuration for ReelStock.

The ``urlpatterns`` list routes URLs to views.  For more information please
see:
    https://docs.djangoproject.com/en/stable/topics/http/urls/

Examples:
Function views
    1. Import the view: ``from core import views``
    2. Add a URL to ``urlpatterns``: ``path('', views.home, name='home')``
Class-based views
    1. Import the view: ``from other_app.views import Home``
    2. Add a URL to ``urlpatterns``: ``path('', Home.as_view(), name='home')``
Including another URLconf
    1. Import the include() function: ``from django.urls import include, path``
    2. Add a URL to ``urlpatterns``: ``path('blog/', include('blog.urls'))``
"""
from django.contrib import admin
from django.urls import path, include

from libraryapp import views as library_views
from studio import views as studio_views


urlpatterns = [
    # Admin site (not customized for the MVP)
    path('admin/', admin.site.urls),
    # Core pages
    path('', include('core.urls')),
    # Library browsing
    path('library/', include('libraryapp.urls')),
    # Standalone routes for asset and creator detail pages to match the
    # specification (e.g. /asset/1/ and /creator/alice/)
    path('asset/<int:asset_id>/', library_views.asset_detail, name='asset_detail'),
    path('creator/<str:username>/', library_views.creator_profile, name='creator_profile'),
    # Studio (creation and my assets)
    path('create/', studio_views.create, name='create'),
    path('my-assets/', studio_views.my_assets, name='my_assets'),
    # Moderation dashboard
    path('admin-panel/', include('moderation.urls')),

]