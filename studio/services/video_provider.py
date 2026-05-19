"""
Fal.ai image-to-video provider for product reel generation.

Uses fal-ai/kling-video/v1.6/standard/image-to-video which is well-suited
for product-style short reels.

API docs: https://fal.ai/models/kling-video

Flow:
  1. Submit job → get request_id
  2. Poll /queue/requests/{id}/status until COMPLETED
  3. Return video URL
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

import requests
from django.conf import settings

from .watermark import watermark_video_file


class VideoGenerationError(Exception):
    pass


# Predefined product-style prompts per category
# These are crafted to produce luxury/commercial reel output
CATEGORY_PROMPTS: Dict[str, str] = {
    "Shoe": (
        "Professional luxury sneaker advertisement reel. The shoe rotates slowly on a clean "
        "reflective surface. Cinematic lighting with soft rim light highlights the material "
        "texture and stitching. Subtle slow zoom-in toward the sole and toe box. "
        "Dark gradient studio background. Commercial quality, high-end brand feel. "
        "Camera: slow pan from side profile to 3/4 angle. 4K, ultra-sharp, product photography style."
    ),
    "Watch": (
        "Luxury watch advertisement reel. The timepiece rotates elegantly on a marble surface "
        "with dramatic chiaroscuro lighting emphasizing the dial, hands, and case edges. "
        "Subtle camera push-in reveals the intricate details. Gold and silver tones reflect softly. "
        "Premium jewelry-store aesthetic, deep black background. Cinematic slow motion. "
        "Camera: slow orbit around the watch face, 4K, ultra-detailed."
    ),
    "Bag": (
        "High-fashion luxury handbag advertisement reel. The bag sits on a polished surface "
        "and rotates to reveal every angle — front, side, and back — with soft studio lighting "
        "highlighting the leather grain, stitching, and hardware. "
        "Subtle zoom draws attention to the clasp and logo. "
        "Clean white or gradient background, editorial fashion feel. "
        "Camera: smooth 360 orbit with gentle push-in. Cinematic, 4K."
    ),
    "Other": (
        "Premium product advertisement reel. The product is showcased on a clean studio "
        "background with cinematic lighting. Slow rotation reveals all angles. "
        "Subtle zoom-in highlights key product features. "
        "Commercial luxury feel, polished and professional. "
        "Camera: smooth slow orbit with a gentle push-in. 4K, ultra-sharp."
    ),
}

FAL_BASE = "https://queue.fal.run"
VIDEO_MODEL = "fal-ai/kling-video/v1.6/standard/image-to-video"


class FalVideoProvider:
    def __init__(self) -> None:
        self.api_key = getattr(settings, "FAL_API_KEY", "")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }

    def _image_to_base64(self, image_path: str) -> str:
        """Convert a saved media file to a base64 data URI."""
        path = Path(settings.MEDIA_ROOT) / image_path.lstrip("/media/")
        if not path.exists():
            # Try as absolute path
            path = Path(image_path)
        with open(path, "rb") as f:
            data = f.read()
        ext = path.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
        b64 = base64.b64encode(data).decode()
        return f"data:{mime};base64,{b64}"

    def submit_job(self, image_path: str, category: str, duration: str = "5") -> str:
        """Submit video generation job; returns request_id."""
        if not self.api_key:
            raise VideoGenerationError(
                "Video generation is not configured. Set the FAL_API_KEY environment variable."
            )

        prompt = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["Other"])
        image_data_uri = self._image_to_base64(image_path)

        payload = {
            "prompt": prompt,
            "image_url": image_data_uri,
            "duration": duration,
            "aspect_ratio": "9:16",
        }

        url = f"{FAL_BASE}/{VIDEO_MODEL}"
        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            request_id = data.get("request_id")
            if not request_id:
                raise VideoGenerationError(f"No request_id returned: {data}")
            return request_id
        except requests.RequestException as exc:
            raise VideoGenerationError(f"Failed to submit video job: {exc}") from exc

    def poll_status(self, request_id: str) -> Dict:
        """
        Poll once and return status dict:
          {"status": "IN_QUEUE"|"IN_PROGRESS"|"COMPLETED"|"FAILED", "video_url": "..."}
        """
        status_url = f"{FAL_BASE}/{VIDEO_MODEL}/requests/{request_id}/status"
        try:
            resp = requests.get(status_url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise VideoGenerationError(f"Failed to poll status: {exc}") from exc

        fal_status = data.get("status", "UNKNOWN")

        if fal_status == "COMPLETED":
            # Get result
            result_url = f"{FAL_BASE}/{VIDEO_MODEL}/requests/{request_id}"
            try:
                rresp = requests.get(result_url, headers=self._headers(), timeout=30)
                rresp.raise_for_status()
                rdata = rresp.json()
            except requests.RequestException as exc:
                raise VideoGenerationError(f"Failed to fetch result: {exc}") from exc

            video_url = ""
            if rdata.get("video"):
                video_url = rdata["video"].get("url", "")
            elif rdata.get("videos"):
                video_url = rdata["videos"][0].get("url", "")

            return {"status": "done", "video_url": video_url}

        elif fal_status in ("FAILED", "ERROR"):
            error = data.get("error", {})
            msg = error.get("message", str(data)) if isinstance(error, dict) else str(error)
            return {"status": "failed", "error": msg}
        else:
            # IN_QUEUE or IN_PROGRESS
            return {"status": "processing"}


# ── Text-to-video placeholder ────────────────────────────────────────
class TextToVideoProvider:
    def __init__(self) -> None:
        self.api_token = getattr(settings, "HF_API_TOKEN", "")
        self.model = getattr(settings, "TEXT_VIDEO_MODEL", "")
        self.timeout = getattr(settings, "TEXT_VIDEO_TIMEOUT", 120)

    def generate(self, prompt: str) -> str:
        if not self.api_token:
            raise VideoGenerationError(
                "Text-to-video is not configured. Set HF_API_TOKEN in your environment."
            )

        if not self.model:
            raise VideoGenerationError(
                "Text-to-video model is not configured. Set TEXT_VIDEO_MODEL in settings."
            )

        headers = {
            "Authorization": f"Bearer {self.api_token}",
        }

        payload = {
            "inputs": prompt
        }

        url = f"https://api-inference.huggingface.co/models/{self.model}"

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)

            if resp.status_code == 503:
                raise VideoGenerationError(
                    "The video model is loading or unavailable right now. Please try again shortly."
                )

            resp.raise_for_status()
        except requests.RequestException as exc:
            raise VideoGenerationError(f"Text-to-video request failed: {exc}") from exc

        output_dir = Path(settings.MEDIA_ROOT) / "generated_videos"
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{uuid4().hex}.mp4"
        save_path = output_dir / filename
        save_path.write_bytes(resp.content)
        watermark_video_file(save_path)

        return f"{settings.MEDIA_URL}generated_videos/{filename}"


TEXT_VIDEO_PLACEHOLDER = (
    "Text-to-video model not configured. Please add your model API key/endpoint."
)
