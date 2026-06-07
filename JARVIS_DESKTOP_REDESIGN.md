# J.A.R.V.I.S — Ambient Desktop Assistant: UX + Architecture Design

Transform J.A.R.V.I.S from "an app you open" into an **ambient layer**: an always-resident orb that lives near the cursor, expands into a solid, readable chat panel, and scales into a full desktop AI OS layer. This builds directly on your existing PyQt6 overlay (`overlay/jarvis_overlay/`) — most primitives already exist.

---

## 0. Headline decision

**Stay on Qt (PyQt6/PySide6). Do not move to Electron.** You already have the right substrate, it's native and lightweight enough to run resident all day, and it lives in Python next to your agents. Add: a glowing **orb** (evolve `cursor_companion.py`), a **solid** chat panel (evolve `response_bubble.py`, drop transparency), a **state-machine controller**, **OS-level global hotkey**, and a **tray presence**. Use QPropertyAnimation/QGraphicsEffects for the premium motion now; optionally render the orb in **QML (Qt Quick)** later for shader-grade glow.

---

## 1. Framework recommendation

| Framework | Always-resident cost | Native overlay / click-through / always-on-top | Premium animation | OS integration (hotkey, tray, acrylic) | Fits your stack | Verdict |
|---|---|---|---|---|---|---|
| **PyQt6 / PySide6 (Qt)** | Low (~60–120 MB) | ✅ first-class (frameless, translucent, `WA_TransparentForMouseEvents`, `WindowStaysOnTopHint`) | ✅ QPropertyAnimation + QGraphicsEffect; ✅✅ QML/Qt Quick (GPU) | ✅ via pywin32 / Qt | ✅ Python, same as backend/agents | **RECOMMENDED** |
| Tauri (Rust + WebView2) | Low (~80 MB) | ⚠️ possible via plugins; click-through + per-pixel orb fiddly in webview | ✅ web/CSS/Canvas | ⚠️ plugins + Rust | ⚠️ adds Rust + IPC to Python | Strong *if you want a web UI panel* |
| Electron | ❌ High (250–500 MB resident) | ✅ good | ✅ web | ✅ | ⚠️ JS layer | ❌ Reject — too heavy for an always-on layer |
| WinUI 3 / WPF | Low | ✅✅ best native Windows (Mica/Acrylic, composition) | ✅✅ Composition API | ✅✅ best | ❌ C#/.NET rewrite | Best OS feel, wrong language for you |

**Why Qt wins for you specifically:** (a) your orb, hotkey, click-through, multi-monitor clamping, and follow-cursor loop are *already written*; (b) a resident ambient assistant must be memory-cheap — Electron disqualifies itself here; (c) staying in Python keeps the UI one process-hop from your planner/browser/WhatsApp agents. Choose **PySide6** over PyQt6 if you want the LGPL license and slightly smoother QML story; otherwise keep PyQt6.

**When to add QML:** the orb's glow/pulse/morph is the one place GPU shaders shine. Ship Phase 1 in QWidget+QPainter (lowest risk on your base), then optionally host the orb in a `QQuickWidget` for richer effects without touching the rest.

---

## 2. UX architecture — the ambient model

### 2.1 States (one state machine, in the controller)
```
        Ctrl+Shift+Space / type
HIDDEN ───────────────► ORB ──click or keypress──► PANEL (Quick Ask)
   ▲                     │  ▲                          │
   │   inactivity        │  │   Esc / inactivity       │  "expand"
   └──────────◄──────────┘  └──────────◄──────────────┤
                              PANEL (Expanded Chat) ◄──┘
                                     │ long task
                                     ▼
                              MISSION HUD (compact, docked)
```
- **HIDDEN → ORB:** hotkey or "start typing" spawns the orb at the cursor with a smooth fade+scale-in.
- **ORB → PANEL:** click the orb *or* begin typing → orb morphs into the panel (geometry + opacity animation).
- **PANEL → ORB:** `Esc` or N seconds of inactivity collapses back to the orb (which docks to the nearest screen edge).
- **ORB → HIDDEN:** click-away / second hotkey toggles it fully away (orb stays warm in memory).
- **Mission:** a long-running task spawns a small **Mission HUD** that docks to a corner and shows progress, independent of the panel.

### 2.2 Three interaction modes (map cleanly to states)
- **Mode 1 — Quick Ask:** orb → slim single-line input + one-shot answer card. (Evolve `action_palette.py` / `input_popup.py`.) Routes to a fast model, no agent loop.
- **Mode 2 — Expanded Chat:** full conversation + agent execution (browser/research). The solid chat panel (evolve `response_bubble.py`). Routes to your Tier-3 master_graph.
- **Mode 3 — Mission HUD:** long-running missions with progress + browser-automation status; docked corner widget that survives panel collapse.

