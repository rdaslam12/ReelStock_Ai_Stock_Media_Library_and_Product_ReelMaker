from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import GeneratedImage, GeneratedVideo
from .services.image_provider import HuggingFaceImageProvider, ImageGenerationError
from .services.video_provider import TextToVideoProvider, VideoGenerationError
from .services.reel_pipeline import start_pipeline_thread

logger = logging.getLogger(__name__)


def _absolute_url(request, url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if not url.startswith("/"):
        url = "/" + url
    return request.build_absolute_uri(url)


def create(request):
    return render(request, "studio/create.html")


@login_required
def my_assets(request):
    tab    = request.GET.get("tab", "all")
    images = GeneratedImage.objects.filter(user=request.user, is_saved=True)
    videos = GeneratedVideo.objects.filter(user=request.user, is_saved=True, status="done")
    return render(request, "studio/my_assets.html", {
        "images": images, "videos": videos,
        "tab": tab,
        "total_images": images.count(),
        "total_videos": videos.count(),
        "total": images.count() + videos.count(),
    })


def prompt_to_image(request):
    return render(request, "studio/prompt_to_image.html")


@require_POST
def generate_image(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    prompt       = (payload.get("prompt") or "").strip()
    style        = (payload.get("style") or "Realistic").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "1:1").strip()

    if not prompt:
        return JsonResponse({"success": False, "error": "Please enter a prompt."}, status=400)

    provider = HuggingFaceImageProvider()
    try:
        result = provider.generate_image(prompt=prompt, style=style, aspect_ratio=aspect_ratio)
    except ImageGenerationError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=503)

    return JsonResponse({
        "success": True,
        "image_url": result["image_url"],
        "prompt_used": result["prompt_used"],
        "style": style,
        "aspect_ratio": aspect_ratio,
    })


