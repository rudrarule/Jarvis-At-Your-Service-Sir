// Preload runs in an isolated context with access to a limited Node surface.
// We expose only a tiny, read-only bridge — the UI itself talks to the backend
// over HTTP (same origin), so it needs almost nothing from Electron.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("jarvisDesktop", {
  isDesktop: true,
  platform: process.platform,
  backendUrl: `http://localhost:${process.env.JARVIS_PORT || "8000"}`,
});
