"""
compositor.py
─────────────
Composites a transparent-background product image onto a scene background.

IMPROVEMENTS over previous version:
  • Scene-aware colour grading (warm/cool toning matched to background)
  • Rim light / edge highlight pass (simulates studio rim lamp)
  • Stronger drop shadow with ambient fill
  • Better reflection gradient fade
  • Subtle colour-match so product doesn't look pasted

Position types:
  center        — product centred, 60% frame width
  lower_center  — product centred but lower (on "floor"), 58% width
  elevated      — product higher, slightly smaller, 52% width
  macro         — product large, nearly full frame, 85% width
  wrist_left    — product smaller, left-centre (wrist context), 35% width
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw

POSITION_CONFIGS: dict[str, dict] = {
    "center": {
        "scale": 0.60, "cx": 0.50, "cy": 0.50,
        "shadow_blur": 26, "shadow_alpha": 150, "shadow_offset": (12, 20),
    },
    "lower_center": {
        "scale": 0.58, "cx": 0.50, "cy": 0.63,
        "shadow_blur": 22, "shadow_alpha": 165, "shadow_offset": (10, 16),
    },
    "elevated": {
        "scale": 0.52, "cx": 0.50, "cy": 0.40,
        "shadow_blur": 20, "shadow_alpha": 110, "shadow_offset": (8, 18),
    },
    "macro": {
        "scale": 0.84, "cx": 0.50, "cy": 0.52,
        "shadow_blur": 30, "shadow_alpha": 115, "shadow_offset": (0, 12),
    },
    "wrist_left": {
        "scale": 0.38, "cx": 0.42, "cy": 0.57,
        "shadow_blur": 15, "shadow_alpha": 105, "shadow_offset": (6, 12),
    },
}


# ── Drop shadow ───────────────────────────────────────────────────────

def _add_shadow(
    canvas: Image.Image,
    product: Image.Image,
    paste_x: int, paste_y: int,
    blur: int, alpha_val: int, offset: tuple,
) -> Image.Image:
    W, H = canvas.size
    pw, ph = product.size
    ox, oy = offset

    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_patch = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))

    prod_alpha = product.split()[3] if product.mode == "RGBA" else Image.new("L", (pw, ph), 255)
    shadow_alpha = prod_alpha.point(lambda p: min(p, alpha_val))
    shadow_patch.putalpha(shadow_alpha)
    shadow_patch = shadow_patch.filter(ImageFilter.GaussianBlur(blur))

    sx = max(0, min(paste_x + ox, W - pw))
    sy = max(0, min(paste_y + oy, H - ph))
    shadow_layer.paste(shadow_patch, (sx, sy))

    return Image.alpha_composite(canvas.convert("RGBA"), shadow_layer)


# ── Floor reflection ──────────────────────────────────────────────────

def _add_reflection(
    canvas: Image.Image,
    product: Image.Image,
    paste_x: int, paste_y: int,
) -> Image.Image:
    W, H = canvas.size
    pw, ph = product.size
    refl = product.transpose(Image.FLIP_TOP_BOTTOM)

    refl_arr = np.array(refl.convert("RGBA"), dtype=np.float32)
    rows = np.arange(ph, dtype=np.float32)
    # Fade from 55% opacity at top of reflection to 0 at 40% of height
    fade = np.clip(1.0 - rows / (ph * 0.40), 0.0, 1.0) * 0.55
    refl_arr[:, :, 3] *= fade[:, np.newaxis]
    refl = Image.fromarray(np.clip(refl_arr, 0, 255).astype(np.uint8), "RGBA")

    rx, ry = paste_x, paste_y + ph
    if ry >= H:
        return canvas
    clip_h = min(ph, H - ry)
    if clip_h <= 0:
        return canvas
    refl = refl.crop((0, 0, pw, clip_h))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(refl, (rx, ry))
    return Image.alpha_composite(canvas.convert("RGBA"), layer)


# ── Rim light (edge highlight) ────────────────────────────────────────

def _add_rim_light(
    product: Image.Image,
    scene_name: str,
) -> Image.Image:
    """
    Add a subtle rim-light highlight on the left/right edge of the product
    to simulate a studio rim lamp. Gives the product a 3-D embedded look.
    """
    name = scene_name.lower()
    prod = product.convert("RGBA")
    pw, ph = prod.size

    # Choose rim colour based on scene mood
    if any(k in name for k in ("dark", "moody", "editorial", "velvet")):
        rim_colour = (180, 200, 255, 0)   # cool blue-white rim
        rim_alpha  = 55
    elif any(k in name for k in ("marble", "white", "clean")):
        rim_colour = (255, 255, 240, 0)   # warm white rim
        rim_alpha  = 35
    elif any(k in name for k in ("warm", "amber", "city", "hero")):
        rim_colour = (255, 190, 100, 0)   # warm golden rim
        rim_alpha  = 45
    else:
        rim_colour = (220, 220, 240, 0)
        rim_alpha  = 30

    rim_layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))

    # Left-side rim gradient
    for x in range(min(pw // 8, 18)):
        alpha = int(rim_alpha * (1.0 - x / (pw // 8 + 1)) ** 1.5)
        r, g, b, _ = rim_colour
        rim_layer.paste(
            Image.new("RGBA", (1, ph), (r, g, b, alpha)), (x, 0)
        )

    # Right-side rim gradient (dimmer)
    for x in range(min(pw // 10, 12)):
        alpha = int(rim_alpha * 0.6 * (1.0 - x / (pw // 10 + 1)) ** 1.5)
        r, g, b, _ = rim_colour
        rim_layer.paste(
            Image.new("RGBA", (1, ph), (r, g, b, alpha)), (pw - 1 - x, 0)
        )

    # Mask by product alpha so rim only shows on actual product pixels
    prod_alpha = prod.split()[3]
    masked_rim = Image.composite(rim_layer, Image.new("RGBA", (pw, ph), (0, 0, 0, 0)), prod_alpha)

    return Image.alpha_composite(prod, masked_rim)


# ── Scene-aware lighting / colour grading ────────────────────────────

def _adjust_product_lighting(product: Image.Image, scene_name: str) -> Image.Image:
    """
    Apply scene-aware colour grading to the product.
    Keeps adjustments subtle so identity is fully preserved.
    """
    name = scene_name.lower()
    prod = product.convert("RGBA")
    rgb  = prod.convert("RGB")

    if any(k in name for k in ("dark", "moody", "editorial", "velvet")):
        rgb = ImageEnhance.Brightness(rgb).enhance(0.90)
        rgb = ImageEnhance.Contrast(rgb).enhance(1.10)
        # Slight cool shift
        arr = np.array(rgb, dtype=np.float32)
        arr[:, :, 2] = np.clip(arr[:, :, 2] * 1.04, 0, 255)  # boost blue
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 0.97, 0, 255)  # reduce red
        rgb = Image.fromarray(arr.astype(np.uint8), "RGB")
    elif any(k in name for k in ("marble", "white", "clean", "minimal")):
        rgb = ImageEnhance.Brightness(rgb).enhance(1.05)
        rgb = ImageEnhance.Color(rgb).enhance(0.95)
    elif any(k in name for k in ("warm", "lifestyle", "city", "hero", "amber", "boutique")):
        rgb = ImageEnhance.Color(rgb).enhance(1.07)
        rgb = ImageEnhance.Brightness(rgb).enhance(1.03)
        # Slight warm shift
        arr = np.array(rgb, dtype=np.float32)
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.04, 0, 255)  # boost red
        arr[:, :, 2] = np.clip(arr[:, :, 2] * 0.97, 0, 255)  # reduce blue
        rgb = Image.fromarray(arr.astype(np.uint8), "RGB")
    elif any(k in name for k in ("nature", "grass", "outdoor", "green")):
        rgb = ImageEnhance.Brightness(rgb).enhance(1.04)
        rgb = ImageEnhance.Color(rgb).enhance(1.05)

    # Reconstruct with original alpha
    result = prod.copy()
    result.paste(rgb.convert("RGBA"), mask=prod.split()[3])
    return result


# ── Public API ────────────────────────────────────────────────────────

def composite(
    product_rgba: Image.Image,
    background: Image.Image,
    position: str = "center",
    add_reflection: bool = False,
    scene_name: str = "",
) -> Image.Image:
    """
    Composite product_rgba (RGBA) onto background (RGB).
    Returns a finished RGB image at background's dimensions.
    """
    W, H = background.size
    cfg = POSITION_CONFIGS.get(position, POSITION_CONFIGS["center"])

    # Scale product
    prod = product_rgba.convert("RGBA")
    prod = _adjust_product_lighting(prod, scene_name)
    prod = _add_rim_light(prod, scene_name)

    orig_w, orig_h = prod.size
    target_w = int(W * cfg["scale"])
    scale_r  = target_w / orig_w
    target_h = int(orig_h * scale_r)
    # Clamp height to 88% of frame
    if target_h > int(H * 0.88):
        target_h = int(H * 0.88)
        target_w = int(orig_w * (target_h / orig_h))
    prod_scaled = prod.resize((target_w, target_h), Image.LANCZOS)

    # Paste position
    paste_x = int(W * cfg["cx"] - target_w / 2)
    paste_y = int(H * cfg["cy"] - target_h / 2)
    paste_x = max(0, min(paste_x, W - target_w))
    paste_y = max(0, min(paste_y, H - target_h))

    canvas = background.convert("RGBA")

    # Shadow
    canvas = _add_shadow(
        canvas, prod_scaled, paste_x, paste_y,
        blur=cfg["shadow_blur"],
        alpha_val=cfg["shadow_alpha"],
        offset=cfg["shadow_offset"],
    )

    # Ambient fill shadow (secondary, lighter, larger blur)
    canvas = _add_shadow(
        canvas, prod_scaled, paste_x, paste_y,
        blur=cfg["shadow_blur"] + 14,
        alpha_val=int(cfg["shadow_alpha"] * 0.35),
        offset=(cfg["shadow_offset"][0] // 2, cfg["shadow_offset"][1] * 2),
    )

    # Reflection
    if add_reflection:
        canvas = _add_reflection(canvas, prod_scaled, paste_x, paste_y)

    # Paste product
    canvas.paste(prod_scaled, (paste_x, paste_y), prod_scaled)

    return canvas.convert("RGB")
