from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from .models import UserProfile


class ProfileCompletionMiddleware:
    """Send first-time social-login users through one required profile step."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and not user.is_active and not request.path.startswith(reverse("account_restricted")):
            logout(request)
            return redirect("account_restricted")
        if user and user.is_authenticated and self._should_redirect(request):
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if profile.needs_profile_completion or not user.username:
                return redirect("complete_profile")
        return self.get_response(request)

    def _should_redirect(self, request):
        path = request.path
        complete_path = reverse("complete_profile")
        exempt_prefixes = (
            complete_path,
            reverse("logout"),
            "/accounts/",
            "/admin/",
            "/admin-panel/",
            "/static/",
            "/media/",
        )
        return not any(path.startswith(prefix) for prefix in exempt_prefixes)
