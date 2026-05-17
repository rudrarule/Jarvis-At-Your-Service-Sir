# J.A.R.V.I.S Overlay

Phase 1 native desktop overlay for instant screen-context questions.

## Run

```powershell
cd overlay
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m jarvis_overlay.main
```

Set `JARVIS_BACKEND_URL` if your FastAPI server is not running at `http://localhost:8082`.

```powershell
$env:JARVIS_BACKEND_URL="http://localhost:8082"
python -m jarvis_overlay.main
```

## Flow

`Ctrl+Shift+Space` dims the current desktop and shows a cursor-following J.A.R.V.I.S Lens HUD. Drag a region, then choose a quick action or type a custom question.

## Phase 2 Controls

- `Explain`, `Summarize`, `Debug`, `Translate`, and `OCR` chips appear immediately after region selection.
- `Ask...` opens the custom question input.
- Response bubbles support `Copy`, `Pin`, `Follow Up`, `Speak`, and `Close`.
- Follow-up questions reuse the last selected region without another capture.
- Pinned notes stay on screen and can be dragged beside the relevant UI.

Backend endpoints used:

```txt
POST /overlay/ask
POST /overlay/ask/stream
POST /overlay/follow-up
POST /overlay/ocr
GET  /overlay/session/{context_id}
GET  /overlay/sessions
GET  /overlay/history
DELETE /overlay/history
```

`/overlay/ocr` is best-effort. It returns an unavailable response unless local Tesseract plus `pytesseract` are installed.

## Phase 3A

- Each capture now becomes a persistent overlay session with multiple turns.
- Follow-up answers render as a single conversation thread rather than replacing the previous answer.
- Active app metadata is attached to the request when available on Windows: application name, process name, process path, and window title.
- Quick actions use short labels in the visible conversation while sending richer prompts to the backend.
