"""Premium floating response bubble."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget, QScrollArea, QLineEdit, QFrame

from .styles import RESPONSE_STYLE


class ResponseBubble(QWidget):
    pin_requested = pyqtSignal(str, QPoint)
    speak_requested = pyqtSignal(str)
    follow_up_submitted = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("ResponseBubble")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(480)
        self.setMaximumWidth(720)
        self.setMinimumHeight(120)
        self.setMaximumHeight(650)
        self.setStyleSheet(RESPONSE_STYLE)

        self.title = QLabel("☷ J.A.R.V.I.S")
        self.title.setStyleSheet("font-size: 11px; color: rgba(136, 231, 255, 185); letter-spacing: 0.5px; font-weight: bold;")
        
        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("CopyButton")
        self.copy_button.clicked.connect(self._copy_to_clipboard)

        self.pin_button = QPushButton("Pin")
        self.pin_button.clicked.connect(self._pin_response)

        self.speak_button = QPushButton("Speak")
        self.speak_button.clicked.connect(self._speak_response)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.hide)

        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.copy_button)
        header.addWidget(self.pin_button)
        header.addWidget(self.speak_button)
        header.addWidget(self.close_button)
        header.setSpacing(8)

        # Dynamic scrollable chat container
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("ResponseScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.chat_container = QWidget()
        self.chat_container.setObjectName("ChatContainer")
        self.chat_container.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(12)
        self.chat_layout.addStretch(1)

        self.scroll_area.setWidget(self.chat_container)

        # Translucent glassmorphic input box
        self.follow_up_input = QLineEdit(self)
        self.follow_up_input.setObjectName("FollowUpInput")
        self.follow_up_input.setPlaceholderText("Ask a follow-up, Sir...")
        self.follow_up_input.returnPressed.connect(self._submit_follow_up)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.follow_up_input)

        self._drag_offset: QPoint | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_loading)
        self._loading_step = 0
        self._loading_label: QLabel | None = None
        self._last_reply = ""
        self._context_id: str | None = None

    def show_loading(self, point: QPoint) -> None:
        self._timer.stop()
        self._clear_chat()
        self._last_reply = ""
        self._context_id = None
        self.follow_up_input.clear()
        self.follow_up_input.setEnabled(False)
        
        self._loading_label = QLabel("Analyzing selected region")
        self._loading_label.setWordWrap(True)
        self._loading_label.setStyleSheet("color: rgba(238, 250, 255, 160); font-style: italic; font-size: 13px;")
        
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, self._loading_label)
        self._loading_step = 0
        self._timer.start(320)
        
        self.setFixedSize(380, 130)
        self.move(_clamp_to_screen(point + QPoint(18, 74), self.width(), self.height()))
        self.show()
        self.raise_()

    def show_followup_loading(self, question: str) -> None:
        self._timer.stop()
        if self._loading_label:
            self._loading_label.deleteLater()
            
        self._add_message_bubble("user", question)
        self.follow_up_input.clear()
        self.follow_up_input.setEnabled(False)
        
        self._loading_label = QLabel("Analyzing follow-up")
        self._loading_label.setWordWrap(True)
        self._loading_label.setStyleSheet("color: rgba(238, 250, 255, 140); font-style: italic; font-size: 13px;")
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, self._loading_label)
        
        self._loading_step = 0
        self._timer.start(320)
        self._adjust_bubble_size()

    def show_response(self, text: str) -> None:
        self._timer.stop()
        self._clear_chat()
        if self._loading_label:
            self._loading_label.deleteLater()
            self._loading_label = None
            
        self.follow_up_input.setEnabled(True)
        self._add_message_bubble("assistant", text)
        self._last_reply = text
        self._adjust_bubble_size()
        
        self.show()
        self.raise_()
        self.activateWindow()
        self.follow_up_input.setFocus()

    def show_conversation(self, turns: list[dict], metadata: dict | None = None) -> None:
        self._timer.stop()
        self._clear_chat()
        if self._loading_label:
            self._loading_label.deleteLater()
            self._loading_label = None

        self.follow_up_input.setEnabled(True)
        self._last_reply = ""
        
        # Add visual context headers
        meta = metadata or {}
        app_name = meta.get("app_name") or meta.get("process_name") or ""
        window_title = meta.get("window_title") or ""
        if app_name or window_title:
            context_text = ""
            if app_name:
                context_text += f"📍 <b>{app_name}</b>"
            if window_title:
                context_text += f" — <i>{window_title[:60]}</i>"
            
            context_label = QLabel(context_text)
            context_label.setWordWrap(True)
            context_label.setStyleSheet(
                "color: rgba(136, 231, 255, 145); font-size: 11px; padding: 4px 8px; "
                "background: rgba(92, 225, 255, 8); border-radius: 6px;"
            )
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, context_label)

        # Build message cards sequentially
        for idx, turn in enumerate(turns):
            question = str(turn.get("question") or "").strip()
            reply = str(turn.get("reply") or "").strip()
            
            if question and question != "OCR" and not question.startswith("Use the same selected screen region"):
                self._add_message_bubble("user", question)
            if reply:
                self._add_message_bubble("assistant", reply)
                self._last_reply = reply

        self._adjust_bubble_size()
        self.show()
        self.raise_()
        self.activateWindow()
        self.follow_up_input.setFocus()

    def show_error(self, text: str) -> None:
        self._timer.stop()
        self._clear_chat()
        if self._loading_label:
            self._loading_label.deleteLater()
            self._loading_label = None

        self.follow_up_input.setEnabled(True)
        self._add_message_bubble("assistant", f"⚠️ Error: {text}")
        self._adjust_bubble_size()
        self.show()
        self.raise_()
        self.activateWindow()

    def _add_message_bubble(self, role: str, text: str) -> None:
        bubble = QFrame()
        bubble.setObjectName(f"ChatBubble_{role}")
        
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        if role == "user":
            label.setStyleSheet("color: #e6f9ff; font-size: 13px; font-weight: 500;")
        else:
            label.setStyleSheet("color: #edfaff; font-size: 13px; line-height: 1.45;")
            
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 10, 12, 10)
        bubble_layout.addWidget(label)
        
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
 
    def _clear_chat(self) -> None:
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
 
    def _adjust_bubble_size(self) -> None:
        width = 600
        text_width = width - 36 - 24  # subtracting layout margins and bubble paddings
        fm = self.fontMetrics()
        
        total_text_height = 0
        
        # Sweep all children in chat_layout to calculate exact height
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            if not item:
                continue
            widget = item.widget()
            if widget:
                if isinstance(widget, QFrame):
                    label = widget.findChild(QLabel)
                    if label:
                        rect = fm.boundingRect(0, 0, text_width, 10000, 
                                               int(Qt.TextFlag.TextWordWrap), label.text())
                        total_text_height += rect.height() + 24  # text footprint + bubble margins/paddings
                elif isinstance(widget, QLabel):
                    rect = fm.boundingRect(0, 0, text_width, 10000, 
                                           int(Qt.TextFlag.TextWordWrap), widget.text())
                    total_text_height += rect.height() + 12
        
        # Enforce exact child geometry so QScrollArea viewport detects true scrolling height
        self.chat_container.setFixedWidth(width - 36)
        self.chat_container.setFixedHeight(total_text_height + 20)
        
        # Bubble height = container height + header (45) + input (45) + window margins (40)
        bubble_height = total_text_height + 150
        bubble_height = min(max(bubble_height, 160), 650)
        
        self.setFixedSize(width, bubble_height)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maxValue())

    def _submit_follow_up(self) -> None:
        question = self.follow_up_input.text().strip()
        if not question:
            return
        self.follow_up_submitted.emit(question)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_offset = None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        step = scrollbar.singleStep() * 4
        page_step = scrollbar.pageStep()
        
        if event.key() == Qt.Key.Key_Down:
            scrollbar.setValue(scrollbar.value() + step)
            event.accept()
        elif event.key() == Qt.Key.Key_Up:
            scrollbar.setValue(scrollbar.value() - step)
            event.accept()
        elif event.key() == Qt.Key.Key_PageDown or event.key() == Qt.Key.Key_Space:
            scrollbar.setValue(scrollbar.value() + page_step)
            event.accept()
        elif event.key() == Qt.Key.Key_PageUp:
            scrollbar.setValue(scrollbar.value() - page_step)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _tick_loading(self) -> None:
        self._loading_step = (self._loading_step + 1) % 4
        if self._loading_label:
            prefix = "Analyzing selected region" if self._last_reply == "" else "Analyzing follow-up"
            self._loading_label.setText(prefix + "." * self._loading_step)

    def _copy_to_clipboard(self) -> None:
        text = self._last_reply.strip()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.copy_button.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.copy_button.setText("Copy"))

    def _pin_response(self) -> None:
        text = self._last_reply.strip()
        if text:
            self.pin_requested.emit(text, self.pos())

    def _speak_response(self) -> None:
        text = self._last_reply.strip()
        if text:
            self.speak_requested.emit(text)


def _clamp_to_screen(point: QPoint, width: int, height: int) -> QPoint:
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    geometry = screen.availableGeometry()
    x = min(max(point.x(), geometry.left() + 8), geometry.right() - width - 8)
    y = min(max(point.y(), geometry.top() + 8), geometry.bottom() - height - 8)
    return QPoint(x, y)
