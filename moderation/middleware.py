import time
from importlib import import_module

from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date

from .admin_auth import get_admin_user_from_session


class AdminSessionMiddleware:
    """
    Separate session middleware for the custom admin frontend.

    This intentionally does not touch request.user or Django's normal session
    cookie. Admin views read request.admin_user from a second cookie scoped to
    /admin-panel/, so public-site login and custom-admin login remain isolated.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        engine = import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore
        self.cookie_name = getattr(
            settings,
            "CUSTOM_ADMIN_SESSION_COOKIE_NAME",
            "reelstock_admin_sessionid",
        )
        self.cookie_path = getattr(
            settings,
            "CUSTOM_ADMIN_SESSION_COOKIE_PATH",
            "/admin-panel/",
        )

    def __call__(self, request):
        if not request.path.startswith(self.cookie_path):
            return self.get_response(request)

        session_key = request.COOKIES.get(self.cookie_name)
        request.admin_session = self.SessionStore(session_key)
        request.admin_user = get_admin_user_from_session(request)

        response = self.get_response(request)
        try:
            accessed = request.admin_session.accessed
            modified = request.admin_session.modified
            empty = request.admin_session.is_empty()
        except AttributeError:
            return response

        if accessed:
            patch_vary_headers(response, ("Cookie",))

        if self.cookie_name in request.COOKIES and empty:
            response.delete_cookie(
                self.cookie_name,
                path=self.cookie_path,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            patch_vary_headers(response, ("Cookie",))
        elif modified and not empty:
            if response.status_code < 500:
                try:
                    request.admin_session.save()
                except UpdateError:
                    return response

                max_age = settings.SESSION_COOKIE_AGE
                expires = http_date(time.time() + max_age)
                response.set_cookie(
                    self.cookie_name,
                    request.admin_session.session_key,
                    max_age=max_age,
                    expires=expires,
                    path=self.cookie_path,
                    domain=settings.SESSION_COOKIE_DOMAIN,
                    secure=settings.SESSION_COOKIE_SECURE,
                    httponly=True,
                    samesite=settings.SESSION_COOKIE_SAMESITE,
                )

        return response
