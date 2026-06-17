/**
 * index.js — Main entry point for the J.A.R.V.I.S WhatsApp Connector.
 *
 * Architecture:
 *   WhatsApp ↔ Baileys Socket ↔ Event Handlers ↔ In-Memory Store
 *                                                      ↕
 *                                              Express REST API
 *                                                      ↕
 *                                         Jarvis FastAPI Backend
 *
 * Features:
 *  - QR pairing with persistent auth state
 *  - Automatic reconnect with exponential backoff
 *  - Event-driven message & call tracking
 *  - SQLite-backed auto-reply rate limiting
 *  - REST API for Jarvis integration
 */

const {
  default: makeWASocket,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} = require("@whiskeysockets/baileys");
const pino = require("pino");

const config = require("./src/config");
const { getAuthState, clearAuthState } = require("./src/auth");
const { registerEvents, startUnansweredSweeper } = require("./src/events");
const { createApi } = require("./src/api");
const { initDb, purgeExpired, closeDb } = require("./src/db");
const store = require("./src/store");

// ── Logger ────────────────────────────────────────────────
const logger = pino({ level: config.logLevel });

// ── State ─────────────────────────────────────────────────
let sock = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY_MS = 2000;

/**
 * Start (or restart) the Baileys WhatsApp connection.
 */
async function startConnection() {
  console.log("\n[WA] ══════════════════════════════════════════");
  console.log("[WA]  J.A.R.V.I.S WhatsApp Connector v1.0.0");
  console.log("[WA] ══════════════════════════════════════════\n");

  // Initialise SQLite (async — sql.js uses WASM)
  await initDb();
  purgeExpired();

  // Load auth state
  const { state, saveCreds } = await getAuthState();

  // Fetch latest Baileys version info
  const { version, isLatest } = await fetchLatestBaileysVersion();
  console.log(`[WA] Using WA Web v${version.join(".")}, isLatest: ${isLatest}`);

  // Create the socket
  sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    logger,
    printQRInTerminal: false,
    generateHighQualityLinkPreview: false,
    syncFullHistory: false,
    markOnlineOnConnect: true,
    browser: ["JARVIS", "Chrome", "1.1.0"],
  });

  // Register event handlers
  registerEvents(sock, saveCreds);

  // ── Handle disconnects with reconnection ──────────────
  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect } = update;

    if (connection === "open") {
      reconnectAttempts = 0; // Reset on successful connection
    }

    if (connection === "close") {
      const statusCode =
        lastDisconnect?.error?.output?.statusCode;

      if (statusCode === DisconnectReason.loggedOut) {
        // Session is dead — need fresh QR
        console.log("[WA] Logged out. Clearing auth and restarting...");
        clearAuthState();
        reconnectAttempts = 0;
        setTimeout(startConnection, 3000);
      } else if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        // Exponential backoff reconnect
        reconnectAttempts++;
        const delay = Math.min(
          BASE_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttempts - 1),
          60000 // Max 60s
        );
        console.log(
          `[WA] Reconnecting in ${delay / 1000}s (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`
        );
        setTimeout(startConnection, delay);
      } else {
        console.error(
          "[WA] ✗ Max reconnect attempts reached. Manual restart required."
        );
        store.setConnectionState({
          status: "disconnected",
          qrCode: null,
        });
      }
    }
  });

  return sock;
}

// ── Express API Server ──────────────────────────────────
const api = createApi(() => sock);
const server = api.listen(config.port, () => {
  console.log(`[API] REST API listening on http://localhost:${config.port}`);
  console.log(`[API] Endpoints:`);
  console.log(`[API]   GET  /health`);
  console.log(`[API]   GET  /unread-summary`);
  console.log(`[API]   GET  /missed-calls`);
  console.log(`[API]   POST /send-message`);
  console.log(`[API]   GET  /connection`);
  console.log(`[API]   POST /clear-unread`);
  console.log(`[API]   POST /clear-calls`);
  console.log(`[API]   GET  /chat-messages`);
  console.log(`[API]   GET  /pending-replies`);
  console.log(`[API]   GET  /auto-replies\n`);
});

// ── Delayed auto-responder for unanswered personal chats ──
startUnansweredSweeper(() => sock);

// ── Graceful Shutdown ───────────────────────────────────
function shutdown(signal) {
  console.log(`\n[WA] ${signal} received. Shutting down gracefully...`);

  if (sock) {
    try {
      sock.end(undefined);
    } catch (_) {}
  }

  closeDb();

  server.close(() => {
    console.log("[WA] HTTP server closed.");
    process.exit(0);
  });

  // Force exit after 5s
  setTimeout(() => process.exit(1), 5000);
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("uncaughtException", (err) => {
  console.error("[WA] Uncaught exception:", err);
});
process.on("unhandledRejection", (err) => {
  console.error("[WA] Unhandled rejection:", err);
});

// ── Start ────────────────────────────────────────────────
startConnection().catch((err) => {
  console.error("[WA] Fatal startup error:", err);
  process.exit(1);
});
