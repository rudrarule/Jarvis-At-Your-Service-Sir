"""Best-effort OCR support for selected overlay captures."""
from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError


class OverlayOcrUnavailable(RuntimeError):
    """Raised when no local OCR backend is installed."""


def extract_overlay_text(image_bytes: bytes) -> dict[str, Any]:
    """Extract text from an uploaded image if pytesseract is available."""
    try:
        import pytesseract
    except ImportError as exc:
        raise OverlayOcrUnavailable("Local OCR is not installed. Install pytesseract and Tesseract OCR to enable this fast path.") from exc

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("L")
            text = pytesseract.image_to_string(image).strip()
    except UnidentifiedImageError as exc:
        raise ValueError("Selected region capture is not a valid image.") from exc

    return {
        "text": text,
        "engine": "pytesseract",
        "character_count": len(text),
        "available": True,
    }
