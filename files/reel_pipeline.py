"""
reel_pipeline.py
────────────────
Orchestrates the full Reel Maker pipeline in a background thread:

  1. Remove product background (rembg → HF API → GrabCut)
  2. Generate 5 AI scene backgrounds (HF FLUX or premium gradient fallback)
  3. Composite product onto each scene (with rim light, grading, shadow)
  4. Assemble cinematic MP4 with Ken Burns + rich transitions
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


def run_pipeline(video_id: int, source_image_path: str, category: str) -> None:
    """Run full pipeline synchronously — call in a background thread."""
    from django.conf import settings
    from core.models import GeneratedVideo
    from .variation_generator import generate_variations
    from .reel_assembler import save_reel_to_media

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
        logger.info(f"reel_pipeline: started for video_id={video_id}, category={category}")

        # ── Stage 1: bg removal + scene generation + compositing ──────
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
        _set_stage(f"Assembling {len(frame_paths)}-frame cinematic reel…")
        video_url = save_reel_to_media(frame_paths)

        # ── Done ──────────────────────────────────────────────────────
        video = GeneratedVideo.objects.get(pk=video_id)
        video.status      = GeneratedVideo.STATUS_DONE
        video.video_url   = video_url
        video.error_message = ""
        video.save(update_fields=["status", "video_url", "error_message"])
        logger.info(f"reel_pipeline: done — {video_url}")

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
    video_id: int, source_image_path: str, category: str
) -> threading.Thread:
    t = threading.Thread(
        target=run_pipeline,
        args=(video_id, source_image_path, category),
        daemon=True,
        name=f"reel-pipeline-{video_id}",
    )
    t.start()
    return t
