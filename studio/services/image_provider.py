"""
Small image generation helper for the Generate page.

The goal here is to keep the provider logic isolated from the view so it is
easy to swap to another API later without rewriting the page flow.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Dict, Tuple
from uuid import uuid4

from django.conf import settings
from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError

from .watermark import watermark_image_bytes


class ImageGenerationError(Exception):
    """Raised when the external image provider cannot return an image."""


class HuggingFaceImageProvider:
    """
    Minimal Hugging Face text-to-image provider.

    It accepts a prompt, generates an image through Hugging Face's current
    InferenceClient flow, saves the returned image into MEDIA_ROOT/generated/,
    and returns the image URL that the frontend can preview.
    """

    def __init__(self) -> None:
        self.api_token = getattr(settings, "HF_API_TOKEN", "")
        self.model = getattr(
            settings,
            "HF_IMAGE_MODEL",
            "black-forest-labs/FLUX.1-schnell",
        )
        self.timeout = getattr(settings, "HF_IMAGE_TIMEOUT", 60)
        self.client = InferenceClient(
            provider="auto",
            api_key=self.api_token,
            timeout=self.timeout,
        )

    def generate_image(self, prompt: str, style: str, aspect_ratio: str) -> Dict[str, str]:
        if not self.api_token:
            raise ImageGenerationError(
                "Image generation is not configured yet. Set the HF_API_TOKEN environment variable and try again."
            )

        width, height = self._dimensions_for_ratio(aspect_ratio)
        full_prompt = self._build_prompt(prompt, style)
        image_bytes, content_type = self._request_image(
            prompt=full_prompt,
            width=width,
            height=height,
        )
        image_url = self._save_image(image_bytes=image_bytes, content_type=content_type)

        return {
            "image_url": image_url,
            "prompt_used": full_prompt,
        }

    def _build_prompt(self, prompt: str, style: str) -> str:
        """
        Add a small style hint without making the code or prompt logic complex.
        """
        if style:
            return f"{prompt}, {style} style"
        return prompt

    def _dimensions_for_ratio(self, aspect_ratio: str) -> Tuple[int, int]:
        """
        Keep sizes modest so demo requests stay lightweight and fast.
        """
        dimension_map = {
            "1:1": (768, 768),
            "16:9": (1024, 576),
            "9:16": (576, 1024),
        }
        return dimension_map.get(aspect_ratio, (768, 768))

    def _request_image(self, prompt: str, width: int, height: int) -> Tuple[bytes, str]:
        """
        Call Hugging Face's current text-to-image inference client.
        """
        try:
            image = self.client.text_to_image(
                prompt=prompt,
                model=self.model,
                width=width,
                height=height,
                num_inference_steps=20,
            )
            return self._image_to_bytes(image)
        except InferenceTimeoutError as exc:
            raise ImageGenerationError(
                "The image provider timed out while generating your image. Please try again in a moment."
            ) from exc
        except HfHubHTTPError as exc:
            provider_message = str(exc).strip() or "The image provider could not generate an image right now."
            raise ImageGenerationError(f"Image generation failed: {provider_message}") from exc
        except Exception as exc:
            raise ImageGenerationError(f"Image generation failed: {exc}") from exc
    def _image_to_bytes(self, image) -> Tuple[bytes, str]:
        buffer = BytesIO()
        image_format = (getattr(image, "format", None) or "PNG").upper()

        if image_format == "JPEG":
            content_type = "image/jpeg"
        elif image_format == "WEBP":
            content_type = "image/webp"
        else:
            image_format = "PNG"
            content_type = "image/png"

        image.save(buffer, format=image_format)
        return buffer.getvalue(), content_type

    def _save_image(self, image_bytes: bytes, content_type: str) -> str:
        extension = self._extension_from_content_type(content_type)
        image_format = self._format_from_content_type(content_type)

        output_dir = Path(settings.MEDIA_ROOT) / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{uuid4().hex}{extension}"
        output_path = output_dir / filename
        image_bytes = watermark_image_bytes(image_bytes, image_format)
        output_path.write_bytes(image_bytes)

        return f"{settings.MEDIA_URL}generated/{filename}"

    def _extension_from_content_type(self, content_type: str) -> str:
        content_type = (content_type or "").lower()

        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
        if "webp" in content_type:
            return ".webp"
        return ".png"

    def _format_from_content_type(self, content_type: str) -> str:
        content_type = (content_type or "").lower()

        if "jpeg" in content_type or "jpg" in content_type:
            return "JPEG"
        if "webp" in content_type:
            return "WEBP"
        return "PNG"
