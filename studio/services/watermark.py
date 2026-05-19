from __future__ import annotations

import logging
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

WATERMARK_TEXT = "R"
WATERMARK_OPACITY = 0.30
WATERMARK_COLOR = (255, 255, 255)


def _load_watermark_font(size: int) -> ImageFont.ImageFont:
    for font_name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def apply_image_watermark(image: Image.Image) -> Image.Image:
    """
    Add a small white "R" watermark at 30% opacity.

    The helper works on a copy and returns an RGBA image so callers can choose
    the final output mode/format that matches their storage target.
    """
    base = image.convert("RGBA")
    width, height = base.size
    min_side = max(1, min(width, height))
    font_size = max(12, int(min_side * 0.045))
    margin = max(6, int(min_side * 0.022))
    alpha = int(255 * WATERMARK_OPACITY)

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _load_watermark_font(font_size)
    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = width - text_width - margin - bbox[0]
    y = height - text_height - margin - bbox[1]

    draw.text(
        (x, y),
        WATERMARK_TEXT,
        font=font,
        fill=(*WATERMARK_COLOR, alpha),
    )
    return Image.alpha_composite(base, layer)


def watermark_image_bytes(image_bytes: bytes, image_format: str) -> bytes:
    image_format = (image_format or "PNG").upper()
    if image_format == "JPG":
        image_format = "JPEG"

    with Image.open(BytesIO(image_bytes)) as image:
        watermarked = apply_image_watermark(image)
        if image_format in {"JPEG", "WEBP"}:
            watermarked = watermarked.convert("RGB")

        output = BytesIO()
        watermarked.save(output, format=image_format)
        return output.getvalue()


def watermark_video_file(video_path: str | Path) -> bool:
    """
    Apply the same small "R" watermark to a generated MP4 using ffmpeg.

    Returns True when the file was replaced with a watermarked copy. If ffmpeg
    is unavailable or drawtext fails, the original file is left untouched.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    if not ffmpeg:
        logger.warning("watermark: ffmpeg not available; video watermark skipped for %s", video_path)
        return False

    path = Path(video_path)
    if not path.exists():
        logger.warning("watermark: video file does not exist: %s", path)
        return False

    output_path = path.with_name(f".{path.stem}_watermarked{path.suffix}")
    filter_expr = (
        "drawtext=text='R':fontcolor=white@0.30:fontsize=28:"
        "x=w-tw-18:y=h-th-18"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-vf",
        filter_expr,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=180)
        output_path.replace(path)
        return True
    except Exception as exc:
        logger.warning("watermark: video watermark failed for %s: %s", path, exc)
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
