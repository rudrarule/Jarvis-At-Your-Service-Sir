/**
 * api.js — Express REST API for the WhatsApp connector.
 *
 * Endpoints:
 *  GET  /health         — Connector health and connection status
 *  GET  /unread-summary — Unread messages grouped by chat
 *  GET  /missed-calls   — Recent missed call events
 *  POST /send-message   — Send a WhatsApp message
 *  POST /clear-unread   — Clear unread messages (optionally per chat)
 *  POST /clear-calls    — Clear missed calls
 *  GET  /auto-replies   — View auto-reply rate-limit records
 */

const express = require("express");
const store = require("./store");
const db = require("./db");

/**
 * Create and configure the Express app.
 *
 * @param {import("@whiskeysockets/baileys").WASocket | null} getSocket
 *        — A function that returns the current socket (may be null during reconnect)
 * @returns {express.Application}
 */
function createApi(getSocket) {
  const app = express();
  app.use(express.json());

  // ── CORS (allow Jarvis backend to call) ─────────────────
  app.use((req, res, next) => {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Headers", "Content-Type, Authorization");
    res.header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    if (req.method === "OPTIONS") return res.sendStatus(200);
    next();
  });

  // ── Health Check ────────────────────────────────────────
  app.get("/health", (req, res) => {
    const conn = store.getConnectionState();
    res.json({
      status: "online",
      service: "jarvis-whatsapp-connector",
      connection: conn.status,
      user: conn.user,
      last_connected: conn.lastConnected,
      uptime_seconds: Math.floor(process.uptime()),
    });
  });

  // ── Unread Summary ──────────────────────────────────────
  app.get("/unread-summary", (req, res) => {
    const summary = store.getUnreadSummary();
    res.json({
      total_chats: summary.length,
      total_messages: summary.reduce((acc, c) => acc + c.unread_count, 0),
      chats: summary,
    });
  });

  // ── Missed Calls ────────────────────────────────────────
  app.get("/missed-calls", (req, res) => {
    const since = req.query.since ? parseInt(req.query.since, 10) : undefined;
    const calls = store.getMissedCalls(since);
    res.json({
      count: calls.length,
      calls,
    });
  });

  // ── Send Message ────────────────────────────────────────
  app.post("/send-message", async (req, res) => {
    const { chat_id, text } = req.body;

    if (!chat_id || !text) {
      return res.status(400).json({
        error: "Missing required fields: chat_id, text",
      });
    }

    const sock = getSocket();
    if (!sock) {
      return res.status(503).json({
        error: "WhatsApp not connected",
      });
    }

    try {
      // Normalize JID: add @s.whatsapp.net if not present
      let jid = chat_id;
      if (!jid.includes("@")) {
        jid = `${jid}@s.whatsapp.net`;
      }

      if (!sock || store.getConnectionState().status !== "connected") {
        return res.status(503).json({ 
          error: "WhatsApp not connected",
          detail: "The connector is currently disconnected or reconnecting."
        });
      }

      await sock.sendMessage(jid, { text });
      console.log(`[API] Message sent to ${jid}: ${text.substring(0, 60)}`);
      res.json({ success: true, chat_id: jid });
    } catch (err) {
      console.error("[API] Send message failed:", err.message);
      res.status(500).json({
        error: "Failed to send message",
        detail: err.message,
      });
    }
  });

  // ── Clear Unread ────────────────────────────────────────
  app.post("/clear-unread", (req, res) => {
    const { chat_id } = req.body || {};
    store.clearUnread(chat_id);
    res.json({
      success: true,
      cleared: chat_id || "all",
    });
  });

  // ── Clear Missed Calls ─────────────────────────────────
  app.post("/clear-calls", (req, res) => {
    store.clearMissedCalls();
    res.json({ success: true });
  });

  // ── Auto-Reply Records ─────────────────────────────────
  app.get("/auto-replies", (req, res) => {
    try {
      const records = db.getAllAutoReplies();
      res.json({ count: records.length, records });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ── Search Chats / Contacts ─────────────────────────────
  app.get("/search-chats", (req, res) => {
    const query = req.query.query;
    if (!query) {
      return res.status(400).json({
        error: "Missing required query parameter: query",
      });
    }

    // First try our in-memory/persisted cache
    let matches = store.searchChats(query);

    // If no results, try querying the Baileys socket's internal contacts
    if (matches.length === 0) {
      const sock = getSocket();
      if (sock?.store?.contacts) {
        const socketContacts = Object.values(sock.store.contacts);
        
        // Cache all socket contacts into our store for future searches
        if (socketContacts.length > 0) {
          store.upsertContacts(socketContacts);
          console.log(`[API] Loaded ${socketContacts.length} contacts from Baileys socket store`);
          // Retry search with the now-populated cache
          matches = store.searchChats(query);
        }
      }
    }

    res.json({ matches, count: matches.length });
  });

  // ── Sync Contacts (manual trigger) ─────────────────────
  app.get("/contacts", (req, res) => {
    let contacts = store.getContacts();

    if (contacts.length === 0) {
      const sock = getSocket();
      if (sock?.store?.contacts) {
        const socketContacts = Object.values(sock.store.contacts);
        if (socketContacts.length > 0) {
          store.upsertContacts(socketContacts);
          contacts = store.getContacts();
        }
      }
    }

    res.json({ contacts, count: contacts.length });
  });

  app.post("/sync-contacts", async (req, res) => {
    const sock = getSocket();
    if (!sock) {
      return res.status(503).json({ error: "WhatsApp not connected" });
    }

    try {
      // Try to fetch contacts from the socket's internal store
      // Baileys caches contacts it has seen in sock.store
      if (sock.store?.contacts) {
        const contactsList = Object.values(sock.store.contacts);
        if (contactsList.length > 0) {
          store.upsertContacts(contactsList);
          return res.json({
            success: true,
            source: "socket_store",
            count: contactsList.length,
          });
        }
      }

      // Fallback: request contact list via presence subscribe
      // This triggers contacts.upsert events
      await sock.sendPresenceUpdate("available");
      
      res.json({
        success: true,
        source: "presence_trigger",
        message: "Presence update sent. Contacts should sync shortly.",
        current_cache_size: store.searchChats("").length || 0,
      });
    } catch (err) {
      console.error("[API] Sync contacts failed:", err.message);
      res.status(500).json({ error: err.message });
    }
  });

  // ── Connection State ────────────────────────────────────
  app.get("/connection", (req, res) => {
    res.json(store.getConnectionState());
  });

  return app;
}

module.exports = { createApi };
