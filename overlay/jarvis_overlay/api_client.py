"""Async HTTP bridge from the PyQt overlay to FastAPI."""
from __future__ import annotations

import asyncio

import httpx
from PyQt6.QtCore import QObject, pyqtSignal

from .config import OverlayConfig
from .state import RegionCapture


class OverlayAskWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, config: OverlayConfig, capture: RegionCapture, question: str, app_context: dict | None = None, session_id: str | None = None):
        super().__init__()
        self._config = config
        self._capture = capture
        self._question = question
        self._app_context = app_context or {}
        self._session_id = session_id or config.session_id

    def run(self) -> None:
        try:
            result = asyncio.run(self._post())
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    async def _post(self) -> dict:
        rect = self._capture.rect
        screen = self._capture.screen
        data = {
            "question": self._question,
            "session_id": self._session_id,
            "screen_name": screen.name(),
            "region_x": str(rect.x()),
            "region_y": str(rect.y()),
            "region_width": str(rect.width()),
            "region_height": str(rect.height()),
            "device_pixel_ratio": str(self._capture.device_pixel_ratio),
        }
        for key in ("app_name", "process_name", "process_path", "window_title"):
            value = self._app_context.get(key)
            if value:
                data[key] = str(value)
        files = {"image": ("selection.png", self._capture.image_bytes, "image/png")}
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            response = await client.post(f"{self._config.backend_url}/overlay/ask", data=data, files=files)
            if response.status_code >= 400:
                detail = _extract_error(response)
                raise RuntimeError(detail)
            return response.json()


class OverlayFollowUpWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, config: OverlayConfig, context_id: str, question: str, session_id: str | None = None):
        super().__init__()
        self._config = config
        self._context_id = context_id
        self._question = question
        self._session_id = session_id or config.session_id

    def run(self) -> None:
        try:
            result = asyncio.run(self._post())
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    async def _post(self) -> dict:
        payload = {
            "context_id": self._context_id,
            "question": self._question,
            "session_id": self._session_id,
        }
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            response = await client.post(f"{self._config.backend_url}/overlay/follow-up", json=payload)
            if response.status_code >= 400:
                detail = _extract_error(response)
                raise RuntimeError(detail)
            return response.json()


class OverlayOcrWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, config: OverlayConfig, capture: RegionCapture):
        super().__init__()
        self._config = config
        self._capture = capture

    def run(self) -> None:
        try:
            result = asyncio.run(self._post())
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    async def _post(self) -> dict:
        files = {"image": ("selection.png", self._capture.image_bytes, "image/png")}
        async with httpx.AsyncClient(timeout=self._config.request_timeout_s) as client:
            response = await client.post(f"{self._config.backend_url}/overlay/ocr", files=files)
            if response.status_code >= 400:
                detail = _extract_error(response)
                raise RuntimeError(detail)
            return response.json()


def _extract_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"Backend request failed with HTTP {response.status_code}."
    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    return f"Backend request failed with HTTP {response.status_code}."
