from functools import wraps

from django.contrib.auth import authenticate
from django.contrib.auth.models import AnonymousUser, User
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


ADMIN_SESSION_USER_ID = "_custom_admin_user_id"
ADMIN_SESSION_AUTH_HASH = "_custom_admin_auth_hash"


def is_admin_user(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_staff or user.is_superuser)
    )


def authenticate_admin(request, identifier, password):
    identifier = (identifier or "").strip()
    password = password or ""
    if not identifier or not password:
        return None

    username = identifier
    if "@" in identifier:
        for candidate in User.objects.filter(email__iexact=identifier).order_by("id"):
            user = authenticate(request, username=candidate.username, password=password)
            if is_admin_user(user):
                return user
        return None

    user = authenticate(request, username=username, password=password)
    return user if is_admin_user(user) else None


def get_admin_user_from_session(request):
    admin_session = getattr(request, "admin_session", None)
    if admin_session is None:
        return AnonymousUser()

    user_id = admin_session.get(ADMIN_SESSION_USER_ID)
    auth_hash = admin_session.get(ADMIN_SESSION_AUTH_HASH)
    if not user_id or not auth_hash:
        return AnonymousUser()

    try:
        user = User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        admin_session.flush()
        return AnonymousUser()

    if not is_admin_user(user) or user.get_session_auth_hash() != auth_hash:
        admin_session.flush()
        return AnonymousUser()

    return user


def admin_login_session(request, user):
    request.admin_session.flush()
    request.admin_session[ADMIN_SESSION_USER_ID] = str(user.pk)
    request.admin_session[ADMIN_SESSION_AUTH_HASH] = user.get_session_auth_hash()
    request.admin_session.modified = True
    request.admin_user = user


def admin_logout_session(request):
    if hasattr(request, "admin_session"):
        request.admin_session.flush()
    request.admin_user = AnonymousUser()


def safe_admin_redirect(request, fallback="admin_dashboard"):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse(fallback)


def admin_login_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if is_admin_user(getattr(request, "admin_user", None)):
            return view_func(request, *args, **kwargs)
        login_url = reverse("admin_login")
        return redirect(f"{login_url}?next={request.get_full_path()}")

    return _wrapped


def superuser_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        admin_user = getattr(request, "admin_user", None)
        if is_admin_user(admin_user) and admin_user.is_superuser:
            return view_func(request, *args, **kwargs)
        return redirect("admin_dashboard")

    return _wrapped
