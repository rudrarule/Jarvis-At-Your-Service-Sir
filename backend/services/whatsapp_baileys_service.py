"""
whatsapp_baileys_service.py — FastAPI integration with the Baileys WhatsApp Connector.

Provides async functions to communicate with the Node.js Baileys connector
running on localhost:3100. This replaces the Twilio-based WhatsApp service
with a self-hosted, zero-cost solution.

All summarization stays in Python/Jarvis. The Node connector is data-only.
"""

import os
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Connector URL ─────────────────────────────────────────
CONNECTOR_URL = os.getenv("WA_CONNECTOR_URL", "http://localhost:3100")
TIMEOUT = 10.0


# ── Health ────────────────────────────────────────────────

async def connector_health() -> dict:
    """Check if the Baileys connector is alive and connected."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{CONNECTOR_URL}/health")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"status": "offline", "error": str(e)}


# ── Unread Messages ──────────────────────────────────────

async def get_unread_summary() -> dict:
    """
    Fetch unread message summary from the connector.

    Returns:
        {
            "total_chats": int,
            "total_messages": int,
            "chats": [
                {
                    "chat_id": str,
                    "chat_name": str,
                    "unread_count": int,
                    "last_message": str,
                    "timestamp": int,
                    "messages": [...]
                }
            ]
        }
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{CONNECTOR_URL}/unread-summary")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {
            "total_chats": 0,
            "total_messages": 0,
            "chats": [],
            "error": "WhatsApp connector is not running",
        }
    except Exception as e:
        return {
            "total_chats": 0,
            "total_messages": 0,
            "chats": [],
            "error": f"Failed to fetch unread: {e}",
        }


# ── Missed Calls ─────────────────────────────────────────

async def get_missed_calls(since: Optional[int] = None) -> dict:
    """
    Fetch missed WhatsApp call events.

    Args:
        since: Unix timestamp (ms). Only return calls after this time.

    Returns:
        {
            "count": int,
            "calls": [
                {
                    "from": str,
                    "from_name": str,
                    "timestamp": int,
                    "status": str,
                    "is_video": bool,
                    "chat_id": str
                }
            ]
        }
    """
    try:
        params = {}
        if since is not None:
            params["since"] = since

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{CONNECTOR_URL}/missed-calls", params=params
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {
            "count": 0,
            "calls": [],
            "error": "WhatsApp connector is not running",
        }
    except Exception as e:
        return {"count": 0, "calls": [], "error": f"Failed to fetch calls: {e}"}


# ── Send Message ──────────────────────────────────────────

async def send_whatsapp_message(chat_id: str, text: str) -> dict:
    """
    Send a WhatsApp message through the Baileys connector.

    Args:
        chat_id: The recipient JID (e.g., "919876543210@s.whatsapp.net"
                 or just "919876543210")
        text:    The message body

    Returns:
        {"success": True, "chat_id": str} or {"error": str}
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{CONNECTOR_URL}/send-message",
                json={"chat_id": chat_id, "text": text},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"success": False, "error": "WhatsApp connector is not running"}
    except Exception as e:
        return {"success": False, "error": f"Send failed: {e}"}


# ── Clear Operations ─────────────────────────────────────

async def clear_unread(chat_id: Optional[str] = None) -> dict:
    """Clear unread messages, optionally for a specific chat."""
    try:
        payload = {}
        if chat_id:
            payload["chat_id"] = chat_id

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{CONNECTOR_URL}/clear-unread", json=payload
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def clear_missed_calls() -> dict:
    """Clear all missed call records."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{CONNECTOR_URL}/clear-calls")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Connection State ─────────────────────────────────────

async def get_connection_state() -> dict:
    """Get the current WhatsApp connection state."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{CONNECTOR_URL}/connection")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"status": "offline", "error": "Connector not running"}
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


# ── Briefing Helper ──────────────────────────────────────

async def get_whatsapp_briefing() -> str:
    """
    Generate a polished, voice-friendly briefing for Jarvis.
    Uses the whatsapp_formatter to post-process raw connector data.
    """
    from services.whatsapp_formatter import format_whatsapp_briefing
    
    try:
        # Fetch raw data
        unread = await get_unread_summary()
        if unread.get("error"):
            return f"WhatsApp connector error: {unread['error']}"
        
        # Debug log for inspection
        print(f"[WA DEBUG] Unread chats count: {len(unread.get('chats', []))}")
            
        missed_calls = await get_missed_calls()
        if missed_calls.get("error"):
            # If missed calls fail, we still try to format the unread messages
            missed_calls = {"count": 0, "calls": []}

        # Format for voice
        briefing = format_whatsapp_briefing(unread, missed_calls)
        
        # Log the final briefing string
        print(f"[WA DEBUG] Final Briefing: {briefing[:100]}...")
        
        return briefing

    except Exception as e:
        print(f"[WHATSAPP BRIEFING ERROR] {e}")
        return "I'm sorry sir, I encountered an error while compiling your WhatsApp briefing."
