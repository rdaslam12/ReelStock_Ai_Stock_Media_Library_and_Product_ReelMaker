"""
reel_assembler.py
─────────────────
Assembles a list of PIL Images into a polished 9:16 MP4 reel using
OpenCV + Pillow. Zero external API calls.

MAJOR IMPROVEMENTS over previous version:
  • Richer transition library:
      - blur_fade       (Gaussian blur cross-dissolve)
      - whip_pan        (horizontal slide wipe)
      - zoom_morph      (push-in zoom dissolve)
      - flash_cut       (brief white flash, hard cut)
      - iris_fade       (standard smoothstep crossfade)
  • Transitions cycle through the library per-cut for variety
  • Stronger Ken Burns: deeper zooms, more axis movement
  • Opening fade-in from black (0.4s)
  • Closing fade-out to black (0.3s)
  • Vignette computed with fast numpy (not per-pixel loop)
  • Subtle letterbox / cinematic bars removed (full bleed looks better)
"""
from __future__ import annotations

import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from django.conf import settings

from .watermark import apply_image_watermark

logger = logging.getLogger(__name__)

OUTPUT_FPS        = 24
HOLD_DURATION     = 1.6    # seconds per shot
TRANSITION_FRAMES = 16     # ~0.67 s
OUTPUT_SIZE       = (576, 1024)   # 9:16


# ── Ken Burns shot plans ──────────────────────────────────────────────
# (z_start, z_end, pan_x_start, pan_x_end, pan_y_start, pan_y_end)
SHOT_PLANS: List[Tuple] = [
    (1.00, 1.10,  0.00,  0.00,  0.00, -0.08),  # push-in, drift up
    (1.12, 1.00,  0.08, -0.04,  0.00,  0.00),  # pull-back + pan left
    (1.04, 1.18, -0.10,  0.05,  0.00,  0.00),  # pan right + push-in
    (1.18, 1.06,  0.00,  0.00,  0.10, -0.05),  # drift down + pull-back
    (1.00, 1.14,  0.00,  0.00, -0.06,  0.06),  # push-in + tilt down
    (1.10, 1.00, -0.06,  0.06,  0.00,  0.00),  # pull-wide + pan right
]

# Transition sequence — cycles for each cut
TRANSITION_SEQUENCE = [
    "zoom_morph",
    "whip_pan",
    "blur_fade",
    "flash_cut",
    "iris_fade",
]


