/**
 * config.js — Central configuration for the WhatsApp connector.
 * Reads from environment variables with sensible defaults.
 */

const path = require("path");
require("dotenv").config({ path: path.resolve(__dirname, "../.env") });

const config = {
  /** REST API port */
  port: parseInt(process.env.PORT || "3100", 10),

  /** Jarvis FastAPI backend URL */
  jarvisUrl: process.env.JARVIS_BACKEND_URL || "http://localhost:8002",

  /** Directory to persist Baileys auth credentials */
  authDir: path.resolve(__dirname, "../auth_state"),

  /** SQLite database path for rate limiting */
  dbPath: path.resolve(__dirname, "../rate_limit.db"),

  /**
   * Approved contacts for missed-call auto-reply.
   * Format: E.164 without '+' prefix (e.g., "919876543210").
   */
  approvedContacts: (process.env.APPROVED_CONTACTS || "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean),

  /** Cooldown period in hours before re-sending auto-reply to the same contact */
  autoReplyCooldownHours: parseFloat(
    process.env.AUTO_REPLY_COOLDOWN_HOURS || "12"
  ),

  /** The auto-reply message text */
  autoReplyMessage:
    process.env.AUTO_REPLY_MESSAGE ||
    "Hi, I am Jarvis, Rudra's personal assistant. Sir is a bit busy at the moment, but I assure you he will get back to you shortly.",

  /** Pino log level */
  logLevel: process.env.LOG_LEVEL || "info",

  /** Maximum number of unread messages to store per chat */
  maxUnreadPerChat: 100,

  /** Maximum number of missed calls to retain */
  maxMissedCalls: 200,
};

module.exports = config;
