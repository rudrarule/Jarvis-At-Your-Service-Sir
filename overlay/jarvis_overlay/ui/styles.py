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
    /* SOLID graphite (no gradient): gradient fills don't paint on a
       WA_TranslucentBackground top-level window, which made the panel see-through
       over white sites. A solid colour paints opaquely and stays readable. */
    background: #11161d;
    border: 1px solid rgba(92, 225, 255, 150);
    border-radius: 18px;
}
QLabel {
    color: #eaf6ff;
    background: transparent;
    font-size: 14px;
}
QLabel#BubbleText {
    color: #edf7ff;
    font-size: 14px;
}
QLabel#BubbleRole_assistant {
    color: rgba(120, 232, 255, 225);
    font-size: 10px;
    font-weight: bold;
}
QLabel#BubbleRole_user {
    color: rgba(190, 246, 255, 220);
    font-size: 10px;
    font-weight: bold;
}
QFrame#HeaderDivider {
    background: rgba(146, 224, 255, 38);
    border: none;
}
QPushButton {
    color: rgba(230, 245, 255, 215);
    background: rgba(255, 255, 255, 16);
    border: 1px solid rgba(146, 224, 255, 40);
    border-radius: 9px;
    padding: 5px 11px;
    font-size: 11px;
}
QPushButton:hover {
    background: rgba(92, 225, 255, 55);
    color: #ffffff;
    border: 1px solid rgba(92, 225, 255, 150);
}
QPushButton#CopyButton {
    color: #06303c;
    font-weight: bold;
    border: none;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7fe7ff, stop:1 #45c8ff);
}
QPushButton#CopyButton:hover {
    background: #9cefff;
    color: #06303c;
}
QPushButton#CaptureButton {
    color: #7fe7ff;
    font-weight: bold;
    border: 1px solid rgba(124, 232, 255, 150);
    background: rgba(92, 225, 255, 30);
}
QPushButton#CaptureButton:hover {
    background: rgba(92, 225, 255, 80);
    color: #ffffff;
}
QScrollArea#ResponseScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 9px;
    margin: 2px 0px 2px 0px;
}
QScrollBar::handle:vertical {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(124, 232, 255, 175), stop:1 rgba(74, 200, 255, 150));
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(124, 232, 255, 235);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QLineEdit#FollowUpInput {
    color: #ffffff;
    background: rgba(8, 14, 22, 235);
    border: 1px solid rgba(92, 225, 255, 80);
    border-radius: 13px;
    padding: 11px 15px;
    font-size: 13px;
    selection-background-color: rgba(0, 212, 255, 120);
}
QLineEdit#FollowUpInput:focus {
    border: 1px solid rgba(124, 232, 255, 210);
    background: rgba(10, 17, 26, 250);
}
QLineEdit#FollowUpInput::placeholder {
    color: rgba(210, 238, 255, 120);
}
QFrame#ChatBubble_user {
    /* SOLID colours so text stays readable over any background. */
    background: #18495f;
    border: 1px solid rgba(124, 232, 255, 150);
    border-radius: 13px;
}
QFrame#ChatBubble_assistant {
    background: #161e2a;
    border: 1px solid rgba(146, 224, 255, 40);
    border-left: 2px solid rgba(92, 225, 255, 150);
    border-radius: 13px;
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
