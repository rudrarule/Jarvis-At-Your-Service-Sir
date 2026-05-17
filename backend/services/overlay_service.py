"""Overlay request pipeline for selected screen-region analysis."""
from __future__ import annotations

import base64
import io
import os
import time
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from services.dashboard_event_service import emit_dashboard_event
from services.overlay_context_service import (
    append_overlay_turn,
    create_overlay_context,
    get_overlay_context,
    get_overlay_context_public,
)
from services.mission_store import (
    complete_mission,
    create_mission,
    fail_mission,
    reset_current_mission_id,
    set_current_mission_id,
)


MAX_UPLOAD_BYTES = int(os.getenv("OVERLAY_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
MAX_IMAGE_EDGE = int(os.getenv("OVERLAY_MAX_IMAGE_EDGE", "1536"))
JPEG_QUALITY = int(os.getenv("OVERLAY_JPEG_QUALITY", "85"))


class OverlayCaptureRejected(ValueError):
    """Raised when a selected capture should not be sent to the model."""


async def ask_about_overlay_region(
    *,
    image_bytes: bytes,
    question: str,
    session_id: str = "overlay",
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, normalize, and analyze a selected desktop region."""
    started = time.perf_counter()
    metadata = _clean_metadata(metadata or {})
    clean_question = " ".join(question.strip().split())

    if not clean_question:
        raise OverlayCaptureRejected("Question is required.")
    if not image_bytes:
        raise OverlayCaptureRejected("Selected region capture is empty.")
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise OverlayCaptureRejected("Selected region capture is too large.")

    window_title = str(metadata.get("window_title") or "")
    if window_title and not _is_safe_to_capture(window_title):
        await emit_dashboard_event(
            "overlay.capture_blocked",
            {"reason": "sensitive_window_title", "window_title": window_title, "session_id": session_id},
            source="overlay",
            level="warning",
        )
        raise OverlayCaptureRejected(
            "Sir, I've detected what appears to be sensitive credentials on screen. I'd rather not see that. Please switch windows."
        )

    normalized = _normalize_image(image_bytes)

    # Reset standard chat session history for "overlay" to keep conversational turns isolated per crop capture
    from services.session_service import chat_sessions
    chat_sessions[session_id] = []

    await emit_dashboard_event(
        "overlay.ask_started",
        {
            "session_id": session_id,
            "question": clean_question,
            "content_type": content_type,
            **(metadata or {}),
            **normalized["stats"],
        },
        source="overlay",
    )

    from services.llm_service import generate_response
    print(f"[OVERLAY ASK ROUTING] Routing initial crop capture to generate_response: '{clean_question}'")
    reply = await generate_response(clean_question, session_id=session_id)

    elapsed_ms = round((time.perf_counter() - started) * 1000)

    context_id = create_overlay_context(
        session_id=session_id,
        question=clean_question,
        reply=reply,
        image_base64=normalized["image_base64"],
        image_stats=normalized["stats"],
        metadata=metadata or {},
        mission_id="",
    )

    await emit_dashboard_event(
        "overlay.response",
        {
            "context_id": context_id,
            "session_id": session_id,
            "reply": reply,
            "duration_ms": elapsed_ms,
            **normalized["stats"],
        },
        source="overlay",
    )

    return {
        "reply": reply,
        "context_id": context_id,
        "mission_id": "",
        "duration_ms": elapsed_ms,
        "image": normalized["stats"],
        "turns": [{"question": clean_question, "reply": reply}],
        "metadata": metadata or {},
    }


async def ask_overlay_follow_up(*, context_id: str, question: str, session_id: str = "overlay") -> dict[str, Any]:
    """Ask a follow-up question about a previous selected region using the unified multimodal graph brain."""
    started = time.perf_counter()
    clean_question = " ".join(question.strip().split())
    if not clean_question:
        raise OverlayCaptureRejected("Question is required.")

    context = get_overlay_context(context_id)
    if not context:
        raise OverlayCaptureRejected("Overlay context has expired. Please capture the region again.")

    await emit_dashboard_event(
        "overlay.followup_started",
        {"context_id": context_id, "session_id": session_id, "question": clean_question},
        source="overlay",
    )

    from services.llm_service import generate_response
    print(f"[OVERLAY FOLLOWUP ROUTING] Routing follow-up directly to generate_response: '{clean_question}'")
    reply = await generate_response(clean_question, session_id=session_id)

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    append_overlay_turn(context_id, clean_question, reply)
    public_context = get_overlay_context_public(context_id) or {}

    await emit_dashboard_event(
        "overlay.followup_response",
        {
            "context_id": context_id,
            "session_id": session_id,
            "reply": reply,
            "duration_ms": elapsed_ms,
        },
        source="overlay",
    )

    return {
        "reply": reply,
        "context_id": context_id,
        "mission_id": "",
        "duration_ms": elapsed_ms,
        "image": context.get("image", {}),
        "turns": public_context.get("turns", []),
        "metadata": context.get("metadata", {}),
    }


def _normalize_image(image_bytes: bytes) -> dict[str, Any]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            original_width, original_height = image.size

            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, (18, 22, 28))
                alpha = image.getchannel("A") if image.mode == "RGBA" else image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            if max(image.size) > MAX_IMAGE_EDGE:
                image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            normalized_bytes = buffer.getvalue()
    except UnidentifiedImageError as exc:
        raise OverlayCaptureRejected("Selected region capture is not a valid image.") from exc

    width, height = image.size
    return {
        "image_base64": base64.b64encode(normalized_bytes).decode("utf-8"),
        "stats": {
            "original_width": original_width,
            "original_height": original_height,
            "width": width,
            "height": height,
            "size_kb": round(len(normalized_bytes) / 1024, 1),
            "mime_type": "image/jpeg",
        },
    }


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if key in {"region_x", "region_y", "region_width", "region_height"}:
            cleaned[key] = int(value)
        elif key == "device_pixel_ratio":
            cleaned[key] = float(value)
        else:
            cleaned[key] = str(value)[:200]
    return cleaned


def _build_contextual_prompt(question: str, metadata: dict[str, Any]) -> str:
    context = _metadata_prompt(metadata)
    if not context:
        return question
    return f"{context}User question: {question}"


def _metadata_prompt(metadata: dict[str, Any]) -> str:
    if not metadata:
        return ""
    labels = {
        "app_name": "Application",
        "process_name": "Process",
        "window_title": "Window title",
        "screen_name": "Screen",
    }
    lines = []
    for key, label in labels.items():
        value = metadata.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if not lines:
        return ""
    return "Selected desktop context:\n" + "\n".join(lines) + "\n\n"


async def _analyze_screen_region(image_b64: str, question: str, session_id: str) -> str | None:
    from services.llm_service import analyze_screen_region

    return await analyze_screen_region(image_b64, question, session_id=session_id)


def _is_safe_to_capture(window_title: str) -> bool:
    try:
        from services.vision_service import is_safe_to_capture

        return is_safe_to_capture(window_title)
    except Exception:
        sensitive_keywords = [
            "password",
            "1password",
            "bitwarden",
            "lastpass",
            "dashlane",
            "bank",
            "login",
            "credential",
            "sign in",
            "auth",
        ]
        title_lower = window_title.lower()
        return not any(keyword in title_lower for keyword in sensitive_keywords)
