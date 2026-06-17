/**
 * events.js — Baileys event handlers.
 *
 * Wires up the socket's event emitter to:
 *  1. Store incoming messages (unread tracking)
 *  2. Detect and store missed calls
 *  3. Auto-reply to missed calls from approved contacts
 *  4. Track connection state (QR, open, close)
 */

const config = require("./config");
const store = require("./store");
const db = require("./db");
const qrcode = require("qrcode-terminal");

/**
 * Register all event handlers on the Baileys socket.
 *
 * @param {import("@whiskeysockets/baileys").WASocket} sock
 * @param {Function} saveCreds — persists auth credentials on update
 */
function registerEvents(sock, saveCreds) {
  // ── Connection Updates (QR, open, close) ────────────────
  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      // Print QR to terminal for pairing
      console.log("\n[WA] ══════════════════════════════════════════");
      console.log("[WA]  Scan this QR code with WhatsApp:");
      console.log("[WA] ══════════════════════════════════════════\n");
      qrcode.generate(qr, { small: true });
      store.setConnectionState({ status: "connecting", qrCode: qr });
    }

    if (connection === "open") {
      const user = sock.user;
      console.log(
        `[WA] ✓ Connected as ${user?.name || user?.id || "unknown"}`
      );
      store.setConnectionState({
        status: "connected",
        qrCode: null,
        lastConnected: new Date().toISOString(),
        user: user
          ? { id: user.id, name: user.name }
          : null,
      });
    }

    if (connection === "close") {
      const statusCode =
        lastDisconnect?.error?.output?.statusCode;
      const reason =
        lastDisconnect?.error?.message || "unknown";
      console.log(
        `[WA] ✗ Disconnected (status=${statusCode}, reason=${reason})`
      );
      store.setConnectionState({
        status: "disconnected",
        qrCode: null,
      });

      // DisconnectReason.loggedOut === 401
      // If logged out, auth is dead; otherwise we should reconnect
      // The reconnect logic is in index.js
    }
  });

  // ── Group Updates (Name changes, etc) ──────────────────
  sock.ev.on("groups.update", (updates) => {
    for (const update of updates) {
      if (update.id && update.subject) {
        console.log(`[WA] Group renamed: ${update.id} -> ${update.subject}`);
        store.setGroupName(update.id, update.subject);
      }
    }
  });

  // ── Contacts Sync ────────────────────────────────────────
  sock.ev.on("contacts.upsert", (contactsArr) => {
    store.upsertContacts(contactsArr);
    console.log(`[WA] Contacts synced (upsert): ${contactsArr.length} contacts received`);
  });

  sock.ev.on("contacts.update", (updates) => {
    store.upsertContacts(updates);
  });

  // Baileys v6+ often delivers contacts via history sync
  sock.ev.on("messaging-history.set", (data) => {
    if (data.contacts && data.contacts.length > 0) {
      store.upsertContacts(data.contacts);
      console.log(`[WA] Contacts synced (history): ${data.contacts.length} contacts received`);
    }
  });

  // ── Credentials Update ──────────────────────────────────
  sock.ev.on("creds.update", saveCreds);

  // ── New Messages ────────────────────────────────────────
  sock.ev.on("messages.upsert", (upsert) => {
    // First pass: detect the user's own outgoing replies (across ALL upsert
    // types, including "append" for messages sent from the phone) so the
    // unanswered auto-responder timer for that chat is reset immediately.
    for (const msg of upsert.messages) {
      if (
        msg.key.fromMe &&
        msg.key.remoteJid &&
        msg.key.remoteJid !== "status@broadcast"
      ) {
        store.markReplied(msg.key.remoteJid);
      }
    }

    if (upsert.type !== "notify") return; // Ignore history syncs

    for (const msg of upsert.messages) {
      // Skip own outgoing messages
      if (msg.key.fromMe) continue;

      // Skip status broadcasts
      if (msg.key.remoteJid === "status@broadcast") continue;

      const chatId = msg.key.remoteJid;
      const isGroup = chatId?.endsWith("@g.us");
      const sender = isGroup
        ? msg.key.participant || chatId
        : chatId;

      // Extract text from various message types
      const text =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        msg.message?.imageMessage?.caption ||
        msg.message?.videoMessage?.caption ||
        msg.message?.documentMessage?.caption ||
        null;

      // Determine chat name
      const pushName = msg.pushName || sender;
      const chatName = isGroup ? chatId : pushName;

      // Also cache the contact's pushName for search
      if (pushName && !isGroup && chatId) {
        store.upsertContacts([{ id: chatId, notify: pushName }]);
      }

      const messageData = {
        id: msg.key.id,
        text,
        timestamp: (msg.messageTimestamp || Math.floor(Date.now() / 1000)) * 1000,
        fromMe: false,
        sender: pushName,
        isGroup,
      };

      store.addUnreadMessage(chatId, chatName, messageData);

      console.log(
        `[MSG] ${isGroup ? "[GROUP] " : ""}${pushName}: ${
          text ? text.substring(0, 80) : "[media]"
        }`
      );
    }
  });

  // ── Call Events ─────────────────────────────────────────
  // NOTE: Baileys on WhatsApp Web typically only fires "offer".
  // "timeout" and "reject" rarely come through.
  // Since the connector can't answer calls, every "offer" = missed call.
  sock.ev.on("call", async (calls) => {
    for (const call of calls) {
      console.log(
        `[CALL] Event: status=${call.status}, from=${call.from}, isVideo=${call.isVideo || false}`
      );

      // Only act on "offer" (incoming call) — this is the reliable event
      if (call.status === "offer") {
        console.log(
          `[CALL] Missed ${call.isVideo ? "video" : "voice"} call from ${call.from}`
        );

        store.addMissedCall({
          from: call.from,
          fromName: call.from,
          timestamp: Date.now(),
          status: "missed",
          isVideo: call.isVideo || false,
          chatId: call.from,
        });

        // ── Auto-reply immediately ──────────────────
        await handleMissedCallAutoReply(sock, call);
      }
    }
  });
}

