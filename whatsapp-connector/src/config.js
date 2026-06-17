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

  /** The auto-reply message text (used for missed calls) */
  autoReplyMessage:
    process.env.AUTO_REPLY_MESSAGE ||
    "Hi, I am Jarvis, Rudra's personal assistant. Sir is a bit busy at the moment, but I assure you he will get back to you shortly.",

  /**
   * Delayed auto-responder for UNANSWERED personal messages.
   * If an incoming 1:1 message goes unanswered for this many hours, Jarvis
   * sends a polite professional holding reply. Group chats are excluded.
   */
  unansweredReplyDelayHours: parseFloat(
    process.env.UNANSWERED_REPLY_DELAY_HOURS || "1"
  ),

  /** How often (ms) the sweeper checks for unanswered personal chats */
  unansweredSweepIntervalMs: parseInt(
    process.env.UNANSWERED_SWEEP_INTERVAL_MS || "300000", // 5 minutes
    10
  ),

  /** Whether the delayed auto-responder is enabled */
  unansweredReplyEnabled:
    (process.env.UNANSWERED_REPLY_ENABLED || "true").toLowerCase() !== "false",

  /** The professional holding message for unanswered personal chats */
  unansweredReplyMessage:
    process.env.UNANSWERED_REPLY_MESSAGE ||
    "Hello, this is Jarvis, Rudraksh's personal assistant. He's occupied at the moment and hasn't been able to get to your message yet, but I've noted it and will make sure it reaches him shortly. Thank you for your patience.",

  /** Pino log level */
  logLevel: process.env.LOG_LEVEL || "info",

  /** Maximum number of unread messages to store per chat */
  maxUnreadPerChat: 100,

  /** Maximum number of missed calls to retain */
  maxMissedCalls: 200,
};

module.exports = config;
