"""Shared Qt styles for the overlay widgets."""

INPUT_STYLE = """
QWidget#AskPopup {
    background: rgba(14, 22, 32, 218);
    border: 1px solid rgba(118, 218, 255, 130);
    border-radius: 14px;
}
QLineEdit {
    color: #eefaff;
    background: transparent;
    border: none;
    padding: 12px 16px;
    font-size: 15px;
    selection-background-color: rgba(0, 212, 255, 120);
}
QLineEdit::placeholder {
    color: rgba(238, 250, 255, 120);
}
"""

RESPONSE_STYLE = """
QWidget#ResponseBubble {
    background: #000000;
    border: 2px solid rgba(92, 225, 255, 180);
    border-radius: 16px;
}
QLabel {
    color: #ffffff;
    background: transparent;
    font-size: 14px;
    line-height: 1.45;
}
QPushButton {
    color: rgba(255, 255, 255, 210);
    background: rgba(255, 255, 255, 22);
    border: 1px solid rgba(255, 255, 255, 34);
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 11px;
}
QPushButton:hover {
    background: rgba(255, 255, 255, 45);
    color: #ffffff;
}
QPushButton#CopyButton {
    color: #5ce1ff;
    border: 1px solid rgba(92, 225, 255, 140);
    background: rgba(92, 225, 255, 24);
    font-weight: bold;
}
QPushButton#CopyButton:hover {
    background: rgba(92, 225, 255, 60);
    color: #ffffff;
}
QScrollArea#ResponseScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    border: none;
    background: rgba(255, 255, 255, 10);
    width: 6px;
    margin: 0px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(92, 225, 255, 110);
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(92, 225, 255, 180);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QLineEdit#FollowUpInput {
    color: #ffffff;
    background: #050505;
    border: 1px solid rgba(92, 225, 255, 90);
    border-radius: 12px;
    padding: 10px 14px;
    font-size: 13px;
    selection-background-color: rgba(0, 212, 255, 120);
}
QLineEdit#FollowUpInput:focus {
    border: 1px solid rgba(92, 225, 255, 200);
    background: #000000;
}
QLineEdit#FollowUpInput::placeholder {
    color: rgba(255, 255, 255, 110);
}
QFrame#ChatBubble_user {
    background: rgba(92, 225, 255, 22);
    border: 1px solid rgba(92, 225, 255, 90);
    border-radius: 12px;
}
QFrame#ChatBubble_assistant {
    background: #0a0a0a;
    border: 1px solid rgba(255, 255, 255, 22);
    border-radius: 12px;
}
"""

CURSOR_HUD_STYLE = """
QWidget#CursorCompanion {
    background: rgba(8, 15, 24, 214);
    border: 1px solid rgba(92, 225, 255, 120);
    border-radius: 14px;
}
QLabel#HudTitle {
    color: rgba(136, 231, 255, 210);
    background: transparent;
    font-size: 11px;
}
QLabel#HudBody {
    color: #edfaff;
    background: transparent;
    font-size: 13px;
}
QLabel#HudHint {
    color: rgba(237, 250, 255, 145);
    background: transparent;
    font-size: 11px;
}
"""
