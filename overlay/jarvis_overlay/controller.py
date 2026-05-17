"""Top-level state controller for the native overlay."""
from __future__ import annotations

from PyQt6.QtCore import QThread, QObject
from PyQt6.QtGui import QGuiApplication

try:
    from PyQt6.QtTextToSpeech import QTextToSpeech
except ImportError:
    QTextToSpeech = None

from .actions import get_action
from .api_client import OverlayAskWorker, OverlayFollowUpWorker, OverlayOcrWorker
from .app_context import get_active_app_context
from .capture import capture_region
from .config import CONFIG, OverlayConfig
from .context_store import OverlayContextStore
from .hotkeys import GlobalHotkeyListener
from .state import OverlayState, RegionCapture
from .ui.action_palette import ActionPalette
from .ui.cursor_companion import CursorCompanion
from .ui.input_popup import AskPopup
from .ui.pinned_note import PinnedNote
from .ui.response_bubble import ResponseBubble
from .ui.selection_overlay import SelectionOverlay


class OverlayController(QObject):
    def __init__(self, config: OverlayConfig = CONFIG):
        super().__init__()
        self._config = config
        self._state = OverlayState.IDLE
        self._hotkeys = GlobalHotkeyListener()
        self._hotkeys.activated.connect(self.activate_selection)
        self._selection_windows: list[SelectionOverlay] = []
        self._cursor_hud = CursorCompanion()
        self._action_palette = ActionPalette()
        self._action_palette.action_selected.connect(self.submit_quick_action)
        self._action_palette.ask_selected.connect(self._open_question_input)
        self._action_palette.chat_selected.connect(self._open_chat_input)
        self._action_palette.cancelled.connect(self.cancel)
        self._ask_popup = AskPopup()
        self._connect_ask_handler(self.submit_question)
        self._ask_popup.cancelled.connect(self.cancel)
        self._response_bubble = ResponseBubble()
        self._response_bubble.follow_up_submitted.connect(self.submit_followup)
        self._response_bubble.pin_requested.connect(self._pin_response)
        self._response_bubble.speak_requested.connect(self._speak)
        self._tts = QTextToSpeech(self) if QTextToSpeech else None
        self._context_store = OverlayContextStore()
        self._capture: RegionCapture | None = None
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._pending_question = ""
        self._active_app_context: dict = {}
        self._pinned_notes: list[PinnedNote] = []
        self._active_session_id = "overlay"

    def start(self) -> None:
        self._hotkeys.start()

    def stop(self) -> None:
        self._hotkeys.stop()
        self.cancel()

    def activate_selection(self) -> None:
        if self._state not in {OverlayState.IDLE, OverlayState.SHOWING_RESPONSE}:
            return
        self._state = OverlayState.SELECTING
        self._response_bubble.hide()
        self._active_app_context = get_active_app_context()
        self._cursor_hud.start("Drag around anything on screen", "Release to ask. Esc cancels.")
        self._selection_windows = []
        for screen in QGuiApplication.screens():
            overlay = SelectionOverlay(screen, self._config)
            overlay.selected.connect(self._on_region_selected)
            overlay.cancelled.connect(self.cancel)
            overlay.show()
            overlay.raise_()
            overlay.activateWindow()
            self._selection_windows.append(overlay)

    def submit_question(self, question: str) -> None:
        if not self._capture:
            self.cancel()
            return
        self._state = OverlayState.SENDING
        self._ask_popup.hide()
        self._action_palette.hide()
        self._cursor_hud.stop()
        self._response_bubble.show_loading(self._capture.cursor_pos)
        self._pending_question = question

        self._thread = QThread()
        self._worker = OverlayAskWorker(self._config, self._capture, question, self._context_store.current_metadata, session_id=self._active_session_id)
        self._start_worker(self._worker, self._on_response, self._on_error)

    def submit_quick_action(self, action_id: str) -> None:
        self._active_session_id = "overlay"
        action = get_action(action_id)
        if not action:
            return
        if action_id == "ocr":
            self._submit_ocr()
            return
        self._submit_question_payload(action.prompt, display_question=action.label)

    def submit_followup(self, question: str) -> None:
        context_id = self._context_store.last_context_id
        if not context_id:
            if self._context_store.last_capture:
                self._capture = self._context_store.last_capture
                fallback_question = (
                    "Use the same selected screen region and the previous answer as context.\n\n"
                    f"Previous answer:\n{self._context_store.last_reply}\n\n"
                    f"Follow-up question: {question}"
                )
                self._submit_question_payload(fallback_question, display_question=question)
                return
            self._on_error("No active overlay context. Capture a region first.")
            return
        self._state = OverlayState.SENDING
        self._response_bubble.show_followup_loading(question)
        self._pending_question = question
        self._worker = OverlayFollowUpWorker(self._config, context_id, question, session_id=self._active_session_id)
        self._start_worker(self._worker, self._on_response, self._on_error)

    def _submit_question_payload(self, prompt: str, display_question: str) -> None:
        if not self._capture:
            self.cancel()
            return
        self._state = OverlayState.SENDING
        self._ask_popup.hide()
        self._action_palette.hide()
        self._cursor_hud.stop()
        self._response_bubble.show_loading(self._capture.cursor_pos)
        self._pending_question = display_question
        self._worker = OverlayAskWorker(self._config, self._capture, prompt, self._context_store.current_metadata, session_id=self._active_session_id)
        self._start_worker(self._worker, self._on_response, self._on_error)

    def cancel(self) -> None:
        self._state = OverlayState.IDLE
        self._capture = None
        self._ask_popup.hide()
        self._action_palette.hide()
        self._cursor_hud.stop()
        self._close_selection_windows()

    def _on_region_selected(self, screen, rect, cursor_pos) -> None:
        self._close_selection_windows()
        self._cursor_hud.set_message("Context captured", "Ask what you want to know.")
        try:
            self._capture = capture_region(screen, rect, cursor_pos)
        except Exception as exc:
            self._cursor_hud.stop()
            self._state = OverlayState.SHOWING_RESPONSE
            self._response_bubble.show_error(f"Capture failed: {exc}")
            return
        self._state = OverlayState.AWAITING_QUESTION
        self._cursor_hud.stop()
        self._context_store.begin_session(self._capture, self._active_app_context)
        self._action_palette.open_at(cursor_pos)

    def _on_response(self, payload: dict) -> None:
        self._state = OverlayState.SHOWING_RESPONSE
        reply = str(payload.get("reply") or "No response received.")
        self._context_store.remember_response(self._pending_question, payload)
        turns = self._context_store.current_turns or [{"question": self._pending_question, "reply": reply}]
        self._response_bubble.show_conversation(turns, self._context_store.current_metadata)

    def _on_error(self, message: str) -> None:
        self._state = OverlayState.SHOWING_RESPONSE
        self._response_bubble.show_error(message or "Overlay request failed.")

    def _on_ocr_response(self, payload: dict) -> None:
        self._state = OverlayState.SHOWING_RESPONSE
        if payload.get("available") is False:
            text = str(payload.get("detail") or "Local OCR is not available.")
        else:
            extracted = str(payload.get("text") or "").strip()
            text = extracted or "No readable text was detected in the selected region."
        payload = {"reply": text, "turns": [{"question": "OCR", "reply": text}], "metadata": self._context_store.current_metadata}
        self._context_store.remember_response("OCR", payload)
        self._response_bubble.show_conversation(self._context_store.current_turns, self._context_store.current_metadata)

    def _open_question_input(self) -> None:
        if not self._capture:
            self.cancel()
            return
        self._active_session_id = "overlay"
        self._action_palette.hide()
        self._connect_ask_handler(self.submit_question)
        self._ask_popup.open_at(self._capture.cursor_pos)

    def _open_chat_input(self) -> None:
        if not self._capture:
            self.cancel()
            return
        self._active_session_id = "default"
        self._action_palette.hide()
        self._connect_ask_handler(self.submit_question)
        self._ask_popup.open_at(self._capture.cursor_pos)



    def _submit_ocr(self) -> None:
        if not self._capture:
            self.cancel()
            return
        self._state = OverlayState.SENDING
        self._action_palette.hide()
        self._response_bubble.show_loading(self._capture.cursor_pos)
        self._pending_question = "OCR"
        self._worker = OverlayOcrWorker(self._config, self._capture)
        self._start_worker(self._worker, self._on_ocr_response, self._on_error)

    def _pin_response(self, text, point) -> None:
        note = PinnedNote(text, point)
        note.show()
        self._pinned_notes.append(note)

    def _speak(self, text: str) -> None:
        if self._tts:
            self._tts.say(text[:1200])

    def _start_worker(self, worker: QObject, on_finished, on_failed) -> None:
        self._thread = QThread()
        self._worker = worker
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(on_finished)
        self._worker.failed.connect(on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _connect_ask_handler(self, handler) -> None:
        try:
            self._ask_popup.submitted.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._ask_popup.submitted.connect(handler)

    def _cleanup_worker(self) -> None:
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def _close_selection_windows(self) -> None:
        for window in self._selection_windows:
            window.close()
            window.deleteLater()
        self._selection_windows = []
