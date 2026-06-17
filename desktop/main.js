// Electron main process for J.A.R.V.I.S desktop.
//
// Responsibilities:
//   1. Auto-spawn the Python backend (`python main.py`) on launch — UNLESS one is
//      already listening on the port (so we don't double-bind or kill a backend
//      the user started themselves).
//   2. Show a splash while the backend boots, poll /health, then load the UI.
//   3. The backend serves the compiled React app at "/" and the frontend calls
//      it via window.location.origin, so everything is same-origin at :8000 —
//      no CORS, no file:// quirks.
//   4. Tear the backend down cleanly on quit (whole process tree — the backend
//      spawns Playwright/Chromium children).
//
// IMPORTANT: we spawn `python main.py` (ProactorEventLoop) and never
// `uvicorn --reload` — the reload loop uses a SelectorEventLoop on Windows,
// which breaks Playwright's persistent-context launch (NotImplementedError).

const { app, BrowserWindow, Menu, shell, dialog } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const BACKEND_PORT = process.env.JARVIS_PORT || "8000";
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`;
const HEALTH_URL = `${BACKEND_URL}/health`;

// In dev the repo layout is <root>/desktop, <root>/backend. When packaged,
// JARVIS_BACKEND_DIR can override (e.g. an extraResources path).
const REPO_ROOT = path.resolve(__dirname, "..");
const BACKEND_DIR = process.env.JARVIS_BACKEND_DIR || path.join(REPO_ROOT, "backend");
const PYTHON =
  process.env.JARVIS_PYTHON || (process.platform === "win32" ? "python" : "python3");

let backendProc = null;
let weStartedBackend = false;
let mainWindow = null;

function ping(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(timeoutMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await ping(HEALTH_URL)) return true;
    await new Promise((r) => setTimeout(r, 800));
  }
  return false;
}

function startBackend() {
  console.log(`[jarvis-desktop] spawning backend: ${PYTHON} main.py (cwd=${BACKEND_DIR})`);
  backendProc = spawn(PYTHON, ["main.py"], {
    cwd: BACKEND_DIR,
    env: { ...process.env },
    // detached on POSIX so we can signal the whole process group on quit;
    // on Windows we use taskkill /T instead.
    detached: process.platform !== "win32",
    stdio: ["ignore", "pipe", "pipe"],
  });
  weStartedBackend = true;

  backendProc.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  backendProc.on("exit", (code) => {
    console.log(`[jarvis-desktop] backend exited (code=${code})`);
    backendProc = null;
  });
  backendProc.on("error", (err) => {
    dialog.showErrorBox(
      "J.A.R.V.I.S — backend failed to start",
      `Could not launch "${PYTHON} main.py" in ${BACKEND_DIR}.\n\n${err.message}\n\n` +
        `Make sure Python is on PATH (or set JARVIS_PYTHON) and deps are installed.`
    );
  });
}

function stopBackend() {
  if (!backendProc || !weStartedBackend) return;
  const pid = backendProc.pid;
  console.log(`[jarvis-desktop] stopping backend (pid=${pid})`);
  try {
    if (process.platform === "win32") {
      // Kill the whole tree — backend spawns Chromium/Playwright children.
      spawn("taskkill", ["/pid", String(pid), "/T", "/F"]);
    } else {
      process.kill(-pid, "SIGTERM");
    }
  } catch (e) {
    console.log(`[jarvis-desktop] stopBackend error: ${e.message}`);
  }
  backendProc = null;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0a0a0f",
    show: false,
    autoHideMenuBar: true,
    title: "J.A.R.V.I.S",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.loadFile(path.join(__dirname, "splash.html"));

  // Open external links (e.g. OAuth consent, docs) in the system browser,
  // never inside the app window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

async function boot() {
  const alreadyUp = await ping(HEALTH_URL);
  if (alreadyUp) {
    weStartedBackend = false;
    console.log("[jarvis-desktop] backend already running; attaching.");
  } else {
    startBackend();
  }

  createWindow();

  const ok = await waitForBackend();
  if (!ok) {
    dialog.showErrorBox(
      "J.A.R.V.I.S",
      `The backend did not become healthy at ${HEALTH_URL} within the timeout.\n\n` +
        `Check the console for backend logs, confirm Python deps are installed, ` +
        `and that nothing else is blocking port ${BACKEND_PORT}.`
    );
    return;
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.loadURL(BACKEND_URL);
  }
}

// Single-instance: focus the existing window instead of opening a second app
// (and a second backend).
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    boot();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    stopBackend();
    if (process.platform !== "darwin") app.quit();
  });
  app.on("before-quit", stopBackend);
  // Safety nets so we don't orphan the Python process.
  process.on("exit", stopBackend);
  process.on("SIGINT", () => {
    stopBackend();
    process.exit(0);
  });
}