### 2.3 Cursor-follow ("companion") mode — optional, off by default
You already do this in `cursor_companion.py` (16 ms `QTimer` → `QCursor.pos()`, `WA_TransparentForMouseEvents` = never blocks clicks). For the orb companion: lerp toward the cursor (magnetic easing) instead of snapping, idle-dock when the mouse is still, and keep click-through on the orb's translucent margins. Make it a toggle — persistent following is divisive; default to "appears at cursor, then stays put."

---

## 3. UI architecture & component hierarchy

```
OverlayController (controller.py)               # owns state machine + lifecycle
├── GlobalHotkey (hotkeys.py → hardened)         # Ctrl+Shift+Space, OS-level
├── TrayPresence (new)                           # QSystemTrayIcon: show/settings/quit, always-resident
├── JarvisOrb (new; evolve cursor_companion.py)  # glowing animated orb, click/keypress to expand
├── ChatPanel (evolve response_bubble.py)        # SOLID bg, modes 1&2, movable/resizable
│   ├── Header (title, mode chips, pin/close)
│   ├── Conversation view (your fixed scroll+bubbles)
│   ├── Composer (follow-up input)
│   └── ContextStrip (app/window the question is about)
├── MissionHud (new; evolve pinned_note.py)      # docked progress for long tasks
└── SelectionLens (selection_overlay.py + capture.py)  # keep: screen-region capture
```
Keep the **window-per-surface** model you already use (each is a frameless `Tool` window). The controller decides which surface is visible and animates transitions between them. This is exactly what scales to an "OS layer": new capabilities = new surfaces the controller can summon, not rewrites.

---

## 4. Window lifecycle design (the controller state machine)

```python
# controller.py (sketch)
class UXState(Enum):
    HIDDEN = auto(); ORB = auto(); QUICK = auto(); CHAT = auto(); MISSION = auto()

class OverlayController(QObject):
    def __init__(self):
        self.state = UXState.HIDDEN
        self.orb = JarvisOrb()
        self.panel = ChatPanel()        # solid, created once, hidden
        self.mission = MissionHud()
        self.hotkey = GlobalHotkey()
        self.tray = TrayPresence()
        self.hotkey.activated.connect(self.toggle)
        self.orb.expand_requested.connect(self.expand_to_panel)   # click or keypress
        self.panel.collapse_requested.connect(self.collapse_to_orb)  # Esc/inactivity
        self._idle = QTimer(singleShot=True); self._idle.timeout.connect(self.collapse_to_orb)

    def toggle(self):
        if self.state == UXState.HIDDEN: self.show_orb(QCursor.pos())
        else: self.hide_all()

    def show_orb(self, pos):  self.state = UXState.ORB; self.orb.appear(pos)
    def expand_to_panel(self, seed_text=""):
        self.state = UXState.CHAT
        self._morph(self.orb, self.panel, seed_text)   # geometry+opacity animation
    def collapse_to_orb(self):
        self.state = UXState.ORB; self._morph(self.panel, self.orb)
```
Singletons created once and reused (warm) → instant subsequent invocations. The controller is the single source of truth for "what's on screen," which keeps multi-surface behavior coherent.

---

## 5. Orb implementation

Evolve `CursorCompanion` into `JarvisOrb` — a small (~64 px) frameless, translucent, always-on-top, *activatable* window that paints a glowing core.

