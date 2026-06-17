/**
 * store.js — In-memory store for unread messages and missed calls.
 * Event-driven: data is pushed in by Baileys event handlers,
 * read out by the REST API.  No polling.
 */

const config = require("./config");
const fs = require("fs");
const path = require("path");

const CONTACTS_CACHE_FILE = path.resolve(__dirname, "../contacts_cache.json");
const CONTACT_ALIASES_FILE = path.resolve(__dirname, "../contact_aliases.json");

// ── Unread messages store ────────────────────────────────
// Map<chatId, { chatName, messages: Array<{ id, text, timestamp, fromMe, sender }> }>
const unreadChats = new Map();

// ── Missed calls store ──────────────────────────────────
// Array<{ from, timestamp, status, isVideo, chatId }>
const missedCalls = [];

// ── Pending replies tracker (personal chats only) ───────
// Map<chatId, { firstUnansweredAt: number, chatName: string, lastIncomingAt: number }>
// Tracks personal (1:1) chats where an incoming message is still awaiting a
// reply from the user. Used by the delayed auto-responder sweeper. Cleared the
// moment the user replies (a fromMe message arrives for that chat).
const pendingReplies = new Map();

// ── Contacts cache ──────────────────────────────────────
// Map<jid, { name, notify, pushName, short }>
// Populated from Baileys contacts.upsert events + persisted to disk
const contacts = new Map();

// ── Contact Aliases ─────────────────────────────────────
// Map<alias (lowercase), { jid, displayName }>
// User-editable file mapping friendly names to WhatsApp JIDs
const contactAliases = new Map();

// Load persisted contacts on startup
try {
  if (fs.existsSync(CONTACTS_CACHE_FILE)) {
    const data = JSON.parse(fs.readFileSync(CONTACTS_CACHE_FILE, "utf-8"));
    for (const [jid, info] of Object.entries(data)) {
      contacts.set(jid, info);
    }
    console.log(`[STORE] Loaded ${contacts.size} contacts from disk cache`);
  }
} catch (err) {
  console.warn(`[STORE] Could not load contacts cache: ${err.message}`);
}

// Load contact aliases on startup
try {
  if (fs.existsSync(CONTACT_ALIASES_FILE)) {
    const data = JSON.parse(fs.readFileSync(CONTACT_ALIASES_FILE, "utf-8"));
    for (const [alias, jid] of Object.entries(data)) {
      contactAliases.set(alias.toLowerCase(), {
        jid: jid,
        displayName: alias.charAt(0).toUpperCase() + alias.slice(1),
      });
    }
    console.log(`[STORE] Loaded ${contactAliases.size} contact aliases`);
  }
} catch (err) {
  console.warn(`[STORE] Could not load contact aliases: ${err.message}`);
}

// ── Group Names Cache ──────────────────────────────────
// Map<groupId, groupName>
const groupNames = new Map();

// ── Connection state ────────────────────────────────────
let connectionState = {
  status: "disconnected", // "connected" | "connecting" | "disconnected"
  qrCode: null,
  lastConnected: null,
  user: null,
};

// ─────────────────────────────────────────────────────────
//  UNREAD MESSAGES
// ─────────────────────────────────────────────────────────

/**
 * Push a new message into the unread store.
 */
function addUnreadMessage(chatId, chatName, msg) {
  if (!unreadChats.has(chatId)) {
    unreadChats.set(chatId, { chatName, messages: [] });
  }

  const chat = unreadChats.get(chatId);
  
  // If it's a group and we have a cached name, use it
  if (chatId.endsWith("@g.us") && groupNames.has(chatId)) {
    chat.chatName = groupNames.get(chatId);
  } else {
    // Update name if it's better than what we have
    chat.chatName = chatName || chat.chatName || chatId;
  }

  chat.messages.push(msg);

  // Cap per-chat messages
  if (chat.messages.length > config.maxUnreadPerChat) {
    chat.messages = chat.messages.slice(-config.maxUnreadPerChat);
  }

  // ── Track pending reply for PERSONAL chats only ─────────
  // Groups are intentionally excluded from the auto-responder.
  const isGroup = chatId.endsWith("@g.us");
  if (!isGroup && !msg.fromMe) {
    const now = msg.timestamp || Date.now();
    const existing = pendingReplies.get(chatId);
    if (existing) {
      existing.lastIncomingAt = now;
      existing.chatName = chat.chatName;
    } else {
      pendingReplies.set(chatId, {
        firstUnansweredAt: now,
        lastIncomingAt: now,
        chatName: chat.chatName,
      });
    }
  }
}