/**
 * Handle auto-reply for a missed call.
 * Rules:
 *  1. Must be a personal chat (not a group)
 *  2. Must not have received an auto-reply within the cooldown window (12h)
 *  → Replies to ALL missed calls, no approved-contacts filter.
 */
async function handleMissedCallAutoReply(sock, call) {
  const jid = call.from; // e.g., "919876543210@s.whatsapp.net"
  const rawNumber = jid.split("@")[0];

  // 1. Skip group calls
  if (jid.endsWith("@g.us")) {
    console.log("[AUTO-REPLY] Group call. Skipping.");
    return;
  }

  // 2. Rate limit — don't spam the same person within the cooldown window
  if (!db.canAutoReply(jid)) {
    console.log(
      `[AUTO-REPLY] Cooldown active for ${rawNumber}. Skipping.`
    );
    return;
  }

  // 3. Send auto-reply
  try {
    await sock.sendMessage(jid, { text: config.autoReplyMessage });
    db.recordAutoReply(jid, config.autoReplyMessage);
    console.log(`[AUTO-REPLY] ✓ Sent to ${rawNumber}`);
  } catch (err) {
    console.error(
      `[AUTO-REPLY] ✗ Failed to send to ${rawNumber}:`,
      err.message
    );
  }
}

// ─────────────────────────────────────────────────────────
//  DELAYED AUTO-RESPONDER (unanswered personal messages)
// ─────────────────────────────────────────────────────────

let _unansweredSweeper = null;

/**
 * Run a single sweep: for every personal chat that has had an incoming message
 * unanswered for >= the configured delay, send the professional holding reply
 * (rate-limited via the shared auto_replies cooldown table). Group chats are
 * never included because the store only tracks pending replies for 1:1 chats.
 *
 * @param {Function} getSocket — returns the current socket (may be null)
 */
async function sweepUnansweredReplies(getSocket) {
  if (!config.unansweredReplyEnabled) return;

  const sock = getSocket();
  if (!sock || store.getConnectionState().status !== "connected") return;

  const thresholdMs = config.unansweredReplyDelayHours * 60 * 60 * 1000;
  const pending = store.getPendingPersonalReplies(thresholdMs);

  for (const chat of pending) {
    const jid = chat.chat_id;

    // Defensive: never message groups.
    if (jid.endsWith("@g.us")) continue;

    // Rate limit — don't spam the same person within the cooldown window.
    if (!db.canAutoReply(jid)) continue;

    try {
      await sock.sendMessage(jid, { text: config.unansweredReplyMessage });
      db.recordAutoReply(jid, config.unansweredReplyMessage);
      const mins = Math.round(chat.waiting_ms / 60000);
      console.log(
        `[AUTO-RESPOND] ✓ Holding reply sent to ${jid.split("@")[0]} ` +
          `(unanswered ${mins}m)`
      );
    } catch (err) {
      console.error(
        `[AUTO-RESPOND] ✗ Failed to reply to ${jid.split("@")[0]}:`,
        err.message
      );
    }
  }
}

/**
 * Start the periodic unanswered-reply sweeper. Safe to call once at startup.
 * @param {Function} getSocket — returns the current socket
 */
function startUnansweredSweeper(getSocket) {
  if (_unansweredSweeper) return; // already running
  if (!config.unansweredReplyEnabled) {
    console.log("[AUTO-RESPOND] Delayed auto-responder disabled by config.");
    return;
  }
  console.log(
    `[AUTO-RESPOND] Sweeper active — replying to personal chats unanswered ` +
      `for ${config.unansweredReplyDelayHours}h (checking every ` +
      `${Math.round(config.unansweredSweepIntervalMs / 1000)}s).`
  );
  _unansweredSweeper = setInterval(() => {
    sweepUnansweredReplies(getSocket).catch((err) =>
      console.error("[AUTO-RESPOND] Sweep error:", err.message)
    );
  }, config.unansweredSweepIntervalMs);
  // Don't keep the event loop alive solely for the sweeper.
  if (_unansweredSweeper.unref) _unansweredSweeper.unref();
}

module.exports = { registerEvents, startUnansweredSweeper };