@require_POST
@login_required
def save_image(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    image_url    = (payload.get("image_url") or "").strip()
    prompt       = (payload.get("prompt") or "").strip()
    style        = (payload.get("style") or "").strip()
    aspect_ratio = (payload.get("aspect_ratio") or "").strip()
    publish      = bool(payload.get("publish", False))

    if not image_url:
        return JsonResponse({"success": False, "error": "No image URL."}, status=400)

    img = GeneratedImage.objects.create(
        user=request.user, prompt=prompt, style=style,
        aspect_ratio=aspect_ratio, image_url=image_url,
        is_saved=True, is_published=publish,
    )
    detail_url = reverse("asset_detail", args=["image", img.pk]) if publish else ""
    return JsonResponse({
        "success": True,
        "id": img.pk,
        "published": publish,
        "detail_url": detail_url,
        "public_url": _absolute_url(request, detail_url) if detail_url else "",
    })


@require_POST
def generate_video_text(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return JsonResponse({"success": False, "error": "Please enter a prompt."}, status=400)

    provider = TextToVideoProvider()
    try:
        video_url = provider.generate(prompt=prompt)
    except VideoGenerationError as exc:
        return JsonResponse({"success": False, "error": str(exc), "needs_config": True}, status=503)

    return JsonResponse({"success": True, "video_url": video_url, "prompt_used": prompt})


# ── Reel Maker ────────────────────────────────────────────────────────

@require_POST
@login_required
def submit_reel(request):
    category     = request.POST.get("category", "Other").strip()
    product_name = (request.POST.get("product_name", "").strip() or category)
    image_file   = request.FILES.get("product_image")

    # Capture final duration. Valid values are exact target seconds.
    duration_str = (request.POST.get("duration") or "").strip()
    allowed_durations = {"4", "6", "9"}
    duration = duration_str if duration_str in allowed_durations else "4"
    caption_style = (request.POST.get("caption_style") or "auto").strip().lower()
    allowed_caption_styles = {
        "auto", "karaoke", "bounce", "slide_up", "typewriter",
        "zoom", "glitch", "fade_motion", "punch",
    }
    if caption_style not in allowed_caption_styles:
        caption_style = "auto"

    if not image_file:
        return JsonResponse({"success": False, "error": "Please upload a product image."}, status=400)

    allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
    ext = Path(image_file.name).suffix.lower()
    if ext not in allowed_ext:
        return JsonResponse({"success": False, "error": "Only JPG, PNG, WEBP images are accepted."}, status=400)

    filename  = f"reel_input_{uuid4().hex}{ext}"
    upload_dir = Path(settings.MEDIA_ROOT) / "reel_inputs"
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = upload_dir / filename

    with open(save_path, "wb") as f:
        for chunk in image_file.chunks():
            f.write(chunk)

    relative_url = f"{settings.MEDIA_URL}reel_inputs/{filename}"

    video = GeneratedVideo.objects.create(
        user=request.user,
        category=category,
        product_name=product_name,
        source_image=f"reel_inputs/{filename}",
        source_image_url=relative_url,
        status=GeneratedVideo.STATUS_PENDING,
        duration=duration,
        caption_style=caption_style,
    )

    logger.info(
        "submit_reel: queued video_id=%s category=%s source_image=%s duration=%s caption_style=%s",
        video.pk,
        category,
        video.source_image.name,
        duration,
        caption_style,
    )

    # Start the background processing thread with the optional duration
    start_pipeline_thread(
        video_id=video.pk,
        source_image_path=str(save_path),
        category=category,
        duration=duration,
    )

    return JsonResponse({"success": True, "video_id": video.pk})


@login_required
def reel_status(request, video_id):
    """
    Returns pipeline status for frontend polling.

    Response schema:
      pending / processing:  {"status": "pending"|"processing", "stage": "<human message>"}
      done:                  {"status": "done", "video_url": "<url>"}
      failed:                {"status": "failed", "error": "<message>"}

    NOTE: We do NOT delete the record on failure so the user can see the
    error message. The frontend handles cleanup.
    """
    video = get_object_or_404(GeneratedVideo, pk=video_id, user=request.user)
    if video.status == GeneratedVideo.STATUS_DONE:
        if video.sync_video_file_from_url():
            video.save(update_fields=["video_file", "updated_at"])
            logger.info(
                "reel_status: backfilled video_file for video_id=%s from video_url=%s -> %s",
                video_id,
                video.video_url,
                video.video_file.name,
            )
        video_url = _absolute_url(request, video.playback_url)
        logger.debug(
            "reel_status: video_id=%s done playback_url=%s raw_video_url=%s video_file=%s",
            video_id,
            video_url,
            video.video_url,
            video.video_file.name if video.video_file else "",
        )
        return JsonResponse({
            "status": "done",
            "video_url": video_url,
            "media_url": video_url,
            "playback_url": video_url,
        })

    if video.status == GeneratedVideo.STATUS_FAILED:
        error = video.error_message or "Generation failed — please try again."
        # Don't delete — just report failure so user can retry
        return JsonResponse({"status": "failed", "error": error})

    # pending or processing — include stage message for UI
    stage = video.error_message or ""  # repurposed as stage label during processing
    return JsonResponse({"status": video.status, "stage": stage})


@require_POST
@login_required
def publish_reel(request, video_id):
    video = get_object_or_404(GeneratedVideo, pk=video_id, user=request.user, status="done")
    changed = video.sync_video_file_from_url()
    if not video.playback_url:
        return JsonResponse({"success": False, "error": "No playable reel file was saved."}, status=400)

    video.is_published = True
    title = (request.POST.get("title") or "").strip()
    if title:
        video.title = title
    update_fields = ["is_published", "title", "updated_at"]
    if changed:
        update_fields.append("video_file")
    video.save(update_fields=update_fields)
    logger.info(
        "publish_reel: published video_id=%s playback_url=%s video_file=%s raw_video_url=%s",
        video_id,
        video.playback_url,
        video.video_file.name if video.video_file else "",
        video.video_url,
    )
    return JsonResponse({
        "success": True,
        "video_url": _absolute_url(request, video.playback_url),
        "playback_url": _absolute_url(request, video.playback_url),
        "detail_url": reverse("asset_detail", args=["video", video.pk]),
        "public_url": _absolute_url(request, reverse("asset_detail", args=["video", video.pk])),
    })