/**
 * Mark a personal chat as replied-to. Called when a fromMe message is observed
 * for the chat (the user answered), which resets the unanswered timer so the
 * auto-responder won't fire.
 * @param {string} chatId
 */
function markReplied(chatId) {
  if (!chatId) return;
  pendingReplies.delete(chatId);
}

/**
 * Return personal chats that have gone unanswered for at least `thresholdMs`.
 * @param {number} thresholdMs — minimum age (ms) of the first unanswered message
 * @returns {Array<{ chat_id: string, chat_name: string, first_unanswered_at: number, waiting_ms: number }>}
 */
function getPendingPersonalReplies(thresholdMs) {
  const now = Date.now();
  const out = [];
  for (const [chatId, info] of pendingReplies) {
    const waiting = now - info.firstUnansweredAt;
    if (waiting >= thresholdMs) {
      out.push({
        chat_id: chatId,
        chat_name: info.chatName || chatId,
        first_unanswered_at: info.firstUnansweredAt,
        waiting_ms: waiting,
      });
    }
  }
  return out;
}

/**
 * Return the buffered messages for a single chat (read or unread, as retained
 * in the in-memory store). Used by the backend for group summaries and
 * action-item extraction.
 * @param {string} chatId
 * @returns {{ chat_id: string, chat_name: string, is_group: boolean, messages: Array }}
 */
function getChatMessages(chatId) {
  const chat = unreadChats.get(chatId);
  if (!chat) {
    return {
      chat_id: chatId,
      chat_name: groupNames.get(chatId) || chatId,
      is_group: chatId.endsWith("@g.us"),
      messages: [],
    };
  }
  return {
    chat_id: chatId,
    chat_name: chat.chatName,
    is_group: chatId.endsWith("@g.us"),
    messages: chat.messages.map((m) => ({
      id: m.id,
      text: m.text || "[media]",
      timestamp: m.timestamp,
      sender: m.sender,
      from_me: m.fromMe,
    })),
  };
}

/**
 * Cache a group name.
 */
function setGroupName(groupId, name) {
  if (name && name !== groupId) {
    groupNames.set(groupId, name);
  }
}

/**
 * Get all unread chats as a summary array.
 * @returns {Array<{ chat_id, chat_name, unread_count, last_message, timestamp }>}
 */
function getUnreadSummary() {
  const summary = [];

  for (const [chatId, chat] of unreadChats) {
    if (chat.messages.length === 0) continue;

    const lastMsg = chat.messages[chat.messages.length - 1];
    summary.push({
      chat_id: chatId,
      chat_name: chat.chatName,
      unread_count: chat.messages.length,
      last_message: lastMsg.text || "[media]",
      timestamp: lastMsg.timestamp,
      messages: chat.messages.map((m) => ({
        id: m.id,
        text: m.text || "[media]",
        timestamp: m.timestamp,
        sender: m.sender,
        from_me: m.fromMe,
      })),
    });
  }

  // Sort by most recent first
  summary.sort((a, b) => b.timestamp - a.timestamp);
  return summary;
}

/**
 * Clear unread messages for a specific chat or all chats.
 * @param {string} [chatId] — If omitted, clears all.
 */
function clearUnread(chatId) {
  if (chatId) {
    unreadChats.delete(chatId);
    pendingReplies.delete(chatId);
  } else {
    unreadChats.clear();
    pendingReplies.clear();
  }
}

// ─────────────────────────────────────────────────────────
//  MISSED CALLS
// ─────────────────────────────────────────────────────────

/**
 * Record a missed call event.
 */
function addMissedCall(callEvent) {
  missedCalls.push({
    from: callEvent.from,
    from_name: callEvent.fromName || callEvent.from,
    timestamp: callEvent.timestamp || Date.now(),
    status: callEvent.status || "missed",
    is_video: callEvent.isVideo || false,
    chat_id: callEvent.chatId || callEvent.from,
  });

  // Cap total missed calls
  if (missedCalls.length > config.maxMissedCalls) {
    missedCalls.splice(0, missedCalls.length - config.maxMissedCalls);
  }
}

/**
 * Get all missed calls.
 * @param {number} [since] — Unix timestamp (ms). Only return calls after this time.
 * @returns {Array}
 */
function getMissedCalls(since) {
  if (since) {
    return missedCalls.filter((c) => c.timestamp >= since);
  }
  return [...missedCalls];
}

/**
 * Clear missed calls.
 */
function clearMissedCalls() {
  missedCalls.length = 0;
}

// ─────────────────────────────────────────────────────────
//  CONNECTION STATE
// ─────────────────────────────────────────────────────────

