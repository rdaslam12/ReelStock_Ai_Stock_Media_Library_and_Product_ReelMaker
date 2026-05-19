"""
background_remover.py
─────────────────────
Removes the background from a product image and returns a PIL Image
with a transparent (RGBA) background.

Priority order:
  1. rembg  — best quality, local model (~170MB download on first use)
  2. HF API  — briaai/RMBG-2.0 via Hugging Face Inference API
  3. GrabCut — OpenCV-based, no model needed, works offline
  4. Passthrough — returns original as-is (always succeeds)

Usage:
    from .background_remover import remove_background
    rgba_img = remove_background('/path/to/product.jpg')
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import requests
from PIL import Image

from django.conf import settings

logger = logging.getLogger(__name__)


# ── Method 1: rembg (best quality, local) ────────────────────────────

def _try_rembg(img: Image.Image) -> Optional[Image.Image]:
    try:
        from rembg import remove as rembg_remove
        result = rembg_remove(img)
        logger.info("background_remover: used rembg")
        return result.convert("RGBA")
    except ImportError:
        return None
    except Exception as exc:
        logger.warning(f"background_remover: rembg failed — {exc}")
        return None


# ── Method 2: HF API (briaai/RMBG-2.0) ───────────────────────────────

def _try_hf_rmbg(img: Image.Image) -> Optional[Image.Image]:
    token = getattr(settings, "HF_API_TOKEN", "")
    if not token:
        return None
    try:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        buf.seek(0)
        resp = requests.post(
            "https://api-inference.huggingface.co/models/briaai/RMBG-2.0",
            headers={"Authorization": f"Bearer {token}"},
            data=buf.read(),
            timeout=60,
        )
        if resp.status_code == 200 and resp.content:
            result = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            logger.info("background_remover: used HF RMBG-2.0 API")
            return result
        logger.warning(f"background_remover: HF RMBG returned {resp.status_code}")
    except Exception as exc:
        logger.warning(f"background_remover: HF API failed — {exc}")
    return None


# ── Method 3: OpenCV GrabCut (offline, no model) ─────────────────────

def _try_grabcut(img: Image.Image) -> Image.Image:
    """
    GrabCut with smart rect: assumes the product occupies the middle
    70% of the image (typical product photo composition).
    """
    rgb  = np.array(img.convert("RGB"))
    bgr  = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]

    # Foreground rect: inner 70% of frame (product assumed centred)
    margin_x = int(w * 0.15)
    margin_y = int(h * 0.15)
    rect = (margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)

    mask    = np.zeros((h, w), np.uint8)
    bgd_mdl = np.zeros((1, 65), np.float64)
    fgd_mdl = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(bgr, mask, rect, bgd_mdl, fgd_mdl, 8, cv2.GC_INIT_WITH_RECT)
        alpha = np.where((mask == 2) | (mask == 0), 0, 255).astype(np.uint8)
    except Exception:
        # If GrabCut fails, mark full image as foreground
        alpha = np.full((h, w), 255, dtype=np.uint8)

    # Refine the binary alpha mask to improve cutout quality.
    # GrabCut can leave small holes and jagged edges. Perform morphological
    # closing to fill gaps and opening to remove isolated noise. Then blur
    # the edges for a soft feather. These operations greatly improve the
    # perceived quality of the mask, making the product blend more naturally.
    try:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        # Close small holes inside the foreground
        mask_closed = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel, iterations=2)
        # Open to remove isolated speckles
        mask_opened = cv2.morphologyEx(mask_closed, cv2.MORPH_OPEN, kernel, iterations=1)
        # Final Gaussian blur to feather edges
        alpha_blurred = cv2.GaussianBlur(mask_opened, (7, 7), 0)
        alpha_final = np.where(mask_opened > 0, alpha_blurred, 0).astype(np.uint8)
    except Exception:
        # Fallback if morphology operations fail
        alpha_blurred = cv2.GaussianBlur(alpha, (5, 5), 0)
        alpha_final   = np.where(alpha > 0, alpha_blurred, 0).astype(np.uint8)

    pil_rgba = img.convert("RGBA")
    pil_rgba.putalpha(Image.fromarray(alpha_final))
    logger.info("background_remover: used GrabCut fallback")
    return pil_rgba


# ── Public API ────────────────────────────────────────────────────────

def remove_background(source: str | Path | Image.Image) -> Image.Image:
    """
    Remove background from a product image.
    Always returns an RGBA PIL Image.
    Tries methods in order: rembg → HF API → GrabCut → passthrough.
    """
    if isinstance(source, (str, Path)):
        img = Image.open(source).convert("RGBA")
    else:
        img = source.convert("RGBA")

    # Try rembg first (best quality when installed)
    result = _try_rembg(img)
    if result is not None:
        return result

    # Try HF API
    result = _try_hf_rmbg(img)
    if result is not None:
        return result

    # GrabCut fallback (always works offline)
    return _try_grabcut(img)