def _pil_to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _bgr_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _fit_and_crop(img: Image.Image, W: int, H: int) -> Image.Image:
    sw, sh = img.size
    scale  = max(W / sw, H / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    img    = img.resize((nw, nh), Image.LANCZOS)
    left   = (nw - W) // 2
    top    = (nh - H) // 2
    return img.crop((left, top, left + W, top + H))


def _ken_burns(img: Image.Image, zoom: float, px: float, py: float) -> Image.Image:
    w, h = img.size
    cw = max(1, int(w / zoom))
    ch = max(1, int(h / zoom))
    cx = int((w - cw) * np.clip(0.5 + px * 0.5, 0.0, 1.0))
    cy = int((h - ch) * np.clip(0.5 + py * 0.5, 0.0, 1.0))
    cx = max(0, min(cx, w - cw))
    cy = max(0, min(cy, h - ch))
    return img.crop((cx, cy, cx + cw, cy + ch)).resize((w, h), Image.LANCZOS)


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4 * t * t * t
    p = 2 * t - 2
    return 0.5 * p * p * p + 1.0


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _make_vignette(W: int, H: int, strength: float = 0.32) -> np.ndarray:
    Y = np.linspace(-1, 1, H)[:, np.newaxis]
    X = np.linspace(-1, 1, W)[np.newaxis, :]
    dist = np.sqrt(X**2 + Y**2).astype(np.float32)
    mask = 1.0 - strength * np.clip((dist - 0.50) / 0.70, 0, 1)
    return np.stack([mask, mask, mask], axis=2)


# ── Transition renderers ──────────────────────────────────────────────

def _trans_iris_fade(
    a: Image.Image, b: Image.Image, n: int
) -> List[Image.Image]:
    """Standard smooth crossfade."""
    frames = []
    for f in range(n):
        alpha = _smoothstep(f / n)
        frames.append(Image.blend(a, b, alpha))
    return frames


def _trans_blur_fade(
    a: Image.Image, b: Image.Image, n: int
) -> List[Image.Image]:
    """Gaussian blur dissolve — blurs A out, blurs B in."""
    frames = []
    for f in range(n):
        t = f / n
        alpha = _smoothstep(t)
        blur_r = _smoothstep(min(t * 2.0, 1.0)) * 6.0
        a_blurred = a.filter(ImageFilter.GaussianBlur(blur_r)) if blur_r > 0.3 else a
        b_blurred = b.filter(ImageFilter.GaussianBlur(max(0, 6.0 - blur_r * 6.0))) if (6.0 - blur_r * 6.0) > 0.3 else b
        frames.append(Image.blend(a_blurred, b_blurred, alpha))
    return frames


def _trans_whip_pan(
    a: Image.Image, b: Image.Image, n: int
) -> List[Image.Image]:
    """Horizontal slide wipe — A slides left, B slides in from right."""
    W, H = a.size
    frames = []
    for f in range(n):
        t   = _smoothstep(f / n)
        off = int(t * W)
        canvas = Image.new("RGB", (W, H))
        # A sliding out left
        a_crop = a.crop((off, 0, W, H))
        canvas.paste(a_crop, (0, 0))
        # B sliding in from right
        if off > 0:
            b_crop = b.crop((0, 0, off, H))
            canvas.paste(b_crop, (W - off, 0))
        # Slight motion blur on the seam
        frames.append(canvas)
    return frames


def _trans_zoom_morph(
    a: Image.Image, b: Image.Image, n: int
) -> List[Image.Image]:
    """Push-in zoom dissolve — A zooms in while B fades in."""
    W, H = a.size
    frames = []
    for f in range(n):
        t     = f / n
        alpha = _smoothstep(t)
        zoom  = 1.0 + t * 0.12   # zoom A in
        a_zoomed = _ken_burns(a, zoom, 0, 0)
        frames.append(Image.blend(a_zoomed, b, alpha))
    return frames


def _trans_flash_cut(
    a: Image.Image, b: Image.Image, n: int
) -> List[Image.Image]:
    """Brief white flash then hard cut — energetic, use sparingly."""
    W, H = a.size
    white = Image.new("RGB", (W, H), (250, 250, 250))
    frames = []
    mid = max(1, n // 3)
    # Flash up
    for f in range(mid):
        t = f / mid
        frames.append(Image.blend(a, white, _smoothstep(t)))
    # Flash down into B
    for f in range(n - mid):
        t = f / (n - mid)
        frames.append(Image.blend(white, b, _smoothstep(t)))
    return frames


TRANSITION_FNS = {
    "iris_fade":  _trans_iris_fade,
    "blur_fade":  _trans_blur_fade,
    "whip_pan":   _trans_whip_pan,
    "zoom_morph": _trans_zoom_morph,
    "flash_cut":  _trans_flash_cut,
}


def title_for_category(category: str | None) -> str:
    """Return the tasteful title rendered over the final reel."""
    normalized = (category or "").strip().lower()
    if normalized == "shoe":
        return "Stylish Shoe"
    if normalized == "watch":
        return "Luxury Watch"
    if normalized == "bag":
        return "Elegant Bag"
    if normalized:
        return f"Premium {normalized.title()}"
    return "Premium Pick"


def _allocate_frames(total: int, slots: int, minimum: int = 1) -> List[int]:
    if slots <= 0:
        return []
    total = max(total, minimum * slots)
    base = total // slots
    remainder = total % slots
    return [base + (1 if i < remainder else 0) for i in range(slots)]


def build_caption_segments(
    category: str | None,
    product_name: str | None,
    target_duration: float | None,
    style: str = "auto",
) -> List[Dict[str, Any]]:
    duration = max(float(target_duration or 6.0), 3.0)
    title = product_name or title_for_category(category)
    normalized_style = (style or "auto").strip().lower()
    mixed = normalized_style == "auto"

    def seg(text: str, start: float, end: float, preset: str, position: str = "lower"):
        return {
            "text": text,
            "start": round(max(0.0, start), 3),
            "end": round(min(duration, end), 3),
            "style": preset if mixed else normalized_style,
            "position": position,
        }

    return [
        seg(f"Meet {title}", duration * 0.05, duration * 0.34, "slide_up", "upper"),
        seg("Premium angles in motion", duration * 0.36, duration * 0.66, "karaoke", "lower"),
        seg("Ready to stand out", duration * 0.68, duration * 0.94, "punch", "lower"),
    ]


def _caption_font(size: int) -> ImageFont.ImageFont:
    return _load_overlay_font(size)


def _caption_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = text.split()
    if not words:
        return [text]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _caption_visible_text(text: str, preset: str, progress: float) -> str:
    progress = max(0.0, min(1.0, progress))
    if preset == "typewriter":
        chars = max(1, int(math.ceil(len(text) * progress)))
        return text[:chars]
    if preset == "karaoke":
        words = text.split()
        if not words:
            return text
        count = max(1, int(math.ceil(len(words) * progress)))
        return " ".join(words[:count])
    return text


def _draw_caption_segment(
    layer: Image.Image,
    segment: Dict[str, Any],
    elapsed: float,
    fps: int,
    frame_index: int,
) -> None:
    W, H = layer.size
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", start + 1.0))
    duration = max(end - start, 0.1)
    local = max(0.0, min(1.0, (elapsed - start) / duration))
    exit_t = max(0.0, min(1.0, (end - elapsed) / 0.25))
    entry = _smoothstep(min(local / 0.22, 1.0))
    alpha_ratio = min(entry, _smoothstep(exit_t))
    if alpha_ratio <= 0.01:
        return

    preset = (segment.get("style") or "fade_motion").lower()
    text = _caption_visible_text(str(segment.get("text") or ""), preset, local)
    if not text:
        return

    jitter_x = jitter_y = 0
    scale = 1.0
    y_motion = int((1.0 - entry) * 28)
    flicker = 1.0

    if preset == "bounce":
        scale = 1.0 + math.sin(min(local, 0.35) / 0.35 * math.pi) * 0.12
    elif preset == "zoom":
        scale = 0.86 + 0.14 * entry
    elif preset == "glitch":
        flicker = 0.72 + 0.28 * (1 if (frame_index // 2) % 2 == 0 else 0.55)
        jitter_x = int(math.sin(frame_index * 2.7) * 4)
        jitter_y = int(math.cos(frame_index * 1.9) * 2)
    elif preset == "punch":
        scale = 1.0 + max(0.0, 1.0 - local / 0.24) * 0.16
    elif preset == "slide_up":
        y_motion = int((1.0 - entry) * 42)
    elif preset == "fade_motion":
        y_motion = int((1.0 - entry) * 18)

    alpha = int(235 * alpha_ratio * flicker)
    font_size = max(24, int(W * 0.065 * scale))
    font = _caption_font(font_size)
    draw = ImageDraw.Draw(layer)
    max_text_w = int(W * 0.82)
    lines = _caption_lines(draw, text, font, max_text_w)
    line_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [box[3] - box[1] for box in line_boxes]
    text_w = max((box[2] - box[0] for box in line_boxes), default=0)
    text_h = sum(line_heights) + max(0, len(lines) - 1) * int(font_size * 0.24)
    pad_x = int(W * 0.045)
    pad_y = int(H * 0.014)
    x = (W - text_w) // 2 + jitter_x
    base_y = int(H * (0.18 if segment.get("position") == "upper" else 0.70))
    y = base_y + y_motion + jitter_y

    box = (
        x - pad_x,
        y - pad_y,
        x + text_w + pad_x,
        y + text_h + pad_y + 6,
    )
    draw.rounded_rectangle(
        box,
        radius=22,
        fill=(8, 10, 18, int(alpha * 0.56)),
        outline=(255, 255, 255, int(alpha * 0.18)),
        width=1,
    )

    cursor_y = y
    accent_words = {"stand", "out", "premium", "motion"}
    for line, bbox, line_h in zip(lines, line_boxes, line_heights):
        line_w = bbox[2] - bbox[0]
        line_x = (W - line_w) // 2 + jitter_x
        if preset == "glitch":
            draw.text((line_x + 3, cursor_y), line, font=font, fill=(255, 40, 120, int(alpha * 0.35)))
            draw.text((line_x - 3, cursor_y + 1), line, font=font, fill=(55, 210, 255, int(alpha * 0.35)))
        if preset == "punch" and any(word.strip(".,!?:;").lower() in accent_words for word in line.split()):
            fill = (255, 233, 138, alpha)
        else:
            fill = (255, 255, 255, alpha)
        draw.text((line_x + 1, cursor_y + 2), line, font=font, fill=(0, 0, 0, int(alpha * 0.36)))
        draw.text((line_x, cursor_y), line, font=font, fill=fill)
        cursor_y += line_h + int(font_size * 0.24)


def _add_caption_overlays(
    img: Image.Image,
    caption_segments: List[Dict[str, Any]] | None,
    frame_index: int,
    fps: int,
) -> Image.Image:
    if not caption_segments:
        return img
    elapsed = frame_index / max(fps, 1)
    active = [
        segment for segment in caption_segments
        if float(segment.get("start", 0.0)) <= elapsed <= float(segment.get("end", 0.0))
    ]
    if not active:
        return img
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    for segment in active:
        _draw_caption_segment(layer, segment, elapsed, fps, frame_index)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _load_overlay_font(size: int) -> ImageFont.ImageFont:
    for font_name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _add_text_overlay(img: Image.Image, text: str, frame_index: int, fps: int) -> Image.Image:
    """
    Add a small animated title overlay.

    Motion is a short fade/slide on entry plus a very subtle breathing lift so
    it feels alive without competing with the composited product.
    """
    if not text:
        return img

    W, H = img.size
    elapsed = frame_index / max(fps, 1)
    entry_t = min(max(elapsed / 0.75, 0.0), 1.0)
    alpha = int(230 * _smoothstep(entry_t))
    if alpha <= 0:
        return img

    slide = int((1.0 - _smoothstep(entry_t)) * 26)
    breath = int(math.sin(elapsed * math.pi * 1.2) * 2)

    font = _load_overlay_font(max(24, int(W * 0.055)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x = int(W * 0.035)
    pad_y = int(H * 0.012)
    x = (W - tw) // 2
    y = int(H * 0.115) + slide + breath

    bg_box = (
        x - pad_x,
        y - pad_y,
        x + tw + pad_x,
        y + th + pad_y + 4,
    )
    draw.rounded_rectangle(
        bg_box,
        radius=18,
        fill=(8, 8, 12, int(alpha * 0.42)),
        outline=(255, 255, 255, int(alpha * 0.16)),
        width=1,
    )
    draw.text((x + 1, y + 2), text, font=font, fill=(0, 0, 0, int(alpha * 0.40)))
    draw.text((x, y), text, font=font, fill=(255, 247, 232, alpha))

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _build_transition(
    a: Image.Image, b: Image.Image, n: int, style: str
) -> List[Image.Image]:
    fn = TRANSITION_FNS.get(style, _trans_iris_fade)
    return fn(a, b, n)


# ── Core assembler ────────────────────────────────────────────────────

def assemble_reel(
    images: List[Image.Image],
    output_path: str | Path,
    fps: int = OUTPUT_FPS,
    hold_duration: float = HOLD_DURATION,
    transition_frames: int = TRANSITION_FRAMES,
    fade_in: bool = True,
    fade_out: bool = True,
    overlay_text: str = "",
    target_duration: float | None = None,
    caption_segments: List[Dict[str, Any]] | None = None,
) -> Path:
    """
    Assemble PIL images into a cinematic MP4 reel.
    Returns Path of the written file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    W, H = OUTPUT_SIZE
    n = len(images)
    if n <= 0:
        raise ValueError("assemble_reel requires at least one image")

    if target_duration and target_duration > 0:
        total_frames = max(int(round(float(target_duration) * fps)), n + max(0, n - 1) * 2)
        transition_slots = max(0, n - 1)
        transition_total = 0
        if transition_slots:
            default_transition_total = transition_frames * transition_slots
            transition_total = min(default_transition_total, max(transition_slots * 2, int(total_frames * 0.22)))
        hold_total = total_frames - transition_total
        hold_frame_counts = _allocate_frames(hold_total, n, minimum=2)
        transition_frame_counts = _allocate_frames(transition_total, transition_slots, minimum=2) if transition_slots else []
    else:
        hold_frame_counts = [max(1, int(fps * hold_duration)) for _ in range(n)]
        transition_frame_counts = [transition_frames for _ in range(max(0, n - 1))]

    plans = [SHOT_PLANS[i % len(SHOT_PLANS)] for i in range(n)]

    fitted   = [_fit_and_crop(img, W, H) for img in images]
    vignette = _make_vignette(W, H)

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (W, H),
    )

    FADE_IN_FRAMES  = int(fps * 0.45)
    FADE_OUT_FRAMES = int(fps * 0.35)

    frame_index = 0

    def write_pil(pil_img: Image.Image, brightness: float = 1.0) -> None:
        nonlocal frame_index
        if overlay_text and not caption_segments:
            pil_img = _add_text_overlay(pil_img, overlay_text, frame_index, fps)
        pil_img = _add_caption_overlays(pil_img, caption_segments, frame_index, fps)
        pil_img = apply_image_watermark(pil_img).convert("RGB")
        bgr = _pil_to_bgr(pil_img).astype(np.float32) / 255.0
        bgr = np.clip(bgr * vignette, 0, 1)
        if brightness < 1.0:
            bgr = bgr * brightness
        writer.write((np.clip(bgr * 255, 0, 255)).astype(np.uint8))
        frame_index += 1

    # Build per-shot end frame (last KB position) for each shot
    end_frames = []
    for i, (img, plan) in enumerate(zip(fitted, plans)):
        z0, z1, px0, px1, py0, py1 = plan
        end_frames.append(_ken_burns(img, z1, px1, py1))

    for i, (img, plan) in enumerate(zip(fitted, plans)):
        z0, z1, px0, px1, py0, py1 = plan
        hold_frames = hold_frame_counts[i]
        fade_in_frames = min(FADE_IN_FRAMES, hold_frames)
        fade_out_frames = min(FADE_OUT_FRAMES, hold_frames)

        for f in range(hold_frames):
            t  = _ease(f / max(hold_frames - 1, 1))
            z  = z0  + (z1  - z0)  * t
            px = px0 + (px1 - px0) * t
            py = py0 + (py1 - py0) * t
            frame = _ken_burns(img, z, px, py)

            # Fade-in on first shot
            if fade_in and i == 0 and f < fade_in_frames:
                brightness = 0.18 + 0.82 * _smoothstep(f / max(fade_in_frames, 1))
            # Fade-out on last shot
            elif fade_out and i == n - 1 and f >= hold_frames - fade_out_frames:
                remaining = hold_frames - f
                brightness = _smoothstep(remaining / max(fade_out_frames, 1))
            else:
                brightness = 1.0

            write_pil(frame, brightness)

        # Transition to next shot
        if i < n - 1:
            trans_style = TRANSITION_SEQUENCE[i % len(TRANSITION_SEQUENCE)]
            trans_frames = _build_transition(
                end_frames[i],
                _ken_burns(fitted[i + 1], plans[i + 1][0], plans[i + 1][2], plans[i + 1][4]),
                transition_frame_counts[i],
                trans_style,
            )
            for tf in trans_frames:
                write_pil(tf)

    writer.release()
    return output_path


def _transcode_for_browser(input_path: Path, output_path: Path, target_duration: float | None = None) -> bool:
    """
    Convert OpenCV's mp4v output to H.264/yuv420p with faststart metadata.

    Browsers can load an mp4v file path but fail to decode it or show a black
    player. H.264 in MP4 is the safest target for Django-served reels.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    if not ffmpeg:
        logger.warning("reel_assembler: ffmpeg not found; keeping OpenCV mp4v output at %s", input_path)
        return False

    cmd = [
        ffmpeg,
        "-y",
        "-i", str(input_path),
        "-an",
        "-c:v", "libx264",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-preset", "veryfast",
        "-crf", "20",
    ]
    if target_duration and target_duration > 0:
        cmd.extend(["-t", f"{float(target_duration):.3f}"])
    cmd.append(str(output_path))
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        logger.debug("reel_assembler: ffmpeg transcode output: %s", result.stderr[-800:])
        return True
    except Exception as exc:
        logger.warning("reel_assembler: ffmpeg transcode failed for %s: %s", input_path, exc)
        return False


def assemble_reel_from_paths(
    image_paths: List[str | Path],
    output_path: str | Path,
    **kwargs,
) -> Path:
    images = [Image.open(p).convert("RGB") for p in image_paths]
    return assemble_reel(images, output_path, **kwargs)


def save_reel_to_media(
    image_paths: List[str | Path],
    hold_duration: float | None = None,
    overlay_text: str = "",
    target_duration: float | None = None,
    caption_style: str = "auto",
    caption_segments: List[Dict[str, Any]] | None = None,
) -> str:
    """
    Save a list of image paths into a reel under the MEDIA_ROOT/reels directory.

    Args:
        image_paths: Ordered list of frame paths (PNG/JPG) to include in the reel.
        target_duration: Optional exact total duration in seconds. When provided,
            the assembler allocates a fixed frame budget and ffmpeg clamps the
            browser-ready file to that same duration.

    Returns:
        Relative URL to the saved MP4 video, rooted at MEDIA_URL.
    """
    output_dir = Path(settings.MEDIA_ROOT) / "reels"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename    = f"reel_{uuid4().hex}.mp4"
    output_path = output_dir / filename
    raw_path = output_dir / f".{output_path.stem}_raw.mp4"
    # Pass hold_duration through to the assembler if provided
    kwargs = {}
    if hold_duration is not None and hold_duration > 0:
        kwargs["hold_duration"] = float(hold_duration)
    if target_duration is not None and target_duration > 0:
        kwargs["target_duration"] = float(target_duration)
    if caption_segments:
        kwargs["caption_segments"] = caption_segments
    if overlay_text:
        kwargs["overlay_text"] = overlay_text
    assemble_reel_from_paths(image_paths, raw_path, **kwargs)
    if _transcode_for_browser(raw_path, output_path, target_duration=target_duration):
        try:
            raw_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("reel_assembler: could not remove raw intermediate %s", raw_path)
        logger.info("reel_assembler: saved browser-compatible H.264 reel at %s", output_path)
    else:
        raw_path.replace(output_path)
        logger.info("reel_assembler: saved fallback mp4v reel at %s", output_path)
    return f"{settings.MEDIA_URL}reels/{filename}"