function setConnectionState(updates) {
  Object.assign(connectionState, updates);
}

function getConnectionState() {
  return { ...connectionState };
}

// ─────────────────────────────────────────────────────────
//  CONTACTS
// ─────────────────────────────────────────────────────────

/**
 * Upsert contacts from Baileys contacts.upsert / contacts.update events.
 * @param {Array<{ id: string, name?: string, notify?: string, pushName?: string, short?: string }>} contactList
 */
function upsertContacts(contactList) {
  for (const c of contactList) {
    if (!c.id) continue;
    const existing = contacts.get(c.id) || {};
    contacts.set(c.id, {
      name: c.name || c.verifiedName || existing.name || null,
      notify: c.notify || existing.notify || null,
      pushName: c.pushName || c.pushname || existing.pushName || null,
      short: c.short || existing.short || null,
    });
  }
  console.log(`[STORE] Contacts cache updated: ${contacts.size} total`);

  // Persist to disk
  try {
    const obj = Object.fromEntries(contacts);
    fs.writeFileSync(CONTACTS_CACHE_FILE, JSON.stringify(obj, null, 2));
  } catch (err) {
    console.warn(`[STORE] Failed to persist contacts: ${err.message}`);
  }
}

/**
 * Search contacts and unread chats by display name (case-insensitive substring).
 * @param {string} query — name to search for
 * @returns {Array<{ chat_id: string, chat_name: string, is_group: boolean }>}
 */
function searchChats(query) {
  if (!query || !query.trim()) return [];

  const q = query.trim().toLowerCase();
  const results = new Map(); // deduplicate by JID

  // 0. Search contact aliases FIRST (highest priority, user-defined)
  for (const [alias, info] of contactAliases) {
    if (alias.includes(q) || q.includes(alias)) {
      results.set(info.jid, {
        chat_id: info.jid,
        chat_name: info.displayName,
        is_group: info.jid.endsWith("@g.us"),
      });
    }
  }

  // 1. Search contacts cache
  for (const [jid, info] of contacts) {
    if (results.has(jid)) continue;
    const searchable = [
      info.name,
      info.notify,
      info.pushName,
      info.short,
    ].filter(Boolean).join(" ").toLowerCase();

    if (searchable.includes(q)) {
      results.set(jid, {
        chat_id: jid,
        chat_name: info.notify || info.name || info.pushName || info.short || jid,
        is_group: jid.endsWith("@g.us"),
      });
    }
  }

  // 2. Search unread chats (may have names not in contacts cache)
  for (const [chatId, chat] of unreadChats) {
    if (results.has(chatId)) continue; // already found
    const chatName = (chat.chatName || "").toLowerCase();
    if (chatName.includes(q)) {
      results.set(chatId, {
        chat_id: chatId,
        chat_name: chat.chatName || chatId,
        is_group: chatId.endsWith("@g.us"),
      });
    }
  }

  // 3. Search group names cache
  for (const [groupId, groupName] of groupNames) {
    if (results.has(groupId)) continue;
    if ((groupName || "").toLowerCase().includes(q)) {
      results.set(groupId, {
        chat_id: groupId,
        chat_name: groupName,
        is_group: true,
      });
    }
  }

  return Array.from(results.values());
}

/**
 * Return cached contacts and aliases for backend-side natural-name resolution.
 * @returns {Array<{ id, jid, name, notify, pushName, short, displayName, is_group }>}
 */
function getContacts() {
  const rows = [];

  for (const [jid, info] of contacts) {
    rows.push({
      id: jid,
      jid,
      name: info.name || null,
      notify: info.notify || null,
      pushName: info.pushName || null,
      short: info.short || null,
      displayName: info.notify || info.name || info.pushName || info.short || jid,
      is_group: jid.endsWith("@g.us"),
      source: "contacts_cache",
    });
  }

  for (const [alias, info] of contactAliases) {
    rows.push({
      id: info.jid,
      jid: info.jid,
      name: alias,
      notify: info.displayName,
      pushName: null,
      short: null,
      displayName: info.displayName,
      is_group: info.jid.endsWith("@g.us"),
      source: "contact_aliases",
    });
  }

  return rows;
}

module.exports = {
  // Unread
  addUnreadMessage,
  getUnreadSummary,
  clearUnread,
  setGroupName,
  getChatMessages,
  // Pending replies / auto-responder
  markReplied,
  getPendingPersonalReplies,
  // Missed calls
  addMissedCall,
  getMissedCalls,
  clearMissedCalls,
  // Connection
  setConnectionState,
  getConnectionState,
  // Contacts
  upsertContacts,
  searchChats,
  getContacts,
};
