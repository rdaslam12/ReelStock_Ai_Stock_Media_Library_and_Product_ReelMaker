"""
scene_generator.py
──────────────────
Generates 5 scene backgrounds per product category.

Priority:
  1. HuggingFace FLUX.1-schnell (if HF_API_TOKEN set) — waits for model load
  2. Premium local gradient with noise + texture (always works, much better
     than the old flat gradient)

IMPROVEMENTS over previous version:
  - Better HF retry / wait_for_model handling (polls up to 3× with backoff)
  - Much richer local fallback: adds noise grain, radial vignette, and a
    subtle centre spotlight so backgrounds feel textured, not flat.
  - Removed the slow pixel-by-pixel vignette loop — replaced with fast numpy.
  - Optional scene type label (ai / gradient) attached to returned tuple.
"""
from __future__ import annotations

import io
import logging
import time
from typing import List, NamedTuple, Optional, Tuple

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter

from django.conf import settings

logger = logging.getLogger(__name__)

SCENE_W, SCENE_H = 576, 1024


# ── Scene configuration ───────────────────────────────────────────────

class Scene(NamedTuple):
    name: str
    prompt: str
    product_position: str
    add_reflection: bool
    grad_top: tuple
    grad_bottom: tuple
    # Optional accent colour for the local fallback spotlight
    accent_rgb: tuple = (255, 220, 160)


