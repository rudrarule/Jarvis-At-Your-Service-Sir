/**
 * db.js — SQLite store for auto-reply rate limiting.
 * Uses sql.js (pure JS, no native compilation needed).
 * Tracks when the last auto-reply was sent to each contact
 * to prevent spamming the same person.
 */

const initSqlJs = require("sql.js");
const fs = require("fs");
const config = require("./config");

let db = null;
let sqlReady = null; // Promise that resolves when DB is ready

/**
 * Initialise the SQLite database and create tables if needed.
 * Returns a promise — call once at startup, then use sync helpers.
 */
async function initDb() {
  if (db) return db;

  const SQL = await initSqlJs();

  // Load existing DB file if present
  if (fs.existsSync(config.dbPath)) {
    try {
      const fileBuffer = fs.readFileSync(config.dbPath);
      db = new SQL.Database(fileBuffer);
      console.log("[DB] Loaded existing database from", config.dbPath);
    } catch (err) {
      console.warn("[DB] Failed to load DB, creating fresh:", err.message);
      db = new SQL.Database();
    }
  } else {
    db = new SQL.Database();
    console.log("[DB] Created new database.");
  }

  db.run(`
    CREATE TABLE IF NOT EXISTS auto_replies (
      contact_id  TEXT PRIMARY KEY,
      last_sent   INTEGER NOT NULL,
      message     TEXT
    );
  `);

  console.log("[DB] SQLite initialised (sql.js) →", config.dbPath);
  return db;
}

/**
 * Persist the in-memory database to disk.
 */
function saveDb() {
  if (!db) return;
  try {
    const data = db.export();
    const buffer = Buffer.from(data);
    fs.writeFileSync(config.dbPath, buffer);
  } catch (err) {
    console.error("[DB] Failed to save database:", err.message);
  }
}

/**
 * Check if we can send an auto-reply to this contact.
 * Returns true if no reply was sent within the cooldown window.
 *
 * @param {string} contactId — JID (e.g., "919876543210@s.whatsapp.net")
 * @returns {boolean}
 */
function canAutoReply(contactId) {
  if (!db) return false;

  const result = db.exec(
    "SELECT last_sent FROM auto_replies WHERE contact_id = ?",
    [contactId]
  );

  if (!result.length || !result[0].values.length) return true;

  const lastSent = result[0].values[0][0];
  const cooldownMs = config.autoReplyCooldownHours * 60 * 60 * 1000;
  const elapsed = Date.now() - lastSent;

  return elapsed >= cooldownMs;
}

/**
 * Record that an auto-reply was sent to this contact right now.
 *
 * @param {string} contactId
 * @param {string} message
 */
function recordAutoReply(contactId, message) {
  if (!db) return;

  db.run(
    `INSERT OR REPLACE INTO auto_replies (contact_id, last_sent, message)
     VALUES (?, ?, ?)`,
    [contactId, Date.now(), message]
  );

  saveDb();
}

/**
 * Get all auto-reply records (for debugging / API exposure).
 * @returns {Array<{contact_id: string, last_sent: number, message: string}>}
 */
function getAllAutoReplies() {
  if (!db) return [];

  const result = db.exec("SELECT * FROM auto_replies ORDER BY last_sent DESC");
  if (!result.length) return [];

  return result[0].values.map((row) => ({
    contact_id: row[0],
    last_sent: row[1],
    message: row[2],
  }));
}

/**
 * Clean up old records beyond the cooldown window.
 */
function purgeExpired() {
  if (!db) return;

  const cutoff = Date.now() - config.autoReplyCooldownHours * 60 * 60 * 1000;
  db.run("DELETE FROM auto_replies WHERE last_sent < ?", [cutoff]);
  saveDb();
}

/**
 * Close the database connection.
 */
function closeDb() {
  if (db) {
    saveDb();
    db.close();
    db = null;
    console.log("[DB] Database closed.");
  }
}

module.exports = {
  initDb,
  canAutoReply,
  recordAutoReply,
  getAllAutoReplies,
  purgeExpired,
  closeDb,
};
