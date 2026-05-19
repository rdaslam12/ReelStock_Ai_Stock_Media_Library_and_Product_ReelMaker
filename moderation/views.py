"""
Custom in-app admin frontend.

The views in this module deliberately use request.admin_user, which is populated
from a separate admin-only session cookie. They do not call django.contrib.auth
login/logout and therefore do not sign users into the public website.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from core.models import (
    AssetComment,
    AssetRating,
    AssetView,
    BlogPost,
    Bookmark,
    Collection,
    CollectionItem,
    FeaturedAsset,
    Follow,
    GeneratedImage,
    GeneratedVideo,
    Notification,
    UserProfile,
)
from wallet.models import BasketItem, CoinRequest, Transaction, Wallet

from .admin_auth import (
    admin_login_required,
    admin_login_session,
    admin_logout_session,
    authenticate_admin,
    is_admin_user,
    safe_admin_redirect,
)
from .models import AdminActionLog, TrendingOverride
from .services import (
    admin_email_body,
    delete_asset_and_storage,
    record_admin_action,
    require_note,
    unpublish_user_assets,
)


def _flash(request, message, level="success"):
    request.admin_session["_admin_flash"] = {"message": message, "level": level}
    request.admin_session.modified = True


def _base_context(request, **extra):
    flash = None
    if hasattr(request, "admin_session"):
        flash = request.admin_session.pop("_admin_flash", None)
        if flash:
            request.admin_session.modified = True
    context = {"admin_user": getattr(request, "admin_user", None), "admin_flash": flash}
    context.update(extra)
    return context


def _paginate(request, items, per_page=25):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get("page"))


def _get_or_create_wallet(user):
    wallet, created = Wallet.objects.get_or_create(
        user=user,
        defaults={"balance": Wallet.SIGNUP_BONUS},
    )
    if created:
        Transaction.objects.create(
            wallet=wallet,
            kind=Transaction.KIND_SIGNUP,
            delta=Wallet.SIGNUP_BONUS,
            balance_after=wallet.balance,
            note="Welcome bonus.",
        )
    return wallet


def _asset_model(asset_type):
    return GeneratedVideo if asset_type == "video" else GeneratedImage


def _get_asset(asset_type, asset_id):
    if asset_type not in ("image", "video"):
        raise GeneratedImage.DoesNotExist
    return get_object_or_404(
        _asset_model(asset_type).objects.select_related("user"),
        pk=asset_id,
    )


def _asset_title(asset):
    return asset.display_title() if callable(asset.display_title) else asset.display_title


def _asset_rows(images, videos):
    rows = []
    for image in images:
        rows.append(
            {
                "type": "image",
                "obj": image,
                "title": _asset_title(image),
                "owner": image.user,
                "status": "Published" if image.is_published else "Draft",
                "published": image.is_published,
                "price": image.coin_price,
                "thumb": image.media_url,
                "created_at": image.created_at,
            }
        )
    for video in videos:
        rows.append(
            {
                "type": "video",
                "obj": video,
                "title": _asset_title(video),
                "owner": video.user,
                "status": video.status.title(),
                "published": video.is_published,
                "price": video.coin_price,
                "thumb": video.source_media_url or video.playback_url,
                "created_at": video.created_at,
            }
        )
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


def _filter_assets(request):
    asset_type = request.GET.get("type", "all")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    owner = request.GET.get("owner", "").strip()
    category = request.GET.get("category", "").strip()
    style = request.GET.get("style", "").strip()

    images = GeneratedImage.objects.select_related("user").all()
    videos = GeneratedVideo.objects.select_related("user").all()

    if q:
        images = images.filter(
            Q(title__icontains=q)
            | Q(prompt__icontains=q)
            | Q(user__username__icontains=q)
            | Q(user__email__icontains=q)
        )
        videos = videos.filter(
            Q(title__icontains=q)
            | Q(product_name__icontains=q)
            | Q(category__icontains=q)
            | Q(user__username__icontains=q)
            | Q(user__email__icontains=q)
            | Q(error_message__icontains=q)
        )
    if owner:
        images = images.filter(Q(user__username__icontains=owner) | Q(user__email__icontains=owner))
        videos = videos.filter(Q(user__username__icontains=owner) | Q(user__email__icontains=owner))
    if category:
        videos = videos.filter(category__icontains=category)
        images = images.none()
    if style:
        images = images.filter(style__icontains=style)
        videos = videos.filter(video_style__icontains=style)
    if status == "published":
        images = images.filter(is_published=True)
        videos = videos.filter(is_published=True)
    elif status == "draft":
        images = images.filter(is_published=False)
        videos = videos.filter(is_published=False)
    elif status in dict(GeneratedVideo.STATUS_CHOICES):
        images = images.none()
        videos = videos.filter(status=status)

    if asset_type == "image":
        videos = videos.none()
    elif asset_type == "video":
        images = images.none()

    return images, videos


def _computed_trending_rows(asset_type, limit=10):
    since = timezone.now() - timedelta(days=7)
    ratings = {
        row["asset_id"]: row
        for row in AssetRating.objects.filter(asset_type=asset_type, created_at__gte=since)
        .values("asset_id")
        .annotate(avg=Avg("score"), cnt=Count("id"))
    }
    comments = {
        row["asset_id"]: row["cnt"]
        for row in AssetComment.objects.filter(asset_type=asset_type, created_at__gte=since)
        .values("asset_id")
        .annotate(cnt=Count("id"))
    }
    views = {
        row["asset_id"]: row["cnt"]
        for row in AssetView.objects.filter(asset_type=asset_type, viewed_at__gte=since)
        .values("asset_id")
        .annotate(cnt=Count("id"))
    }
    asset_ids = set(ratings) | set(comments) | set(views)
    scored = []
    for asset_id in asset_ids:
        rating = ratings.get(asset_id, {})
        score = (
            (views.get(asset_id, 0) * 1.0)
            + (comments.get(asset_id, 0) * 1.8)
            + ((rating.get("avg") or 0) * (rating.get("cnt") or 0) * 1.25)
        )
        scored.append((score, asset_id))
    scored.sort(reverse=True)

    if asset_type == "image":
        objects = {
            obj.pk: obj
            for obj in GeneratedImage.objects.filter(pk__in=[pk for _, pk in scored], is_published=True)
            .select_related("user")
        }
    else:
        objects = {
            obj.pk: obj
            for obj in GeneratedVideo.objects.filter(
                pk__in=[pk for _, pk in scored],
                is_published=True,
                status=GeneratedVideo.STATUS_DONE,
            ).select_related("user")
        }

    rows = []
    for score, asset_id in scored:
        asset = objects.get(asset_id)
        if asset:
            rows.append({
                "asset": asset,
                "asset_type": asset_type,
                "score": round(score, 2),
                "views": views.get(asset_id, 0),
                "comments": comments.get(asset_id, 0),
                "rating_count": (ratings.get(asset_id, {}) or {}).get("cnt", 0),
            })
        if len(rows) >= limit:
            break
    return rows


@ensure_csrf_cookie
def admin_login(request):
    if is_admin_user(getattr(request, "admin_user", None)):
        return redirect(safe_admin_redirect(request))

    error = ""
    if request.method == "POST":
        user = authenticate_admin(
            request,
            request.POST.get("identifier"),
            request.POST.get("password"),
        )
        if user:
            admin_login_session(request, user)
            return redirect(safe_admin_redirect(request))
        error = "Use a valid staff or superuser account."

    return render(
        request,
        "moderation/admin_login.html",
        {"error": error, "next": request.GET.get("next", "")},
    )


def admin_logout(request):
    admin_logout_session(request)
    return redirect("admin_login")


@admin_login_required
def admin_dashboard(request):
    week_ago = timezone.now() - timedelta(days=7)
    download_txns = Transaction.objects.filter(kind=Transaction.KIND_DOWNLOAD)
    download_coins = -sum(txn.delta for txn in download_txns.only("delta"))

    recent_images = GeneratedImage.objects.select_related("user").order_by("-created_at")[:5]
    recent_videos = GeneratedVideo.objects.select_related("user").order_by("-created_at")[:5]

    stats = {
        "total_users": User.objects.count(),
        "new_users_7d": User.objects.filter(date_joined__gte=week_ago).count(),
        "published_images": GeneratedImage.objects.filter(is_published=True).count(),
        "published_videos": GeneratedVideo.objects.filter(
            is_published=True,
            status=GeneratedVideo.STATUS_DONE,
        ).count(),
        "generated_reels": GeneratedVideo.objects.count(),
        "failed_reels": GeneratedVideo.objects.filter(status=GeneratedVideo.STATUS_FAILED).count(),
        "wallets": Wallet.objects.count(),
        "coin_balance": Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0,
        "transactions": Transaction.objects.count(),
        "downloads": download_txns.count(),
        "download_coins": download_coins,
        "pending_coin_requests": CoinRequest.objects.filter(
            status=CoinRequest.STATUS_PENDING,
        ).count(),
        "reports": AdminActionLog.objects.filter(
            action__in=[
                AdminActionLog.ACTION_ASSET_DELETED,
                AdminActionLog.ACTION_ASSET_UNPUBLISHED,
                AdminActionLog.ACTION_ASSET_MODERATED,
            ]
        ).count(),
    }

    return render(
        request,
        "moderation/dashboard.html",
        _base_context(
            request,
            stats=stats,
            recent_assets=_asset_rows(recent_images, recent_videos)[:8],
            recent_users=User.objects.order_by("-date_joined")[:8],
            recent_transactions=Transaction.objects.select_related("wallet__user")[:8],
            pending_requests=CoinRequest.objects.select_related("user").filter(
                status=CoinRequest.STATUS_PENDING,
            )[:5],
        ),
    )


@admin_login_required
def admin_users(request):
    users = (
        User.objects.select_related("profile", "wallet")
        .annotate(
            image_count=Count("images", distinct=True),
            video_count=Count("videos", distinct=True),
            collection_count=Count("collections", distinct=True),
            wallet_balance=F("wallet__balance"),
        )
        .order_by("-date_joined")
    )
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "").strip()
    status = request.GET.get("status", "").strip()

    if q:
        users = users.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
    if role == "superuser":
        users = users.filter(is_superuser=True)
    elif role == "staff":
        users = users.filter(is_staff=True, is_superuser=False)
    elif role == "customer":
        users = users.filter(is_staff=False, is_superuser=False)
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)

    return render(
        request,
        "moderation/admin_users.html",
        _base_context(request, users=_paginate(request, users), filters=request.GET),
    )


@admin_login_required
@ensure_csrf_cookie
def admin_user_detail(request, user_id):
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    wallet = _get_or_create_wallet(user)
    return render(
        request,
        "moderation/admin_user_detail.html",
        _base_context(
            request,
            managed_user=user,
            wallet=wallet,
            transactions=wallet.transactions.all()[:20],
            coin_requests=CoinRequest.objects.filter(user=user)[:10],
            images=GeneratedImage.objects.filter(user=user)[:12],
            videos=GeneratedVideo.objects.filter(user=user)[:12],
            basket_items=BasketItem.objects.filter(user=user).select_related("image", "video")[:20],
            collections=Collection.objects.filter(user=user).annotate(item_count=Count("items"))[:20],
            bookmarks=Bookmark.objects.filter(user=user)[:20],
            admin_logs=AdminActionLog.objects.filter(target_user=user).select_related("admin")[:12],
        ),
    )


@admin_login_required
@require_POST
def admin_user_action(request, user_id, action):
    target = get_object_or_404(User, pk=user_id)
    admin_user = request.admin_user
    note, error = require_note(request, "account moderation")
    if error:
        _flash(request, error, "danger")
        return redirect("admin_user_detail", user_id=target.pk)

    if action == "toggle-active":
        if target.pk == admin_user.pk:
            _flash(request, "You cannot deactivate your own admin account.", "danger")
        elif target.is_superuser and not admin_user.is_superuser:
            _flash(request, "Only a superuser can deactivate another superuser.", "danger")
        else:
            was_active = target.is_active
            published_images = GeneratedImage.objects.filter(user=target, is_published=True).count()
            published_videos = GeneratedVideo.objects.filter(user=target, is_published=True).count()
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            if was_active and not target.is_active:
                unpublish_user_assets(target)
                message = "Your ReelStock account has been deactivated. Your published creations were unpublished."
                record_admin_action(
                    admin=admin_user,
                    target_user=target,
                    action=AdminActionLog.ACTION_USER_DEACTIVATED,
                    note=note,
                    object_label=target.username,
                    metadata={"unpublished_images": published_images, "unpublished_videos": published_videos},
                    notification_message=message,
                    email_subject="Your ReelStock account was deactivated",
                    email_body=admin_email_body(target, message, note),
                )
            else:
                message = "Your ReelStock account has been reactivated."
                record_admin_action(
                    admin=admin_user,
                    target_user=target,
                    action=AdminActionLog.ACTION_USER_REACTIVATED,
                    note=note,
                    object_label=target.username,
                    notification_message=message,
                    email_subject="Your ReelStock account was reactivated",
                    email_body=admin_email_body(target, message, note),
                )
            _flash(request, f"{target.username} is now {'active' if target.is_active else 'inactive'}.")
    elif action == "toggle-staff":
        if not admin_user.is_superuser:
            _flash(request, "Only superusers can change staff access.", "danger")
        elif target.pk == admin_user.pk:
            _flash(request, "You cannot remove your own staff access.", "danger")
        else:
            target.is_staff = not target.is_staff
            target.save(update_fields=["is_staff"])
            action_name = AdminActionLog.ACTION_STAFF_GRANTED if target.is_staff else AdminActionLog.ACTION_STAFF_REVOKED
            message = f"Your ReelStock staff access was {'granted' if target.is_staff else 'revoked'}."
            record_admin_action(
                admin=admin_user,
                target_user=target,
                action=action_name,
                note=note,
                object_label=target.username,
                notification_message=message,
                email_subject="Your ReelStock staff access changed",
                email_body=admin_email_body(target, message, note),
            )
            _flash(request, f"Staff access updated for {target.username}.")
    elif action == "toggle-superuser":
        if not admin_user.is_superuser:
            _flash(request, "Only superusers can change superuser access.", "danger")
        elif target.pk == admin_user.pk:
            _flash(request, "You cannot change your own superuser flag here.", "danger")
        else:
            target.is_superuser = not target.is_superuser
            if target.is_superuser:
                target.is_staff = True
            target.save(update_fields=["is_superuser", "is_staff"])
            action_name = AdminActionLog.ACTION_SUPERUSER_GRANTED if target.is_superuser else AdminActionLog.ACTION_SUPERUSER_REVOKED
            message = f"Your ReelStock superuser access was {'granted' if target.is_superuser else 'revoked'}."
            record_admin_action(
                admin=admin_user,
                target_user=target,
                action=action_name,
                note=note,
                object_label=target.username,
                notification_message=message,
                email_subject="Your ReelStock superuser access changed",
                email_body=admin_email_body(target, message, note),
            )
            _flash(request, f"Superuser access updated for {target.username}.")
    else:
        _flash(request, "Unknown user action.", "danger")

    return redirect("admin_user_detail", user_id=target.pk)


@admin_login_required
@require_POST
def admin_user_adjust_wallet(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    wallet = _get_or_create_wallet(target)
    note, error = require_note(request, "wallet adjustments")
    if error:
        _flash(request, error, "danger")
        return redirect("admin_user_detail", user_id=target.pk)
    try:
        amount = int(request.POST.get("amount", "0"))
    except (TypeError, ValueError):
        amount = 0

    try:
        if amount > 0:
            wallet.credit(amount, Transaction.KIND_ADJUST, note=note)
            message = f"{amount} RC was added to your ReelStock wallet."
            record_admin_action(
                admin=request.admin_user,
                target_user=target,
                action=AdminActionLog.ACTION_COINS_ADDED,
                note=note,
                object_label=f"{amount} RC",
                metadata={"amount": amount, "balance_after": wallet.balance},
                notification_message=message,
                email_subject="ReelStock wallet credited",
                email_body=admin_email_body(target, message, note),
            )
            _flash(request, f"Added {amount} RC to {target.username}.")
        elif amount < 0:
            wallet.debit(abs(amount), Transaction.KIND_ADJUST, note=note)
            message = f"{abs(amount)} RC was removed from your ReelStock wallet."
            record_admin_action(
                admin=request.admin_user,
                target_user=target,
                action=AdminActionLog.ACTION_COINS_REMOVED,
                note=note,
                object_label=f"{abs(amount)} RC",
                metadata={"amount": amount, "balance_after": wallet.balance},
                notification_message=message,
                email_subject="ReelStock wallet adjusted",
                email_body=admin_email_body(target, message, note),
            )
            _flash(request, f"Removed {abs(amount)} RC from {target.username}.")
        else:
            _flash(request, "Enter a non-zero coin amount.", "warning")
    except ValueError as exc:
        _flash(request, str(exc), "danger")

    return redirect("admin_user_detail", user_id=target.pk)


@admin_login_required
def admin_assets(request):
    images, videos = _filter_assets(request)
    rows = _asset_rows(images, videos)
    return render(
        request,
        "moderation/admin_assets.html",
        _base_context(
            request,
            assets=_paginate(request, rows, per_page=30),
            filters=request.GET,
            image_count=GeneratedImage.objects.count(),
            video_count=GeneratedVideo.objects.count(),
        ),
    )


@admin_login_required
@ensure_csrf_cookie
def admin_asset_detail(request, asset_type, asset_id):
    asset = _get_asset(asset_type, asset_id)
    rating_qs = AssetRating.objects.filter(asset_type=asset_type, asset_id=asset.pk)
    return render(
        request,
        "moderation/admin_asset_detail.html",
        _base_context(
            request,
            asset=asset,
            asset_type=asset_type,
            owner=asset.user,
            avg_rating=rating_qs.aggregate(avg=Avg("score"))["avg"] or 0,
            rating_count=rating_qs.count(),
            view_count=AssetView.objects.filter(asset_type=asset_type, asset_id=asset.pk).count(),
            comment_count=AssetComment.objects.filter(asset_type=asset_type, asset_id=asset.pk).count(),
            bookmark_count=Bookmark.objects.filter(asset_type=asset_type, asset_id=asset.pk).count(),
            collection_count=CollectionItem.objects.filter(asset_type=asset_type, asset_id=asset.pk).count(),
            admin_logs=AdminActionLog.objects.filter(asset_type=asset_type, asset_id=asset.pk).select_related("admin")[:12],
        ),
    )


@admin_login_required
@require_POST
def admin_asset_update(request, asset_type, asset_id):
    asset = _get_asset(asset_type, asset_id)
    try:
        coin_price = max(0, int(request.POST.get("coin_price", asset.coin_price)))
    except (TypeError, ValueError):
        coin_price = asset.coin_price

    asset.title = (request.POST.get("title") or "").strip()
    asset.coin_price = coin_price
    update_fields = ["title", "coin_price"]

    if asset_type == "image":
        asset.style = (request.POST.get("style") or "").strip()
        update_fields.append("style")
    else:
        requested_status = request.POST.get("status") or asset.status
        if requested_status in dict(GeneratedVideo.STATUS_CHOICES):
            asset.status = requested_status
        asset.category = (request.POST.get("category") or "").strip()
        asset.product_name = (request.POST.get("product_name") or "").strip()
        asset.video_style = (request.POST.get("video_style") or "").strip()
        update_fields.extend(["status", "category", "product_name", "video_style", "updated_at"])

    asset.save(update_fields=update_fields)
    _flash(request, "Asset updated.")
    return redirect("admin_asset_detail", asset_type=asset_type, asset_id=asset.pk)


@admin_login_required
@require_POST
def admin_asset_action(request, asset_type, asset_id, action):
    asset = _get_asset(asset_type, asset_id)
    note = ""
    if action in {"unpublish", "delete", "mark-failed"}:
        note, error = require_note(request, action.replace("-", " "))
        if error:
            _flash(request, error, "danger")
            return redirect("admin_asset_detail", asset_type=asset_type, asset_id=asset.pk)

    if action == "publish":
        asset.is_published = True
        asset.save(update_fields=["is_published"])
        record_admin_action(
            admin=request.admin_user,
            target_user=asset.user,
            action=AdminActionLog.ACTION_CONTENT_UPDATED,
            note=f"Published {asset_type} '{_asset_title(asset)}'.",
            object_label=_asset_title(asset),
            asset_type=asset_type,
            asset_id=asset.pk,
            notify=False,
            email=False,
        )
        _flash(request, "Asset published.")
    elif action == "unpublish":
        asset.is_published = False
        asset.save(update_fields=["is_published"])
        title = _asset_title(asset)
        message = f"Your {asset_type} '{title}' was unpublished by the ReelStock admin team."
        record_admin_action(
            admin=request.admin_user,
            target_user=asset.user,
            action=AdminActionLog.ACTION_ASSET_UNPUBLISHED,
            note=note,
            object_label=title,
            asset_type=asset_type,
            asset_id=asset.pk,
            notification_message=message,
            email_subject="Your ReelStock asset was unpublished",
            email_body=admin_email_body(asset.user, message, note),
        )
        _flash(request, "Asset unpublished.")
    elif action == "mark-done" and asset_type == "video":
        asset.status = GeneratedVideo.STATUS_DONE
        asset.save(update_fields=["status", "updated_at"])
        record_admin_action(
            admin=request.admin_user,
            target_user=asset.user,
            action=AdminActionLog.ACTION_CONTENT_UPDATED,
            note=f"Marked reel '{_asset_title(asset)}' as done.",
            object_label=_asset_title(asset),
            asset_type=asset_type,
            asset_id=asset.pk,
            notify=False,
            email=False,
        )
        _flash(request, "Reel marked as done.")
    elif action == "mark-failed" and asset_type == "video":
        asset.status = GeneratedVideo.STATUS_FAILED
        asset.is_published = False
        asset.save(update_fields=["status", "is_published", "updated_at"])
        title = _asset_title(asset)
        message = f"Your reel '{title}' was marked failed and unpublished by the ReelStock admin team."
        record_admin_action(
            admin=request.admin_user,
            target_user=asset.user,
            action=AdminActionLog.ACTION_ASSET_MODERATED,
            note=note,
            object_label=title,
            asset_type=asset_type,
            asset_id=asset.pk,
            notification_message=message,
            email_subject="Your ReelStock reel was moderated",
            email_body=admin_email_body(asset.user, message, note),
        )
        _flash(request, "Reel marked as failed.", "warning")
    elif action == "delete":
        title = _asset_title(asset)
        owner = asset.user
        cleanup = delete_asset_and_storage(asset_type, asset)
        message = f"Your {asset_type} '{title}' was removed from ReelStock by the admin team."
        record_admin_action(
            admin=request.admin_user,
            target_user=owner,
            action=AdminActionLog.ACTION_ASSET_DELETED,
            note=note,
            object_label=title,
            asset_type=asset_type,
            asset_id=asset_id,
            metadata=cleanup,
            notification_message=message,
            email_subject="Your ReelStock asset was removed",
            email_body=admin_email_body(owner, message, note),
        )
        files_deleted = len(cleanup.get("deleted_files", []))
        _flash(request, f"Deleted {asset_type} '{title}' and removed {files_deleted} stored file(s).", "warning")
        return redirect("admin_assets")
    else:
        _flash(request, "Unknown asset action.", "danger")
    return redirect("admin_asset_detail", asset_type=asset_type, asset_id=asset.pk)


@admin_login_required
def admin_reels(request):
    reels = GeneratedVideo.objects.select_related("user").order_by("-created_at")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    published = request.GET.get("published", "").strip()
    if q:
        reels = reels.filter(
            Q(title__icontains=q)
            | Q(product_name__icontains=q)
            | Q(category__icontains=q)
            | Q(user__username__icontains=q)
            | Q(request_id__icontains=q)
            | Q(error_message__icontains=q)
        )
    if status in dict(GeneratedVideo.STATUS_CHOICES):
        reels = reels.filter(status=status)
    if published == "yes":
        reels = reels.filter(is_published=True)
    elif published == "no":
        reels = reels.filter(is_published=False)

    status_counts = {
        row["status"]: row["count"]
        for row in GeneratedVideo.objects.values("status").annotate(count=Count("id"))
    }
    return render(
        request,
        "moderation/admin_reels.html",
        _base_context(
            request,
            reels=_paginate(request, reels, per_page=25),
            status_counts=status_counts,
            filters=request.GET,
            status_choices=GeneratedVideo.STATUS_CHOICES,
        ),
    )


@admin_login_required
@ensure_csrf_cookie
def admin_wallets(request):
    wallets = (
        Wallet.objects.select_related("user")
        .annotate(txn_count=Count("transactions"))
        .order_by("-updated_at")
    )
    q = request.GET.get("q", "").strip()
    if q:
        wallets = wallets.filter(Q(user__username__icontains=q) | Q(user__email__icontains=q))

    request_status = request.GET.get("request_status", "")
    coin_requests = CoinRequest.objects.select_related("user", "resolved_by")
    if request_status in dict(CoinRequest.STATUS_CHOICES):
        coin_requests = coin_requests.filter(status=request_status)

    return render(
        request,
        "moderation/admin_wallets.html",
        _base_context(
            request,
            wallets=_paginate(request, wallets, per_page=25),
            coin_requests=coin_requests[:30],
            transactions=Transaction.objects.select_related("wallet__user")[:40],
            filters=request.GET,
            total_balance=Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0,
        ),
    )


@admin_login_required
@require_POST
def admin_coin_request_action(request, request_id, action):
    coin_request = get_object_or_404(CoinRequest.objects.select_related("user"), pk=request_id)
    admin_note, error = require_note(request, "coin request decisions")
    if error:
        _flash(request, error, "danger")
        return redirect("admin_wallets")

    with db_transaction.atomic():
        coin_request = CoinRequest.objects.select_for_update().get(pk=coin_request.pk)
        if coin_request.status != CoinRequest.STATUS_PENDING:
            _flash(request, "That coin request has already been resolved.", "warning")
            return redirect("admin_wallets")

        coin_request.admin_note = admin_note
        coin_request.resolved_by = request.admin_user
        coin_request.resolved_at = timezone.now()
        if action == "approve":
            wallet = _get_or_create_wallet(coin_request.user)
            wallet.credit(
                coin_request.amount,
                Transaction.KIND_GRANT,
                note=admin_note or f"Coin request approved by {request.admin_user.username}.",
            )
            coin_request.status = CoinRequest.STATUS_APPROVED
            message = f"Your request for {coin_request.amount} RC was approved."
            record_admin_action(
                admin=request.admin_user,
                target_user=coin_request.user,
                action=AdminActionLog.ACTION_COIN_REQUEST_APPROVED,
                note=admin_note,
                object_label=f"CoinRequest #{coin_request.pk}",
                metadata={"amount": coin_request.amount, "balance_after": wallet.balance},
                notification_message=message,
                email_subject="Your ReelStock coin request was approved",
                email_body=admin_email_body(coin_request.user, message, admin_note),
            )
            _flash(request, f"Approved {coin_request.amount} RC for {coin_request.user.username}.")
        elif action == "reject":
            coin_request.status = CoinRequest.STATUS_REJECTED
            message = f"Your request for {coin_request.amount} RC was rejected."
            record_admin_action(
                admin=request.admin_user,
                target_user=coin_request.user,
                action=AdminActionLog.ACTION_COIN_REQUEST_REJECTED,
                note=admin_note,
                object_label=f"CoinRequest #{coin_request.pk}",
                metadata={"amount": coin_request.amount},
                notification_message=message,
                email_subject="Your ReelStock coin request was rejected",
                email_body=admin_email_body(coin_request.user, message, admin_note),
            )
            _flash(request, f"Rejected coin request from {coin_request.user.username}.", "warning")
        else:
            _flash(request, "Unknown coin request action.", "danger")
            return redirect("admin_wallets")

        coin_request.save(
            update_fields=["status", "admin_note", "resolved_by", "resolved_at"],
        )

    return redirect("admin_wallets")


@admin_login_required
def admin_engagement(request):
    manual_trending = TrendingOverride.objects.select_related(
        "image__user",
        "video__user",
    ).order_by("order", "-created_at")
    return render(
        request,
        "moderation/admin_engagement.html",
        _base_context(
            request,
            stats={
                "bookmarks": Bookmark.objects.count(),
                "collections": Collection.objects.count(),
                "collection_items": CollectionItem.objects.count(),
                "basket_items": BasketItem.objects.count(),
                "comments": AssetComment.objects.count(),
                "ratings": AssetRating.objects.count(),
                "follows": Follow.objects.count(),
                "notifications": Notification.objects.count(),
            },
            collections=Collection.objects.select_related("user").annotate(item_count=Count("items"))[:25],
            bookmarks=Bookmark.objects.select_related("user")[:25],
            basket_items=BasketItem.objects.select_related("user", "image", "video")[:25],
            comments=AssetComment.objects.select_related("user").order_by("-created_at")[:25],
            download_transactions=Transaction.objects.select_related("wallet__user").filter(
                kind=Transaction.KIND_DOWNLOAD,
            )[:25],
            manual_trending=manual_trending,
            computed_trending_images=_computed_trending_rows("image"),
            computed_trending_videos=_computed_trending_rows("video"),
        ),
    )


@admin_login_required
@require_POST
def admin_trending_action(request):
    action = request.POST.get("action")
    override_id = request.POST.get("override_id")

    if action == "add":
        asset_type = request.POST.get("asset_type")
        try:
            asset_id = int(request.POST.get("asset_id", "0"))
            order = int(request.POST.get("order", "0"))
        except (TypeError, ValueError):
            _flash(request, "Invalid trending asset.", "danger")
            return redirect("admin_engagement")

        note = (request.POST.get("note") or "").strip()
        if asset_type == "image":
            asset = get_object_or_404(GeneratedImage, pk=asset_id, is_published=True)
            override, _ = TrendingOverride.objects.update_or_create(
                asset_type="image",
                image=asset,
                defaults={"video": None, "order": order, "is_active": True, "note": note},
            )
        elif asset_type == "video":
            asset = get_object_or_404(
                GeneratedVideo,
                pk=asset_id,
                is_published=True,
                status=GeneratedVideo.STATUS_DONE,
            )
            override, _ = TrendingOverride.objects.update_or_create(
                asset_type="video",
                video=asset,
                defaults={"image": None, "order": order, "is_active": True, "note": note},
            )
        else:
            _flash(request, "Invalid trending asset type.", "danger")
            return redirect("admin_engagement")

        record_admin_action(
            admin=request.admin_user,
            action=AdminActionLog.ACTION_CONTENT_UPDATED,
            note=note or "Added asset to manual trending list.",
            object_label=f"Trending {asset_type} #{asset_id}",
            asset_type=asset_type,
            asset_id=asset_id,
            notify=False,
            email=False,
            metadata={"override_id": override.pk},
        )
        _flash(request, "Trending override saved.")
    elif action in {"toggle", "remove", "update"}:
        override = get_object_or_404(TrendingOverride, pk=override_id)
        if action == "toggle":
            override.is_active = not override.is_active
            override.save(update_fields=["is_active", "updated_at"])
            record_admin_action(
                admin=request.admin_user,
                action=AdminActionLog.ACTION_CONTENT_UPDATED,
                note=f"{'Activated' if override.is_active else 'Hidden'} trending override #{override.pk}.",
                object_label=f"Trending override #{override.pk}",
                notify=False,
                email=False,
            )
            _flash(request, "Trending override status updated.")
        elif action == "update":
            try:
                override.order = int(request.POST.get("order", override.order))
            except (TypeError, ValueError):
                pass
            override.note = (request.POST.get("note") or "").strip()
            override.save(update_fields=["order", "note", "updated_at"])
            record_admin_action(
                admin=request.admin_user,
                action=AdminActionLog.ACTION_CONTENT_UPDATED,
                note=f"Updated trending override #{override.pk}.",
                object_label=f"Trending override #{override.pk}",
                notify=False,
                email=False,
                metadata={"order": override.order, "note": override.note},
            )
            _flash(request, "Trending override updated.")
        else:
            label = f"Trending override #{override.pk}"
            override.delete()
            record_admin_action(
                admin=request.admin_user,
                action=AdminActionLog.ACTION_CONTENT_UPDATED,
                note=f"Removed {label}.",
                object_label=label,
                notify=False,
                email=False,
            )
            _flash(request, "Trending override removed.", "warning")
    else:
        _flash(request, "Unknown trending action.", "danger")

    return redirect("admin_engagement")


@admin_login_required
def admin_reports(request):
    downloads = Transaction.objects.filter(kind=Transaction.KIND_DOWNLOAD)
    top_creators = (
        User.objects.annotate(
            published_images=Count("images", filter=Q(images__is_published=True), distinct=True),
            published_videos=Count(
                "videos",
                filter=Q(videos__is_published=True, videos__status=GeneratedVideo.STATUS_DONE),
                distinct=True,
            ),
            followers_count=Count("followers", distinct=True),
        )
        .filter(Q(published_images__gt=0) | Q(published_videos__gt=0))
        .order_by("-published_images", "-published_videos", "-followers_count")[:10]
    )
    top_categories = (
        GeneratedVideo.objects.filter(is_published=True, status=GeneratedVideo.STATUS_DONE)
        .values("category")
        .annotate(count=Count("id"), views=Sum("view_count"))
        .order_by("-count", "-views")[:10]
    )
    recent_admin_actions = AdminActionLog.objects.select_related("admin", "target_user")[:25]
    report_stats = {
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "inactive_users": User.objects.filter(is_active=False).count(),
        "staff_users": User.objects.filter(is_staff=True).count(),
        "published_images": GeneratedImage.objects.filter(is_published=True).count(),
        "unpublished_images": GeneratedImage.objects.filter(is_published=False).count(),
        "published_videos": GeneratedVideo.objects.filter(is_published=True, status=GeneratedVideo.STATUS_DONE).count(),
        "unpublished_videos": GeneratedVideo.objects.filter(is_published=False).count(),
        "failed_videos": GeneratedVideo.objects.filter(status=GeneratedVideo.STATUS_FAILED).count(),
        "removed_assets": AdminActionLog.objects.filter(action=AdminActionLog.ACTION_ASSET_DELETED).count(),
        "moderated_assets": AdminActionLog.objects.filter(
            action__in=[
                AdminActionLog.ACTION_ASSET_DELETED,
                AdminActionLog.ACTION_ASSET_UNPUBLISHED,
                AdminActionLog.ACTION_ASSET_MODERATED,
            ]
        ).count(),
        "wallet_balance": Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0,
        "wallet_count": Wallet.objects.count(),
        "transactions": Transaction.objects.count(),
        "downloads": downloads.count(),
        "download_coins": -sum(txn.delta for txn in downloads.only("delta")),
        "pending_coin_requests": CoinRequest.objects.filter(status=CoinRequest.STATUS_PENDING).count(),
        "collections": Collection.objects.count(),
        "bookmarks": Bookmark.objects.count(),
        "comments": AssetComment.objects.count(),
        "ratings": AssetRating.objects.count(),
        "manual_trending": TrendingOverride.objects.filter(is_active=True).count(),
    }
    return render(
        request,
        "moderation/admin_reports.html",
        _base_context(
            request,
            report_stats=report_stats,
            top_creators=top_creators,
            top_categories=top_categories,
            top_images=GeneratedImage.objects.filter(is_published=True).select_related("user").order_by("-view_count")[:10],
            top_videos=GeneratedVideo.objects.filter(is_published=True, status=GeneratedVideo.STATUS_DONE).select_related("user").order_by("-view_count")[:10],
            recent_admin_actions=recent_admin_actions,
        ),
    )


@admin_login_required
@ensure_csrf_cookie
def admin_tools(request):
    return render(
        request,
        "moderation/admin_tools.html",
        _base_context(
            request,
            orphan_wallets=Wallet.objects.filter(user__isnull=True).count(),
            local_video_candidates=GeneratedVideo.objects.filter(video_file="", video_url__icontains="/media/").count(),
            django_admin_url=reverse("admin:index"),
            public_home_url=reverse("home"),
            featured_items=FeaturedAsset.objects.select_related("image__user", "video__user"),
            blog_posts=BlogPost.objects.select_related("author").order_by("home_order", "-created_at")[:50],
            image_candidates=GeneratedImage.objects.filter(is_published=True).select_related("user").order_by("-created_at")[:30],
            video_candidates=GeneratedVideo.objects.filter(is_published=True, status=GeneratedVideo.STATUS_DONE).select_related("user").order_by("-created_at")[:30],
        ),
    )


@admin_login_required
@require_POST
def admin_featured_action(request):
    action = request.POST.get("action")
    if action == "add":
        asset_type = request.POST.get("asset_type")
        try:
            asset_id = int(request.POST.get("asset_id", "0"))
            order = int(request.POST.get("order", "0"))
        except (TypeError, ValueError):
            _flash(request, "Invalid featured asset.", "danger")
            return redirect("admin_tools")

        if asset_type == "image":
            asset = get_object_or_404(GeneratedImage, pk=asset_id, is_published=True)
            item = FeaturedAsset.objects.filter(asset_type=FeaturedAsset.ASSET_IMAGE, image=asset).first()
            if item:
                item.video = None
                item.order = order
                item.save(update_fields=["video", "order"])
            else:
                FeaturedAsset.objects.create(asset_type=FeaturedAsset.ASSET_IMAGE, image=asset, order=order)
        elif asset_type == "video":
            asset = get_object_or_404(
                GeneratedVideo,
                pk=asset_id,
                is_published=True,
                status=GeneratedVideo.STATUS_DONE,
            )
            item = FeaturedAsset.objects.filter(asset_type=FeaturedAsset.ASSET_VIDEO, video=asset).first()
            if item:
                item.image = None
                item.order = order
                item.save(update_fields=["image", "order"])
            else:
                FeaturedAsset.objects.create(asset_type=FeaturedAsset.ASSET_VIDEO, video=asset, order=order)
        else:
            _flash(request, "Invalid featured asset type.", "danger")
            return redirect("admin_tools")
        record_admin_action(
            admin=request.admin_user,
            action=AdminActionLog.ACTION_CONTENT_UPDATED,
            note=f"Featured {asset_type} #{asset_id} on the home feed.",
            object_label=f"Featured {asset_type} #{asset_id}",
            asset_type=asset_type,
            asset_id=asset_id,
            notify=False,
            email=False,
            metadata={"order": order},
        )
        _flash(request, "Featured home-feed asset saved.")
    elif action == "update":
        item = get_object_or_404(FeaturedAsset, pk=request.POST.get("item_id"))
        try:
            item.order = int(request.POST.get("order", item.order))
        except (TypeError, ValueError):
            pass
        item.save(update_fields=["order"])
        record_admin_action(
            admin=request.admin_user,
            action=AdminActionLog.ACTION_CONTENT_UPDATED,
            note=f"Updated featured item #{item.pk} order.",
            object_label=f"Featured item #{item.pk}",
            notify=False,
            email=False,
            metadata={"order": item.order},
        )
        _flash(request, "Featured item order updated.")
    elif action == "remove":
        item = get_object_or_404(FeaturedAsset, pk=request.POST.get("item_id"))
        label = f"Featured item #{item.pk}"
        item.delete()
        record_admin_action(
            admin=request.admin_user,
            action=AdminActionLog.ACTION_CONTENT_UPDATED,
            note=f"Removed {label} from the home feed.",
            object_label=label,
            notify=False,
            email=False,
        )
        _flash(request, "Featured item removed.", "warning")
    else:
        _flash(request, "Unknown featured action.", "danger")
    return redirect("admin_tools")


@admin_login_required
@require_POST
def admin_blog_save(request, post_id=None):
    post = get_object_or_404(BlogPost, pk=post_id) if post_id else BlogPost(author=request.admin_user)
    post.title = (request.POST.get("title") or "").strip()
    post.category = (request.POST.get("category") or "Updates").strip()
    post.excerpt = (request.POST.get("excerpt") or "").strip()
    post.body = (request.POST.get("body") or "").strip()
    post.is_published = request.POST.get("is_published") == "on"
    post.show_on_home = request.POST.get("show_on_home") == "on"
    try:
        post.home_order = int(request.POST.get("home_order", "0"))
    except (TypeError, ValueError):
        post.home_order = 0
    if not post.title or not post.body:
        _flash(request, "Blog title and body are required.", "danger")
        return redirect("admin_tools")
    if not post.author_id:
        post.author = request.admin_user
    post.save()
    record_admin_action(
        admin=request.admin_user,
        action=AdminActionLog.ACTION_CONTENT_UPDATED,
        note=f"Saved blog post '{post.title}'.",
        object_label=post.title,
        notify=False,
        email=False,
        metadata={"post_id": post.pk, "show_on_home": post.show_on_home, "is_published": post.is_published},
    )
    _flash(request, "Blog post saved.")
    return redirect("admin_tools")


@admin_login_required
@require_POST
def admin_blog_delete(request, post_id):
    post = get_object_or_404(BlogPost, pk=post_id)
    title = post.title
    post.delete()
    record_admin_action(
        admin=request.admin_user,
        action=AdminActionLog.ACTION_CONTENT_UPDATED,
        note=f"Deleted blog post '{title}'.",
        object_label=title,
        notify=False,
        email=False,
    )
    _flash(request, f"Deleted blog post '{title}'.", "warning")
    return redirect("admin_tools")


@admin_login_required
@require_POST
def admin_sync_video_files(request):
    changed = 0
    for video in GeneratedVideo.objects.all():
        if video.sync_video_file_from_url():
            video.save(update_fields=["video_file", "updated_at"])
            changed += 1
    record_admin_action(
        admin=request.admin_user,
        action=AdminActionLog.ACTION_CONTENT_UPDATED,
        note=f"Synced {changed} local video file references.",
        object_label="Video file sync",
        notify=False,
        email=False,
        metadata={"changed": changed},
    )
    _flash(request, f"Synced {changed} local video file reference{'s' if changed != 1 else ''}.")
    return redirect("admin_tools")
