/**
 * auth.js — Persistent multi-file auth state for Baileys.
 * Stores credentials in the filesystem so the QR code is only needed once.
 * Handles corruption recovery: if auth is broken, wipes and re-pairs.
 */

const {
  useMultiFileAuthState,
} = require("@whiskeysockets/baileys");
const fs = require("fs");
const path = require("path");
const config = require("./config");

/**
 * Initialise or restore the auth state.
 * If the auth directory is corrupted, it will be wiped for a fresh start.
 *
 * @returns {Promise<{ state: object, saveCreds: Function }>}
 */
async function getAuthState() {
  const dir = config.authDir;

  // Ensure directory exists
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
    console.log("[AUTH] Created fresh auth directory:", dir);
  }

  try {
    const { state, saveCreds } = await useMultiFileAuthState(dir);
    console.log("[AUTH] Auth state loaded successfully.");
    return { state, saveCreds };
  } catch (err) {
    console.error("[AUTH] Corrupted auth state detected. Wiping for fresh pairing...");
    console.error("[AUTH] Error was:", err.message);

    // Wipe the corrupted directory
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });

    // Retry
    const { state, saveCreds } = await useMultiFileAuthState(dir);
    return { state, saveCreds };
  }
}

/**
 * Wipe auth state entirely (for manual reset).
 */
function clearAuthState() {
  const dir = config.authDir;
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    console.log("[AUTH] Auth state cleared.");
  }
}

module.exports = { getAuthState, clearAuthState };
