"""
scene_generator.py
──────────────────
Generates 5 empty studio background plates per product category.

Priority:
  1. HuggingFace FLUX.1-schnell (if HF_API_TOKEN set) — waits for model load
  2. Premium local gradient with noise + texture (always works, much better
     than the old flat gradient)

IMPROVEMENTS over previous version:
  - Uses Hugging Face InferenceClient with provider="auto", matching the
    working image generator flow.
  - Much richer local fallback: adds noise grain, radial vignette, and a
    subtle centre spotlight so backgrounds feel textured, not flat.
  - Removed the slow pixel-by-pixel vignette loop — replaced with fast numpy.
  - Optional scene type label (ai / gradient) attached to returned tuple.
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import List, NamedTuple, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError

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


BACKGROUND_PROMPT_RULES = (
    "Background only. Empty background plate. Keep the center empty for later compositing. "
    "No shoe. No sneaker. No bag. No watch. No product. No object. No person. "
    "No text. No logo. 9:16 vertical portrait."
)


def _empty_plate_prompt(style_prompt: str) -> str:
    """
    Wrap every text-to-image request with strict empty-plate constraints.

    The style prompt describes only the room, floor, wall, light, atmosphere,
    and camera feel. Product words are reserved for the negative constraints
    in BACKGROUND_PROMPT_RULES so the generator does not create duplicate
    foreground items before compositing.
    """
    return f"{style_prompt.strip().rstrip('.')}. {BACKGROUND_PROMPT_RULES}"


SCENE_PLANS: dict[str, List[Scene]] = {
    "Watch": [
        Scene(
            name="Dark Spotlight Studio",
            prompt=_empty_plate_prompt(
                "premium indoor dark charcoal studio, dramatic overhead spotlight, "
                "polished black reflective floor, soft falloff, clean empty center"
            ),
            product_position="center", add_reflection=True,
            grad_top=(12, 10, 16), grad_bottom=(30, 24, 40),
            accent_rgb=(200, 180, 120),
        ),
        Scene(
            name="Minimal Marble Studio",
            prompt=_empty_plate_prompt(
                "premium indoor white marble floor studio, subtle marble veining, "
                "soft diffused box lighting, clean wall sweep, empty center"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(240, 235, 230), grad_bottom=(215, 210, 205),
            accent_rgb=(240, 235, 220),
        ),
        Scene(
            name="Glossy Black Stage",
            prompt=_empty_plate_prompt(
                "premium indoor glossy black stage, controlled rim lighting, "
                "deep charcoal wall, subtle floor reflection, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(35, 50, 90), grad_bottom=(110, 75, 45),
            accent_rgb=(255, 180, 80),
        ),
        Scene(
            name="Soft Fog Spotlight Studio",
            prompt=_empty_plate_prompt(
                "premium indoor studio with soft atmospheric fog, narrow spotlight beam, "
                "matte graphite floor, gentle haze, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(55, 45, 35), grad_bottom=(38, 30, 22),
            accent_rgb=(200, 160, 100),
        ),
        Scene(
            name="Warm Minimal Studio",
            prompt=_empty_plate_prompt(
                "premium indoor warm amber studio, deep burgundy gradient wall, "
                "smooth matte floor, elegant moody atmosphere, empty center"
            ),
            product_position="elevated", add_reflection=False,
            grad_top=(90, 38, 18), grad_bottom=(155, 72, 35),
            accent_rgb=(255, 140, 60),
        ),
    ],

    "Shoe": [
        Scene(
            name="Dark Spotlight Studio",
            prompt=_empty_plate_prompt(
                "premium indoor dark spotlight studio, dramatic overhead light, "
                "charcoal wall sweep, polished concrete floor texture, empty center"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(10, 10, 13), grad_bottom=(35, 30, 40),
            accent_rgb=(180, 180, 220),
        ),
        Scene(
            name="Textured Floor Studio",
            prompt=_empty_plate_prompt(
                "premium indoor textured concrete floor studio, cool blue-gray wall, "
                "wide softbox glow, subtle floor scuffs, empty center"
            ),
            product_position="lower_center", add_reflection=False,
            grad_top=(28, 34, 52), grad_bottom=(55, 62, 82),
            accent_rgb=(120, 150, 220),
        ),
        Scene(
            name="Glossy Black Stage",
            prompt=_empty_plate_prompt(
                "premium indoor glossy black stage, mirror-like floor reflection, "
                "thin side rim light, deep shadowed wall, empty center"
            ),
            product_position="lower_center", add_reflection=False,
            grad_top=(8, 8, 12), grad_bottom=(28, 26, 34),
            accent_rgb=(160, 180, 255),
        ),
        Scene(
            name="Minimal Concrete Studio",
            prompt=_empty_plate_prompt(
                "premium indoor minimal concrete studio, light gray seamless wall, "
                "soft even studio lighting, matte floor, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(250, 250, 252), grad_bottom=(232, 232, 238),
            accent_rgb=(255, 255, 255),
        ),
        Scene(
            name="Soft Fog Spotlight Studio",
            prompt=_empty_plate_prompt(
                "premium indoor soft fog spotlight studio, black velvet wall, "
                "controlled side rim lighting, cinematic haze, empty center"
            ),
            product_position="center", add_reflection=True,
            grad_top=(5, 5, 8), grad_bottom=(20, 15, 25),
            accent_rgb=(140, 100, 200),
        ),
    ],

    "Bag": [
        Scene(
            name="Minimal White Studio",
            prompt=_empty_plate_prompt(
                "premium indoor clean white studio, soft box lighting, seamless wall, "
                "light matte floor, refined quiet atmosphere, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(252, 252, 254), grad_bottom=(235, 235, 242),
            accent_rgb=(255, 255, 255),
        ),
        Scene(
            name="Warm Boutique Studio",
            prompt=_empty_plate_prompt(
                "premium indoor warm boutique studio, softly blurred shelving shapes, "
                "cream wall panels, polished floor, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(155, 125, 96), grad_bottom=(95, 75, 55),
            accent_rgb=(230, 190, 130),
        ),
        Scene(
            name="Marble Floor Studio",
            prompt=_empty_plate_prompt(
                "premium indoor white marble floor studio, elegant minimal wall sweep, "
                "soft studio lighting, faint reflection, empty center"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(238, 232, 226), grad_bottom=(216, 210, 204),
            accent_rgb=(240, 235, 220),
        ),
        Scene(
            name="Textured Floor Studio",
            prompt=_empty_plate_prompt(
                "premium indoor textured taupe floor studio, warm overhead lighting, "
                "subtle wall texture, soft shadow zone, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(175, 150, 116), grad_bottom=(135, 108, 80),
            accent_rgb=(240, 200, 140),
        ),
        Scene(
            name="Dark Editorial Studio",
            prompt=_empty_plate_prompt(
                "premium indoor dark moody studio, dramatic side lighting, "
                "deep shadows, black matte wall, empty center"
            ),
            product_position="elevated", add_reflection=False,
            grad_top=(14, 11, 17), grad_bottom=(28, 22, 36),
            accent_rgb=(200, 120, 180),
        ),
    ],

    "Other": [
        Scene(
            name="Dark Spotlight Studio",
            prompt=_empty_plate_prompt(
                "premium indoor dark professional studio, dramatic spotlight, "
                "smooth charcoal gradient wall, polished floor, empty center"
            ),
            product_position="center", add_reflection=True,
            grad_top=(10, 10, 15), grad_bottom=(28, 26, 35),
            accent_rgb=(200, 180, 120),
        ),
        Scene(
            name="Warm Gradient Studio",
            prompt=_empty_plate_prompt(
                "premium indoor warm gradient studio, orange to deep purple wall, "
                "soft spotlight, matte floor, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(195, 75, 28), grad_bottom=(75, 28, 115),
            accent_rgb=(255, 140, 80),
        ),
        Scene(
            name="Soft Fog Spotlight Studio",
            prompt=_empty_plate_prompt(
                "premium indoor studio with soft atmospheric fog, focused spotlight, "
                "cool graphite floor, clean negative space, empty center"
            ),
            product_position="center", add_reflection=False,
            grad_top=(32, 36, 44), grad_bottom=(18, 20, 28),
            accent_rgb=(180, 205, 240),
        ),
        Scene(
            name="Textured Floor Studio",
            prompt=_empty_plate_prompt(
                "premium indoor dark textured floor studio, warm controlled lighting, "
                "subtle wall texture, empty center"
            ),
            product_position="lower_center", add_reflection=True,
            grad_top=(52, 36, 20), grad_bottom=(35, 24, 12),
            accent_rgb=(200, 150, 80),
        ),
        Scene(
            name="Minimal White Studio",
            prompt=_empty_plate_prompt(
                "premium indoor minimal clean white studio, even soft lighting, "
                "modern seamless wall and floor, empty center"
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
    client: InferenceClient,
    model: str,
) -> Optional[Image.Image]:
    """
    Call Hugging Face through the current InferenceClient flow.

    This matches the working Generate page provider instead of the older raw
    api-inference endpoint, which can fail for provider-routed FLUX models.
    Returns a PIL Image or None on failure.
    """
    try:
        image = client.text_to_image(
            prompt=prompt,
            model=model,
            width=SCENE_W,
            height=SCENE_H,
            num_inference_steps=20,
        )

        if isinstance(image, Image.Image):
            img = image.convert("RGB")
        elif isinstance(image, bytes):
            img = Image.open(BytesIO(image)).convert("RGB")
        else:
            logger.warning(f"scene_generator: HF returned unsupported image type: {type(image)!r}")
            return None

        if img.size != (SCENE_W, SCENE_H):
            img = img.resize((SCENE_W, SCENE_H), Image.LANCZOS)

        logger.info("scene_generator: HF image generated successfully")
        return img
    except InferenceTimeoutError as exc:
        logger.warning(f"scene_generator: HF timeout: {exc}")
    except HfHubHTTPError as exc:
        logger.warning(f"scene_generator: HF HTTP error: {exc}")
    except Exception as exc:
        logger.warning(f"scene_generator: HF exception: {exc}")

    return None


# ── Public API ────────────────────────────────────────────────────────

def generate_scenes(category: str) -> List[Tuple[Image.Image, Scene]]:
    """
    Generate 5 background scenes for the given product category.
    Returns a list of (PIL Image, Scene) tuples.
    """
    token   = getattr(settings, "HF_API_TOKEN", "").strip()
    model   = getattr(settings, "HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    timeout = int(getattr(settings, "HF_IMAGE_TIMEOUT", 90))
    scenes  = SCENE_PLANS.get(category, SCENE_PLANS["Other"])
    results = []
    client  = None

    if token:
        client = InferenceClient(
            provider="auto",
            api_key=token,
            timeout=timeout,
        )

    for scene in scenes:
        bg = None
        if client:
            logger.info(
                f"scene_generator: requesting HF image for '{scene.name}' using model '{model}'"
            )
            logger.debug(
                "scene_generator: final empty-plate background prompt for '%s': %s",
                scene.name,
                scene.prompt,
            )
            logger.debug(
                "scene_generator: using text-to-image only for '%s'; uploaded product image is not passed to background generation",
                scene.name,
            )
            bg = _hf_generate_background(scene.prompt, client, model)

        if bg is None:
            bg = _make_premium_gradient_bg(scene)
            if token:
                # Only log degradation warning when AI was actually attempted
                logger.warning(
                    f"scene_generator: HF FAILED for '{scene.name}' — using premium gradient fallback"
                )
            else:
                logger.info(f"scene_generator: no HF token, using gradient for '{scene.name}'")
                logger.debug(
                    "scene_generator: fallback gradient used for '%s' with empty-plate prompt: %s",
                    scene.name,
                    scene.prompt,
                )
        else:
            logger.info(f"scene_generator: AI generated '{scene.name}'")

        results.append((bg, scene))

    return results