```python
class JarvisOrb(QWidget):
    expand_requested = pyqtSignal(str)  # seed text ("" if clicked)
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(72, 72)               # core 56 + glow margin
        self._phase = 0.0
        self._pulse = QTimer(self); self._pulse.timeout.connect(self._tick); self._pulse.start(33)  # ~30fps
        # premium glow without shaders:
        self.setGraphicsEffect(QGraphicsDropShadowEffect(blurRadius=40, color=QColor(92,225,255,180), xOffset=0, yOffset=0))

    def appear(self, pos):
        self.move(_clamp(pos + QPoint(16, 16), self.width(), self.height()))
        _fade_scale_in(self, 160)               # QPropertyAnimation: opacity 0→1 + size 0.8→1.0
        self.show(); self.raise_()

    def _tick(self):
        self._phase = (self._phase + 0.04) % (2*math.pi)
        self.update()                            # repaint pulse ring

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = 8 + 2*math.sin(self._phase)          # breathing radius
        grad = QRadialGradient(self.rect().center(), 28)
        grad.setColorAt(0, QColor(150,235,255)); grad.setColorAt(1, QColor(40,140,220,40))
        p.setBrush(grad); p.setPen(Qt.NoPen)
        p.drawEllipse(self.rect().center(), 20+r, 20+r)

    def keyPressEvent(self, e):                  # "start typing" → expand with that char
        if e.text().strip(): self.expand_requested.emit(e.text())
    def mouseReleaseEvent(self, e):              # click → expand
        self.expand_requested.emit("")
```
Notes: enable activation (drop `WA_TransparentForMouseEvents` for the orb so it's clickable; keep it for the *companion* follow-mode margins only). Hover state = grow + brighten via a short animation. For shader-grade glow/particles later, swap the `paintEvent` for a `QQuickWidget` loading a small QML `ShaderEffect`.

---

## 6. Expansion animation (orb → panel morph)

Two clean options:
- **A. Geometry morph (QWidget, ship this):** animate a single frameless window's `geometry` from the orb's 72×72 rect to the panel's rect with `QEasingCurve.OutCubic`, cross-fading orb-paint → panel-content opacity. One `QParallelAnimationGroup` (geometry + windowOpacity), ~180–220 ms. Feels like the orb *unfolds*.
- **B. Two windows, hand-off:** fade/scale the orb out (120 ms) while the panel fades/scales in from the orb's center (160 ms), slight overlap. Simpler to reason about; nearly identical feel.

```python
def _morph(src, dst, seed=""):
    dst.setWindowOpacity(0); dst.setGeometry(_grow_from(src.geometry(), dst.target_size()))
    dst.show()
    grp = QParallelAnimationGroup(dst)
    grp.addAnimation(_anim(dst, b"geometry", _grow_from(src.geometry(), dst.target_size()), dst.target_rect(), 200, OutCubic))
    grp.addAnimation(_anim(dst, b"windowOpacity", 0.0, 1.0, 180))
    grp.addAnimation(_anim(src, b"windowOpacity", 1.0, 0.0, 120))
    grp.finished.connect(src.hide)
    grp.start(); 
    if seed: dst.seed_input(seed)
```
Keep durations ≤ 220 ms — premium = *fast and smooth*, not slow and showy.

---

## 7. Global hotkey architecture (harden it)

Today `hotkeys.py` uses a `pynput` listener tracking pressed keys. That works but is a software hook: it can miss the combo under focus changes and competes with other hooks. **Recommendation:** register an OS-level hotkey via the Win32 `RegisterHotKey` API (through `pywin32` or `ctypes`) on a dedicated thread, which Windows delivers reliably regardless of focused app. Keep `pynput` as a fallback.

```python
# win32 RegisterHotKey(id, MOD_CONTROL|MOD_SHIFT, VK_SPACE) on a thread that pumps messages,
# emit activated() to the Qt main thread via a queued signal.
```
Also: **single-instance guard** (named mutex / QLocalServer) so a second launch just summons the running orb; and make the hotkey a **toggle** (show ↔ hide).

---

## 8. Chat panel design (solid, readable — the #1 complaint)

**Drop transparency for the panel.** Transparent glass over white sites is the readability bug you hit. Use a **solid graphite** background with a real (opaque) surface; reserve translucency only for the thin outer border/shadow.

- Background: graphite `#11161D` → charcoal `#0C1118` vertical gradient, **fully opaque**.
- Accent: electric blue / cyan `#5CE1FF` for borders, focus, and the assistant's left-rail.
- Text: `#EDF7FF` at ~14px, generous line spacing; min contrast ratio ≥ 7:1.
- Surface: 16–18px radius, soft outer drop-shadow, 1px cyan hairline border.
- Optional **blur-behind** *only behind the window's own shadow margin* via Windows Acrylic/Mica (`DwmEnableBlurBehindWindow` / `SetWindowCompositionAttribute`) — gives the premium frosted edge **without** putting blur behind the text.
- Reuse the scroll/bubble fixes you just landed (`response_bubble.py`), but switch its background from translucent to the solid graphite surface above.

This is the key rule: **glass on the chrome, never behind the text.**

---

## 9. Always-on-top, multi-monitor, DPI, click-through

You already do most of this — codify it:
- **Always-on-top:** `WindowStaysOnTopHint | Tool` (Tool keeps it out of the taskbar/alt-tab). For "above fullscreen apps too," you may additionally bump z-order via `SetWindowPos(HWND_TOPMOST)`.
- **Multi-monitor:** keep `QGuiApplication.screenAt(point)` + `availableGeometry()` clamping (already in `_clamp_to_screen`). Spawn the orb on the monitor under the cursor.
- **Per-monitor DPI:** you set `HighDpiScaleFactorRoundingPolicy.PassThrough` in `main.py` — good; size the orb/panel in logical px and let Qt scale.
- **Click-through** where wanted: `WA_TransparentForMouseEvents` (companion margins) — already used.
- **Show without stealing focus** for the orb/HUD: `WA_ShowWithoutActivating` (already used); the panel *does* take focus so typing works.

---

## 10. Performance considerations

- **Stay resident** in the tray; create orb/panel/HUD once and reuse (warm windows = instant summon). Never spin up a process on hotkey.
- **Orb repaint:** cap at ~30 fps (`33 ms`), pause the pulse timer when hidden, and keep the painted area tiny. Cursor-follow at 16 ms only while in companion mode.
- **Lazy-load the heavy stuff:** don't import the agent/Bedrock/Playwright graph until the first real query — keep cold-start of the *UI* near-instant.
- **Animations:** GPU-friendly (opacity/geometry); avoid per-frame layout. If you adopt QML, the orb runs on the scene graph (GPU) for free.
- **Memory target:** idle UI well under ~150 MB; the agent work happens in the backend process, not the overlay.
- **Decouple UI from agents:** overlay talks to the backend (your FastAPI) via local IPC/HTTP/websocket so a slow mission never freezes the orb.

---

## 11. Windows integration checklist

- `QSystemTrayIcon` with menu (Show, Companion mode toggle, Settings, Quit) — the "always present" anchor.
- Win32 `RegisterHotKey` for the global shortcut; configurable in settings.
- Single-instance (named mutex / `QLocalServer`).
- **Autostart:** add to `HKCU\...\Run` or a Startup shortcut (offer as a setting).
- Acrylic/Mica edge via DWM for the premium frosted border (optional).
- Package with **PyInstaller** (`--noconsole`, tray icon, versioned) → a single `JARVIS.exe`. You already ship a `pythonw.exe` venv launch; PyInstaller makes it distributable.

---

## 12. Future scalability → "Desktop OS Layer"

Design the controller as a **surface registry** so new capabilities plug in without rewrites:
```
OverlayController
 ├─ surfaces: {orb, quick, chat, mission, lens, <future: voice_hud, calendar, clipboard_ai>}
 ├─ router: query → (mode, surface, agent)        # reuse your new LLM intent router
 └─ agent bus: backend IPC (planner / browser / whatsapp / memory / voice)
```
- **Voice:** add a `VoiceHud` surface + wake-word service that drives the same controller (`show_orb`, `expand_to_panel`). Orb pulse doubles as the listening indicator.
- **Agents:** Mission HUD subscribes to backend task events (you already emit `tool.started` / `verifier.result` / `agent.token_usage`) → live progress with zero UI rewrite.
- **Memory/planning:** a "context strip" + a side "memory" surface; both are just new surfaces.
- **Desktop automation:** same agent-bus pattern; new tools appear as capabilities, not new windows.
The invariant that makes this scale: **the controller owns lifecycle; surfaces are dumb and reusable; the backend owns intelligence.** New feature = new surface + new agent on the bus.

---

## 13. Phased implementation roadmap

1. **Phase 1 — Orb + morph (the feel).** New `JarvisOrb` (evolve `cursor_companion.py`), controller state machine, orb→panel morph animation, panel made **solid** (kill transparency). Hotkey still pynput. *Outcome: the ambient experience is real.*
2. **Phase 2 — Hardening.** Win32 `RegisterHotKey`, single-instance, tray presence, autostart, multi-monitor spawn-at-cursor, inactivity-collapse + edge dock.
3. **Phase 3 — Modes.** Quick Ask (slim), Expanded Chat (full, → master_graph), Mission HUD wired to backend task events.
4. **Phase 4 — Polish & premium.** Acrylic/Mica edge, hover micro-interactions, optional QML orb with shader glow, companion follow-mode toggle with magnetic easing.
5. **Phase 5 — OS layer.** Voice HUD + wake word, surface registry generalization, settings UI, packaging as `JARVIS.exe`.

Each phase ships independently and reuses your existing files — no big-bang rewrite.

---

## 14. What to keep / evolve / add (mapped to your repo)
- **Keep:** `hotkeys.py` (harden), `selection_overlay.py` + `capture.py` (the Lens), `_clamp_to_screen`, DPI policy in `main.py`, the scroll/size fixes in `response_bubble.py`.
- **Evolve:** `cursor_companion.py` → `JarvisOrb`; `response_bubble.py` → solid `ChatPanel`; `pinned_note.py` → `MissionHud`; `action_palette.py` → Quick Ask; `styles.py` → solid graphite theme tokens.
- **Add:** `controller.py` state machine (you already reference `OverlayController`), `TrayPresence`, Win32 hotkey, single-instance guard, backend IPC client.

---

### TL;DR
Keep Qt, go resident in the tray, evolve your cursor companion into a glowing clickable orb that morphs into a **solid** graphite chat panel, harden the hotkey with Win32, and structure the controller as a surface registry so voice/agents/missions plug in later. You're ~3 focused phases from a Raycast-grade ambient J.A.R.V.I.S, mostly by evolving files you already have.
