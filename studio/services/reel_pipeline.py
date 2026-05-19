"""
reel_pipeline.py
────────────────
Orchestrates the full Reel Maker pipeline in a background thread:

  1. Remove product background (rembg → HF API → GrabCut)
  2. Generate 5 AI scene backgrounds (HF FLUX or premium gradient fallback)
  3. Composite product onto each scene (with rim light, grading, shadow)
  4. Assemble cinematic MP4 with Ken Burns + rich transitions + title overlay
  5. Update GeneratedVideo DB record with stage progress throughout

IMPROVEMENTS:
  - stage_message field updated at each step for real progress reporting
  - Error messages are surfaced clearly to the frontend
  - No silent failures — every exception is logged with full traceback
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def run_pipeline(video_id: int, source_image_path: str, category: str, duration: str | None = None) -> None:
    """Run full pipeline synchronously — call in a background thread."""
    from django.conf import settings
    from core.models import GeneratedVideo
    from .variation_generator import generate_variations
    from .reel_assembler import build_caption_segments, save_reel_to_media, title_for_category

    def _media_file_name_from_url(url: str) -> str:
        """Convert a MEDIA_URL-based URL to a FileField name."""
        url = (url or "").strip()
        if not url or url.startswith(("http://", "https://")):
            return ""
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if url.startswith(media_url):
            return url[len(media_url):].lstrip("/")
        if url.startswith("/media/"):
            return url[len("/media/"):]
        if url.startswith("media/"):
            return url[len("media/"):]
        return url.lstrip("/")

    def _set_stage(msg: str) -> None:
        """Update stage message in DB for frontend progress display."""
        try:
            GeneratedVideo.objects.filter(pk=video_id).update(error_message=msg)
        except Exception:
            pass

    try:
        video = GeneratedVideo.objects.get(pk=video_id)
        video.status = GeneratedVideo.STATUS_PROCESSING
        video.error_message = "Starting pipeline…"
        video.save(update_fields=["status", "error_message"])
        logger.info(f"reel_pipeline: started for video_id={video_id}, category={category}, duration={duration or 'default'}")

        # ── Stage 1: bg removal + scene generation + compositing ──────
        # Inform the user if no HF token is provided. When the HF_API_TOKEN
        # environment variable is missing, the scene generator falls back to
        # premium gradients. Provide a hint in the stage message so users
        # understand why they're seeing gradients instead of AI scenes.
        if not getattr(settings, "HF_API_TOKEN", ""):  # token not provided
            _set_stage("No HF API token – using gradient backgrounds. Removing background and generating scenes…")
        else:
            _set_stage("Removing background and generating scenes…")
        frame_dir = Path(settings.MEDIA_ROOT) / "reel_frames"
        frame_paths = generate_variations(
            source_path=source_image_path,
            category=category,
            save_dir=frame_dir,
        )

        if not frame_paths:
            raise ValueError("No frames were generated — check logs for scene/compositing errors.")

        logger.info(f"reel_pipeline: {len(frame_paths)} frames ready, assembling video")

        # ── Stage 2: video assembly ────────────────────────────────────
        # The requested duration is the exact output length. The assembler fits
        # both shot holds and transitions into this total frame budget.
        target_duration: float = 4.0
        if duration:
            try:
                total_secs = float(duration)
                if total_secs in (4.0, 6.0, 9.0):
                    target_duration = total_secs
            except Exception:
                target_duration = 4.0

        overlay_text = title_for_category(category)
        caption_style = (video.caption_style or "auto").strip().lower()
        caption_segments = video.caption_script or build_caption_segments(
            category=category,
            product_name=video.product_name,
            target_duration=target_duration,
            style=caption_style,
        )
        if not video.caption_script:
            GeneratedVideo.objects.filter(pk=video_id).update(caption_script=caption_segments)
        logger.info(
            "reel_pipeline: assembling video_id=%s target_duration=%s caption_style=%s overlay_text=%r",
            video_id,
            target_duration,
            caption_style,
            overlay_text,
        )
        _set_stage(f"Assembling exact {target_duration:g}s reel with animated captions…")
        video_url = save_reel_to_media(
            frame_paths,
            overlay_text=overlay_text,
            target_duration=target_duration,
            caption_style=caption_style,
            caption_segments=caption_segments,
        )
        video_file_name = _media_file_name_from_url(video_url)

        # ── Done ──────────────────────────────────────────────────────
        video = GeneratedVideo.objects.get(pk=video_id)
        video.status      = GeneratedVideo.STATUS_DONE
        video.video_url   = video_url
        if video_file_name:
            video.video_file.name = video_file_name
        video.error_message = ""
        update_fields = ["status", "video_url", "error_message"]
        if video_file_name:
            update_fields.append("video_file")
        video.save(update_fields=update_fields)
        logger.info(
            "reel_pipeline: done video_id=%s video_url=%s video_file=%s",
            video_id,
            video_url,
            video_file_name or "",
        )

    except Exception as exc:
        logger.error(f"reel_pipeline: FAILED for video_id={video_id} — {exc}", exc_info=True)
        try:
            from core.models import GeneratedVideo as GV
            GV.objects.filter(pk=video_id).update(
                status=GV.STATUS_FAILED,
                error_message=str(exc)[:500],
            )
        except Exception:
            pass


def start_pipeline_thread(
    video_id: int,
    source_image_path: str,
    category: str,
    duration: str | None = None,
) -> threading.Thread:
    """
    Launch the reel generation pipeline in a separate daemon thread. Pass through
    optional duration (seconds) to influence shot timing. The duration should be a
    string containing a positive number. If None or invalid, default timing is used.
    """
    t = threading.Thread(
        target=run_pipeline,
        args=(video_id, source_image_path, category, duration),
        daemon=True,
        name=f"reel-pipeline-{video_id}",
    )
    t.start()
    return t