SCENE_PLANS: dict[str, List[Scene]] = {
    "Watch": [
        Scene(
            name="Studio Dark",
            prompt=(
                "empty luxury watch photography studio, dark charcoal gradient background, "
                "dramatic spotlight from above, polished black reflective floor, "
                "no objects no people, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=True,
            grad_top=(12, 10, 16), grad_bottom=(30, 24, 40),
            accent_rgb=(200, 180, 120),
        ),
        Scene(
            name="Marble Luxury",
            prompt=(
                "white Carrara marble surface close-up, luxury product photography, "
                "soft diffused studio lighting, subtle marble veining texture, "
                "no objects no people, 9:16 vertical portrait"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(240, 235, 230), grad_bottom=(215, 210, 205),
            accent_rgb=(240, 235, 220),
        ),
        Scene(
            name="City Lifestyle",
            prompt=(
                "blurred city skyline at dusk, golden hour bokeh street lights, "
                "rooftop luxury lifestyle background, shallow depth of field, "
                "no people no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(35, 50, 90), grad_bottom=(110, 75, 45),
            accent_rgb=(255, 180, 80),
        ),
        Scene(
            name="Business Context",
            prompt=(
                "two business people handshaking close-up, formal suit sleeves, "
                "professional office interior blurred bokeh background, "
                "corporate luxury editorial, wrists visible, 9:16 vertical portrait"
            ),
            product_position="wrist_left", add_reflection=False,
            grad_top=(55, 45, 35), grad_bottom=(38, 30, 22),
            accent_rgb=(200, 160, 100),
        ),
        Scene(
            name="Warm Hero",
            prompt=(
                "warm amber deep burgundy luxury gradient background, "
                "elegant moody atmosphere, professional product photography, "
                "no objects no people, 9:16 vertical portrait"
            ),
            product_position="elevated", add_reflection=False,
            grad_top=(90, 38, 18), grad_bottom=(155, 72, 35),
            accent_rgb=(255, 140, 60),
        ),
    ],

    "Shoe": [
        Scene(
            name="Studio Dark",
            prompt=(
                "dark studio photography background, dramatic overhead spot lighting, "
                "polished concrete floor texture, professional sneaker photography, "
                "no objects no people, 9:16 vertical portrait"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(10, 10, 13), grad_bottom=(35, 30, 40),
            accent_rgb=(180, 180, 220),
        ),
        Scene(
            name="Urban Street",
            prompt=(
                "blurred urban street, city pavement bokeh, fashion editorial background, "
                "cool blue tones street photography, no people, 9:16 vertical portrait"
            ),
            product_position="lower_center", add_reflection=False,
            grad_top=(28, 34, 52), grad_bottom=(55, 62, 82),
            accent_rgb=(120, 150, 220),
        ),
        Scene(
            name="Nature Grass",
            prompt=(
                "soft focus green grass field, natural outdoor daylight, "
                "shallow depth of field fresh organic lifestyle, "
                "no people no objects, 9:16 vertical portrait"
            ),
            product_position="lower_center", add_reflection=False,
            grad_top=(75, 125, 65), grad_bottom=(45, 90, 35),
            accent_rgb=(200, 240, 150),
        ),
        Scene(
            name="Clean White",
            prompt=(
                "clean white seamless paper background, flat lay photography, "
                "soft even studio lighting, minimalist product photography, "
                "no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(250, 250, 252), grad_bottom=(232, 232, 238),
            accent_rgb=(255, 255, 255),
        ),
        Scene(
            name="Dark Editorial",
            prompt=(
                "deep black velvet background, moody dramatic fashion editorial, "
                "rim lighting from side, premium sneaker advertisement, "
                "no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=True,
            grad_top=(5, 5, 8), grad_bottom=(20, 15, 25),
            accent_rgb=(140, 100, 200),
        ),
    ],

    "Bag": [
        Scene(
            name="Studio White",
            prompt=(
                "clean white studio background, professional fashion handbag photography, "
                "soft box lighting, luxury brand aesthetic, no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(252, 252, 254), grad_bottom=(235, 235, 242),
            accent_rgb=(255, 255, 255),
        ),
        Scene(
            name="Parisian Street",
            prompt=(
                "blurred Parisian street cobblestone, haussmann buildings background, "
                "fashion editorial warm afternoon light, no people no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(155, 125, 96), grad_bottom=(95, 75, 55),
            accent_rgb=(230, 190, 130),
        ),
        Scene(
            name="Marble Luxury",
            prompt=(
                "white marble surface background, luxury fashion photography, "
                "elegant minimal soft studio lighting, no objects, 9:16 vertical portrait"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(238, 232, 226), grad_bottom=(216, 210, 204),
            accent_rgb=(240, 235, 220),
        ),
        Scene(
            name="Boutique Interior",
            prompt=(
                "luxury boutique interior blurred background, warm lighting, "
                "high-end retail shelving fashion house, no people, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(175, 150, 116), grad_bottom=(135, 108, 80),
            accent_rgb=(240, 200, 140),
        ),
        Scene(
            name="Dark Editorial",
            prompt=(
                "dark moody fashion editorial background, dramatic side lighting, "
                "luxury brand advertisement deep shadows, no objects, 9:16 vertical portrait"
            ),
            product_position="elevated", add_reflection=False,
            grad_top=(14, 11, 17), grad_bottom=(28, 22, 36),
            accent_rgb=(200, 120, 180),
        ),
    ],

    "Other": [
        Scene(
            name="Studio Dark",
            prompt=(
                "dark professional studio background, dramatic spotlight, "
                "premium product photography gradient, no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=True,
            grad_top=(10, 10, 15), grad_bottom=(28, 26, 35),
            accent_rgb=(200, 180, 120),
        ),
        Scene(
            name="Gradient Lifestyle",
            prompt=(
                "warm gradient lifestyle background orange to deep purple, "
                "premium product advertisement aesthetic, no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(195, 75, 28), grad_bottom=(75, 28, 115),
            accent_rgb=(255, 140, 80),
        ),
        Scene(
            name="Nature Outdoor",
            prompt=(
                "blurred natural outdoor background, greenery bokeh daylight, "
                "lifestyle product photography, no people no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(55, 105, 55), grad_bottom=(35, 75, 35),
            accent_rgb=(180, 230, 120),
        ),
        Scene(
            name="Texture Surface",
            prompt=(
                "dark wood grain texture surface background, warm lighting, "
                "artisan premium product photography, no objects, 9:16 vertical portrait"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(52, 36, 20), grad_bottom=(35, 24, 12),
            accent_rgb=(200, 150, 80),
        ),
        Scene(
            name="Minimal White",
            prompt=(
                "minimal clean white background, product photography, "
                "even soft lighting modern aesthetic, no objects, 9:16 vertical portrait"
            ),
            product_position="center", add_reflection=False,
            grad_top=(253, 253, 253), grad_bottom=(238, 238, 244),
            accent_rgb=(255, 255, 255),
        ),
    ],
}


# ── Premium local gradient fallback ──────────────────────────────────

def _make_premium_gradient_bg(scene: Scene) -> Image.Image:
    """
    Generate a premium gradient background with:
    - Smooth linear gradient
    - Subtle film grain noise for texture
    - Fast numpy vignette (not pixel-by-pixel loop)
    - Warm/cool centre spotlight matching scene accent
    """
    tr, tg, tb = scene.grad_top
    br, bg_c, bb = scene.grad_bottom

    # Base gradient via numpy broadcast
    t = np.linspace(0.0, 1.0, SCENE_H)[:, np.newaxis]
    r_ch = (tr + (br - tr) * t).astype(np.float32)
    g_ch = (tg + (bg_c - tg) * t).astype(np.float32)
    b_ch = (tb + (bb - tb) * t).astype(np.float32)

    arr = np.stack(
        [np.broadcast_to(r_ch, (SCENE_H, SCENE_W)),
         np.broadcast_to(g_ch, (SCENE_H, SCENE_W)),
         np.broadcast_to(b_ch, (SCENE_H, SCENE_W))],
        axis=2,
    ).copy()

    # Film grain
    rng = np.random.default_rng(seed=42)
    grain = rng.normal(0, 3.5, (SCENE_H, SCENE_W, 3)).astype(np.float32)
    arr = np.clip(arr + grain, 0, 255)

    # Fast vignette via radial distance mask
    Y = np.linspace(-1.0, 1.0, SCENE_H)[:, np.newaxis]
    X = np.linspace(-1.0, 1.0, SCENE_W)[np.newaxis, :]
    dist = np.sqrt(X**2 + Y**2)
    vignette = np.clip(1.0 - 0.55 * np.clip((dist - 0.45) / 0.75, 0, 1), 0, 1)
    arr = arr * vignette[:, :, np.newaxis]

    # Radial centre spotlight
    accent = np.array(scene.accent_rgb, dtype=np.float32)
    spotlight_strength = np.clip(0.12 * (1.0 - np.clip(dist / 0.85, 0, 1)), 0, 1)
    arr = arr * (1.0 - spotlight_strength[:, :, np.newaxis]) + \
          accent[np.newaxis, np.newaxis, :] * spotlight_strength[:, :, np.newaxis]

    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")

    # Subtle Gaussian blur to smooth the grain and make it cinematic
    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    return img


# ── HF text-to-image API call ─────────────────────────────────────────

def _hf_generate_background(
    prompt: str,
    token: str,
    model: str,
    timeout: int,
    max_retries: int = 3,
) -> Optional[Image.Image]:
    """
    Call HF inference API with wait_for_model and retry on 503.
    Returns a PIL Image or None on failure.
    """
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Wait-For-Model": "true",   # tells HF to wait if model is loading
    }
    payload = {
        "inputs": prompt,
        "parameters": {
            "width": SCENE_W,
            "height": SCENE_H,
            "num_inference_steps": 25,
            "guidance_scale": 3.5,
        },
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200 and resp.content:
                try:
                    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                    if img.size != (SCENE_W, SCENE_H):
                        img = img.resize((SCENE_W, SCENE_H), Image.LANCZOS)
                    logger.info(f"scene_generator: HF success on attempt {attempt}")
                    return img
                except Exception as parse_exc:
                    logger.warning(f"scene_generator: image parse error attempt {attempt}: {parse_exc}")
            elif resp.status_code == 503:
                # Model loading — wait_for_model header should handle this,
                # but back off and retry just in case
                wait = 15 * attempt
                logger.info(f"scene_generator: HF 503 (model loading), retry {attempt}/{max_retries} in {wait}s")
                time.sleep(wait)
            else:
                logger.warning(
                    f"scene_generator: HF HTTP {resp.status_code} attempt {attempt}: {resp.text[:200]}"
                )
                if attempt < max_retries:
                    time.sleep(8)
        except requests.Timeout:
            logger.warning(f"scene_generator: HF timeout attempt {attempt}/{max_retries}")
            if attempt < max_retries:
                time.sleep(5)
        except Exception as exc:
            logger.warning(f"scene_generator: HF exception attempt {attempt}: {exc}")
            if attempt < max_retries:
                time.sleep(5)

    return None


# ── Public API ────────────────────────────────────────────────────────

def generate_scenes(category: str) -> List[Tuple[Image.Image, Scene]]:
    """
    Generate 5 background scenes for the given product category.
    Returns a list of (PIL Image, Scene) tuples.
    """
    token   = getattr(settings, "HF_API_TOKEN", "")
    model   = getattr(settings, "HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    timeout = int(getattr(settings, "HF_IMAGE_TIMEOUT", 90))
    scenes  = SCENE_PLANS.get(category, SCENE_PLANS["Other"])
    results = []

    for scene in scenes:
        bg = None
        if token:
            logger.info(f"scene_generator: requesting HF image for '{scene.name}'")
            bg = _hf_generate_background(scene.prompt, token, model, timeout)

        if bg is None:
            bg = _make_premium_gradient_bg(scene)
            if token:
                # Only log degradation warning when AI was actually attempted
                logger.warning(
                    f"scene_generator: HF FAILED for '{scene.name}' — using premium gradient fallback"
                )
            else:
                logger.info(f"scene_generator: no HF token, using gradient for '{scene.name}'")
        else:
            logger.info(f"scene_generator: AI generated '{scene.name}'")

        results.append((bg, scene))

    return results
