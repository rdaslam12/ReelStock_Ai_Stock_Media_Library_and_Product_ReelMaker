from __future__ import annotations

import logging
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.db import transaction

from core.models import (
    AssetComment,
    AssetRating,
    AssetView,
    Bookmark,
    CollectionItem,
    GeneratedImage,
    GeneratedVideo,
    Notification,
)
from wallet.models import BasketItem

from .models import AdminActionLog

logger = logging.getLogger(__name__)


def require_note(request, action_label="this action"):
    note = (request.POST.get("admin_note") or request.POST.get("note") or "").strip()
    if not note:
        return "", f"An admin note is required for {action_label}."
    return note, ""


def send_admin_email(user, subject, body):
    if not user or not user.email:
        return False, "User has no email address."
    try:
        sent = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        return bool(sent), ""
    except Exception as exc:  # noqa: BLE001 - admin action must survive email failures
        logger.exception("Failed to send admin email to user_id=%s", getattr(user, "pk", None))
        return False, str(exc)


def record_admin_action(
    *,
    admin,
    action,
    target_user=None,
    note,
    object_label="",
    asset_type="",
    asset_id=None,
    metadata=None,
    notify=True,
    email=True,
    notification_message="",
    email_subject="",
    email_body="",
):
    log = AdminActionLog.objects.create(
        admin=admin,
        target_user=target_user,
        action=action,
        asset_type=asset_type or "",
        asset_id=asset_id,
        object_label=object_label or "",
        note=note,
        metadata=metadata or {},
    )

    if target_user and notify:
        Notification.objects.create(
            recipient=target_user,
            actor=admin,
            notif_type=Notification.NOTIF_ADMIN,
            asset_type=asset_type or "",
            asset_id=asset_id,
            message=notification_message or log.get_action_display(),
            admin_note=note,
        )

    if target_user and email:
        subject = email_subject or f"ReelStock admin update: {log.get_action_display()}"
        body = email_body or (
            f"Hello {target_user.get_full_name() or target_user.username},\n\n"
            f"{notification_message or log.get_action_display()}\n\n"
            f"Admin note:\n{note}\n\n"
            "If you have questions, contact the ReelStock admin team."
        )
        log.email_sent, log.email_error = send_admin_email(target_user, subject, body)
        log.save(update_fields=["email_sent", "email_error"])

    return log


def _storage_name_from_media_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        path = parsed.path
    else:
        path = raw

    media_url = settings.MEDIA_URL or "/media/"
    if path.startswith(media_url):
        return path[len(media_url):].lstrip("/")
    if path.startswith("/media/"):
        return path[len("/media/"):]
    if path.startswith("media/"):
        return path[len("media/"):]
    return ""


def _delete_storage_name(name, deleted):
    if not name or name in deleted:
        return False
    deleted.add(name)
    try:
        if default_storage.exists(name):
            default_storage.delete(name)
            logger.info("Deleted media file %s", name)
            return True
        logger.info("Media file already missing: %s", name)
    except Exception:
        logger.exception("Failed deleting media file %s", name)
    return False


def collect_asset_storage_names(asset_type, asset):
    names = []
    if asset_type == "image":
        if getattr(asset, "image_file", None) and asset.image_file.name:
            names.append(asset.image_file.name)
        names.append(_storage_name_from_media_url(getattr(asset, "image_url", "")))
        names.append(_storage_name_from_media_url(getattr(asset, "media_url", "")))
    else:
        if getattr(asset, "video_file", None) and asset.video_file.name:
            names.append(asset.video_file.name)
        if getattr(asset, "source_image", None) and asset.source_image and asset.source_image.name:
            names.append(asset.source_image.name)
        names.append(_storage_name_from_media_url(getattr(asset, "video_url", "")))
        names.append(_storage_name_from_media_url(getattr(asset, "source_image_url", "")))
        names.append(_storage_name_from_media_url(getattr(asset, "playback_url", "")))
        names.append(_storage_name_from_media_url(getattr(asset, "source_media_url", "")))
    return [name for name in names if name]


def cleanup_polymorphic_asset_relations(asset_type, asset_id):
    AssetView.objects.filter(asset_type=asset_type, asset_id=asset_id).delete()
    AssetRating.objects.filter(asset_type=asset_type, asset_id=asset_id).delete()
    AssetComment.objects.filter(asset_type=asset_type, asset_id=asset_id).delete()
    Bookmark.objects.filter(asset_type=asset_type, asset_id=asset_id).delete()
    CollectionItem.objects.filter(asset_type=asset_type, asset_id=asset_id).delete()
    Notification.objects.filter(asset_type=asset_type, asset_id=asset_id).update(asset_id=None, asset_type="")


def delete_asset_and_storage(asset_type, asset):
    storage_names = collect_asset_storage_names(asset_type, asset)
    deleted_files = []
    missing_or_skipped = []
    seen = set()

    for name in storage_names:
        before_count = len(deleted_files)
        deleted = _delete_storage_name(name, seen)
        if deleted:
            deleted_files.append(name)
        elif len(deleted_files) == before_count and name not in deleted_files:
            missing_or_skipped.append(name)

    asset_id = asset.pk
    with transaction.atomic():
        cleanup_polymorphic_asset_relations(asset_type, asset_id)
        asset.delete()

    return {
        "deleted_files": deleted_files,
        "missing_or_skipped": sorted(set(missing_or_skipped)),
        "storage_names": sorted(set(storage_names)),
    }


def unpublish_user_assets(user):
    images = GeneratedImage.objects.filter(user=user, is_published=True).update(is_published=False)
    videos = GeneratedVideo.objects.filter(user=user, is_published=True).update(is_published=False)
    return images, videos


def admin_email_body(user, message, note):
    return (
        f"Hello {user.get_full_name() or user.username},\n\n"
        f"{message}\n\n"
        f"Admin note:\n{note}\n\n"
        f"Contact: {getattr(settings, 'ADMIN_CONTACT_EMAIL', '')}\n\n"
        "ReelStock Admin Team"
    )
