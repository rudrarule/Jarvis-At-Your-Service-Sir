"""
whatsapp_service.py — Twilio WhatsApp Integration for J.A.R.V.I.S
Handles outbound message delivery and busy-mode gating.
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Twilio Config ─────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "")  # e.g. "whatsapp:+14155238886"

# ── Busy Mode ─────────────────────────────────────────────
BUSY_MODE: bool = False
BUSY_RESPONSE = "Apologies, sir is currently busy. Please call later."

# ── Allowed Users (empty = allow all) ─────────────────────
# Add phone numbers like "whatsapp:+919876543210"
ALLOWED_USERS: list[str] = []


def is_busy() -> bool:
    """Check if Jarvis is in busy mode."""
    return BUSY_MODE


def set_busy(state: bool):
    """Toggle busy mode on/off."""
    global BUSY_MODE
    BUSY_MODE = state


def is_user_allowed(sender: str) -> bool:
    """Check if the sender is in the allowed users list. Empty list = allow all."""
    if not ALLOWED_USERS:
        return True
    return sender in ALLOWED_USERS


async def send_whatsapp_message(to: str, message: str) -> bool:
    """
    Send a WhatsApp message via Twilio REST API.
    Returns True on success, False on failure.
    """
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
        print("[WA] ERROR: Twilio credentials not configured.")
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"

    # Twilio has a 1600 char limit for WhatsApp — truncate gracefully
    if len(message) > 1500:
        message = message[:1497] + "..."

    payload = {
        "From": TWILIO_WHATSAPP_NUMBER,
        "To": to,
        "Body": message,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                data=payload,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            )
            if response.status_code in (200, 201):
                print(f"[WA] OK: Message sent to {to}")
                return True
            else:
                print(f"[WA] ERROR: Twilio {response.status_code}: {response.text}")
                return False
    except Exception as e:
        print(f"[WA] ERROR: Send failed - {type(e).__name__}: {e}")
        return False
