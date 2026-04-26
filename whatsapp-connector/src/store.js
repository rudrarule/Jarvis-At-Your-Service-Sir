/**
 * store.js — In-memory store for unread messages and missed calls.
 * Event-driven: data is pushed in by Baileys event handlers,
 * read out by the REST API.  No polling.
 */

const config = require("./config");

// ── Unread messages store ────────────────────────────────
// Map<chatId, { chatName, messages: Array<{ id, text, timestamp, fromMe, sender }> }>
const unreadChats = new Map();

// ── Missed calls store ──────────────────────────────────
// Array<{ from, timestamp, status, isVideo, chatId }>
const missedCalls = [];

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
  } else {
    unreadChats.clear();
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

module.exports = {
  // Unread
  addUnreadMessage,
  getUnreadSummary,
  clearUnread,
  setGroupName,
  // Missed calls
  addMissedCall,
  getMissedCalls,
  clearMissedCalls,
  // Connection
  setConnectionState,
  getConnectionState,
};
