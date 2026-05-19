"""
variation_generator.py
──────────────────────
Orchestrates the complete product variation pipeline:

  1. Remove background from uploaded product image
  2. Generate 5 scene backgrounds (HF FLUX or premium local fallback)
  3. Composite product onto each scene
  4. Save all frames to disk

Returns 6 frame paths:
  • Frame 0 — original product photo (anchor frame)
  • Frames 1–5 — product composited into different scenes/environments

KEY FIXES:
  - Scene names are slugified before use in file paths (fixes [Errno 2] crash
    from names like "Nature / Grass" creating invalid paths like "nature_/grass")
  - Premium dark radial gradient for frame 0 instead of plain flat gradient
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw

from django.conf import settings
from django.utils.text import slugify

from .background_remover import remove_background
from .scene_generator import generate_scenes
from .compositor import composite

logger = logging.getLogger(__name__)


def _safe_scene_slug(name: str) -> str:
    """
    Convert a scene name into a filesystem-safe slug.
    'Nature / Grass' → 'nature-grass'
    'Studio Dark'    → 'studio-dark'
    """
    return slugify(name) or "scene"


def _prepare_original_frame(source_path: Path, W: int = 576, H: int = 1024) -> Image.Image:
    """
    Prepare the original uploaded image as frame 0.
    Centers and fits it to the reel aspect ratio with a premium dark radial bg.
    """
    src = Image.open(source_path).convert("RGB")
    sw, sh = src.size

    # Premium dark radial gradient — center slightly lighter
    bg_arr = np.zeros((H, W, 3), dtype=np.float32)
    Y = np.linspace(-1.0, 1.0, H)
    X = np.linspace(-1.0, 1.0, W)
    Xg, Yg = np.meshgrid(X, Y)
    dist = np.sqrt(Xg**2 + Yg**2)
    center_rgb = np.array([30, 26, 38], dtype=np.float32)
    edge_rgb   = np.array([7,  6,  10], dtype=np.float32)
    t = np.clip(dist / 1.4, 0.0, 1.0)[:, :, np.newaxis]
    bg_arr = center_rgb * (1.0 - t) + edge_rgb * t
    bg = Image.fromarray(bg_arr.astype(np.uint8), "RGB")

    # Soft warm spotlight overlay
    spotlight = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(spotlight)
    cx, cy = W // 2, H // 2
    radius = min(W, H) // 2
    for r in range(radius, 0, -2):
        alpha = int(22 * (1.0 - r / radius) ** 2)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 220, 160, alpha))
    bg = Image.alpha_composite(bg.convert("RGBA"), spotlight).convert("RGB")

    # Scale product to 65% width, clamped to 80% height
    target_w = int(W * 0.65)
    scale    = target_w / sw
    target_h = int(sh * scale)
    if target_h > int(H * 0.80):
        target_h = int(H * 0.80)
        target_w = int(sw * (target_h / sh))

    src_resized = src.resize((target_w, target_h), Image.LANCZOS)
    paste_x = max(0, (W - target_w) // 2)
    paste_y = max(0, (H - target_h) // 2)
    bg.paste(src_resized, (paste_x, paste_y))
    return bg


def generate_variations(
    source_path: str | Path,
    category: str = "Other",
    save_dir: str | Path | None = None,
) -> List[Path]:
    """
    Full pipeline: bg removal → scene generation → compositing → save.

    Returns list of paths to 6 PNG frames (frame_00 = original, frames 01-05 = scenes).
    """
    source_path = Path(source_path)
    if save_dir is None:
        save_dir = Path(settings.MEDIA_ROOT) / "reel_frames"
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid4().hex[:12]
    saved_paths: List[Path] = []

    # ── Frame 0: original product on dark studio bg ───────────────────
    logger.info(f"variation_generator [{run_id}]: preparing original frame")
    original_frame = _prepare_original_frame(source_path)
    frame0_path = save_dir / f"{run_id}_frame_00_original.png"
    original_frame.save(frame0_path, "PNG")
    saved_paths.append(frame0_path)
    logger.info(f"variation_generator [{run_id}]: frame 0 saved")

    # ── Remove background ─────────────────────────────────────────────
    logger.info(f"variation_generator [{run_id}]: removing background")
    product_rgba = remove_background(source_path)
    logger.info(f"variation_generator [{run_id}]: background removed → {product_rgba.size}")

    # ── Generate scenes + composite ───────────────────────────────────
    logger.info(f"variation_generator [{run_id}]: generating {category} scenes")
    scene_results = generate_scenes(category)

    for i, (bg_img, scene) in enumerate(scene_results):
        logger.info(f"variation_generator [{run_id}]: compositing frame {i+1} — {scene.name}")
        composited = composite(
            product_rgba=product_rgba,
            background=bg_img,
            position=scene.product_position,
            add_reflection=scene.add_reflection,
            scene_name=scene.name,
        )
        # CRITICAL FIX: use slugified scene name to prevent path errors
        safe_slug = _safe_scene_slug(scene.name)
        frame_path = save_dir / f"{run_id}_frame_{i+1:02d}_{safe_slug}.png"
        composited.save(frame_path, "PNG")
        saved_paths.append(frame_path)
        logger.info(f"variation_generator [{run_id}]: frame {i+1} saved → {frame_path.name}")

    logger.info(f"variation_generator [{run_id}]: {len(saved_paths)} frames ready")
    return saved_paths
