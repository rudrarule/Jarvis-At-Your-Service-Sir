# J.A.R.V.I.S Desktop

An Electron shell that wraps the React UI in a native window and **auto-spawns the
Python backend** on launch. Because the backend (`backend/main.py`) already serves
the compiled frontend at `/` and the UI calls it via `window.location.origin`,
everything runs same-origin at `http://localhost:8000` — no CORS, no dev server.

## How it works

1. On launch, the app checks whether something is already healthy at
   `http://localhost:8000/health`.
   - If **yes**, it attaches to that backend (and won't kill it on quit).
   - If **no**, it spawns `python main.py` in `../backend`.
2. A splash screen shows while it polls `/health`.
3. Once healthy, the window loads `http://localhost:8000` (UI + API).
4. On quit, if the app started the backend, it kills the whole process tree
   (the backend spawns Playwright/Chromium children).

> It deliberately runs `python main.py` (ProactorEventLoop), **not**
> `uvicorn --reload`, because the reload loop's SelectorEventLoop breaks
> Playwright's persistent-context launch on Windows.

## First-time setup

```bash
# 1. Build the frontend once (backend serves frontend/dist at "/")
cd frontend && npm install && npm run build

# 2. Install the desktop deps
cd ../desktop && npm install
```

## Run

```bash
cd desktop
npm start           # launches the window + auto-spawns the backend
# or build the UI first, then launch, in one go:
npm run start:full
```

After changing frontend code, rebuild it (`npm run build:ui` from `desktop/`,
or `npm run build` in `frontend/`) so the backend serves the latest UI.

## Configuration (env vars)

| Variable              | Default                    | Purpose                                  |
| --------------------- | -------------------------- | ---------------------------------------- |
| `JARVIS_PORT`         | `8000`                     | Backend port the window loads.           |
| `JARVIS_PYTHON`       | `python` / `python3`       | Python executable used to spawn backend. |
| `JARVIS_BACKEND_DIR`  | `../backend`               | Backend working directory.               |

## Packaging an installer (later)

`package.json` includes an `electron-builder` config. To produce a distributable:

```bash
cd desktop && npm run dist
```

For a fully self-contained installer you'd also bundle the Python backend
(e.g. PyInstaller) and point `JARVIS_BACKEND_DIR`/`JARVIS_PYTHON` at the bundled
binary — that's the bigger "ship it" step beyond this auto-spawn dev setup.
