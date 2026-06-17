"""
wa_send_workflow.py — Outbound WhatsApp Messaging Workflow Engine
=================================================================
Graph-ready workflow with isolated node functions for sending WhatsApp
messages via the Baileys connector. Each node function can later map
directly to a LangGraph node without rewrite.

Workflow:
    1. node_extract_params   — LLM extracts contact name + message intent
    2. node_resolve_contact  — Search Baileys connector for contact JID
    3. node_draft_message    — LLM drafts a natural message
    4. node_confirm_send     — Build confirmation prompt for voice
    5. node_handle_confirmation — Process yes/no from user
    6. node_send_message     — Send via Baileys (hard gate: requires confirmed=True)
    7. node_handle_failure   — Graceful error responses
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ── Ollama Config (mirrors llm_service.py) ────────────────
OLLAMA_URL = "http://localhost:11434"
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


# ── Workflow State ────────────────────────────────────────

@dataclass
class WASendState:
    """
    Structured state for the outbound messaging workflow.
    Designed for direct migration to LangGraph state schema.
    """
    session_id: str
    raw_message: str                         # original user utterance
    contact_query: str = ""                  # extracted contact name ("Mom")
    message_intent: str = ""                 # extracted message instruction
    matches: list[dict] = field(default_factory=list)  # search results
    selected_contact: str = ""               # resolved display name
    selected_chat_id: str = ""               # resolved JID
    draft_message: str = ""                  # LLM-drafted natural text
    confirmed: bool = False                  # explicit user confirmation
    status: str = "init"                     # workflow status
    error: Optional[str] = None

    # Valid statuses:
    #   init -> extracting -> resolving -> drafting ->
    #   pending_confirm -> sending -> sent
    #   pending_disambiguation (multiple contacts)
    #   cancelled | error


# ── Session-scoped Workflow Store ─────────────────────────

_active_workflows: dict[str, WASendState] = {}


def get_active_workflow(session_id: str) -> Optional[WASendState]:
    """Retrieve the active workflow for a session, if any."""
    return _active_workflows.get(session_id)


def clear_workflow(session_id: str) -> None:
    """Remove workflow state for a session."""
    _active_workflows.pop(session_id, None)


def create_workflow(session_id: str, raw_message: str) -> WASendState:
    """Create and store a new workflow state."""
    state = WASendState(session_id=session_id, raw_message=raw_message)
    _active_workflows[session_id] = state
    return state


# ── Node 1: Extract Parameters (LLM) ─────────────────────

async def node_extract_params(state: WASendState) -> WASendState:
    """
    Use llama3.2:1b to extract contact name and message intent
    from the raw user utterance. No hardcoded regex patterns.
    
    Example:
        "Message Mom that I have left for home"
        → contact_query="Mom", message_intent="I have left for home"
    """
    state.status = "extracting"

    prompt = """You are a parameter extractor. Given a user message that asks to send a WhatsApp message, extract:
1. CONTACT: The recipient's name or identifier
2. MESSAGE: What the user wants to say to the recipient

Reply ONLY in this exact JSON format, nothing else:
{"contact": "<name>", "message": "<what to say>"}

Examples:
User: "Message Mom that I have left for home"
{"contact": "Mom", "message": "I have left for home"}

User: "Tell Dad I will be late"
{"contact": "Dad", "message": "I will be late"}

User: "Text Sarah saying the meeting is at 3"
{"contact": "Sarah", "message": "the meeting is at 3"}

User: "Send a WhatsApp to John that the project is done"
{"contact": "John", "message": "the project is done"}

User: "Let Mom know I'm on my way"
{"contact": "Mom", "message": "I'm on my way"}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": state.raw_message},
                    ],
                    "stream": False,
                    "options": {"num_ctx": 2048, "num_predict": 128, "temperature": 0.1},
                    "keep_alive": "5m",
                },
            )
            response.raise_for_status()
            raw = response.json()["message"]["content"].strip()

            # Parse the JSON from the LLM response
            # Handle potential markdown wrapping
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)

            state.contact_query = parsed.get("contact", "").strip()
            state.message_intent = parsed.get("message", "").strip()

            if not state.contact_query or not state.message_intent:
                state.status = "error"
                state.error = "Could not understand the contact or message from your request."
                return state

            print(f"[WA_SEND] Extracted: contact='{state.contact_query}', message='{state.message_intent}'")
            return state

    except (json.JSONDecodeError, KeyError) as e:
        print(f"[WA_SEND] Extract params parse error: {e}, raw='{raw}'")
        state.status = "error"
        state.error = "I couldn't parse the contact and message from your request, sir."
        return state
    except Exception as e:
        print(f"[WA_SEND] Extract params error: {e}")
        state.status = "error"
        state.error = "I encountered an error understanding your message, sir."
        return state


# ── Node 2: Resolve Contact ──────────────────────────────

async def node_resolve_contact(state: WASendState) -> WASendState:
    """
    Search the Baileys connector for the contact by name.
    0 matches → error. 1 match → auto-select. >1 → disambiguation.
    """
    from services.contact_resolver import resolve_contact
    from services.whatsapp_baileys_service import search_chats

    state.status = "resolving"

    resolved = await resolve_contact(state.contact_query)
    if resolved.get("status") == "single":
        match = resolved["match"]
        state.selected_contact = match["chat_name"]
        state.selected_chat_id = match["chat_id"]
        print(f"[WA_SEND] Resolved contact: {state.selected_contact} ({state.selected_chat_id}) via {match.get('match_type')}")
        return state

    if resolved.get("status") == "multiple":
        matches = resolved.get("matches", [])
        personal_matches = [m for m in matches if not m.get("is_group")]
        state.matches = personal_matches or matches
        state.status = "pending_disambiguation"
        print(f"[WA_SEND] Multiple resolver matches ({len(state.matches)}): {[m['chat_name'] for m in state.matches]}")
        return state

    result = await search_chats(state.contact_query)

    if result.get("error"):
        state.status = "error"
        state.error = f"I can't reach the WhatsApp connector, sir. {result['error']}"
        return state

    matches = result.get("matches", [])
    # Filter out groups for direct messaging (usually you message people, not groups)
    # But keep groups if the user explicitly seems to want a group
    personal_matches = [m for m in matches if not m.get("is_group")]
    
    # If no personal matches but groups exist, use all matches
    if not personal_matches and matches:
        personal_matches = matches

    state.matches = personal_matches

    if len(personal_matches) == 0:
        state.status = "error"
        state.error = f"I couldn't find a contact named '{state.contact_query}' in your WhatsApp, sir."
        return state

    if len(personal_matches) == 1:
        # Single match — auto-select
        match = personal_matches[0]
        state.selected_contact = match["chat_name"]
        state.selected_chat_id = match["chat_id"]
        print(f"[WA_SEND] Resolved contact: {state.selected_contact} ({state.selected_chat_id})")
        return state

    # Multiple matches — need disambiguation
    state.status = "pending_disambiguation"
    print(f"[WA_SEND] Multiple matches ({len(personal_matches)}): {[m['chat_name'] for m in personal_matches]}")
    return state


# ── Node 3: Draft Message (LLM) ──────────────────────────

async def node_draft_message(state: WASendState) -> WASendState:
    """
    Use llama3.2:1b to convert the user's instruction into
    a natural, ready-to-send WhatsApp message.
    """
    state.status = "drafting"

    prompt = f"""You are a message drafter for a WhatsApp assistant. Convert the user's instruction into a natural, friendly WhatsApp message.

Rules:
- Write a brief, natural message as if the user is texting the recipient
- Start with a greeting appropriate for the relationship (e.g., "Hi Mom", "Hey Dad", "Hi Sarah")
- Keep it concise — 1-2 sentences max
- Do NOT add any explanation or commentary
- Reply with ONLY the message text, nothing else

Recipient: {state.selected_contact}
User wants to say: {state.message_intent}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Draft a message to {state.selected_contact}: {state.message_intent}"},
                    ],
                    "stream": False,
                    "options": {"num_ctx": 2048, "num_predict": 128, "temperature": 0.7},
                    "keep_alive": "5m",
                },
            )
            response.raise_for_status()
            draft = response.json()["message"]["content"].strip()

            # Strip any wrapping quotes the LLM might add
            if draft.startswith('"') and draft.endswith('"'):
                draft = draft[1:-1]
            if draft.startswith("'") and draft.endswith("'"):
                draft = draft[1:-1]

            state.draft_message = draft
            print(f"[WA_SEND] Draft: '{draft}'")
            return state

    except Exception as e:
        print(f"[WA_SEND] Draft message error: {e}")
        state.status = "error"
        state.error = "I encountered an error drafting your message, sir."
        return state


# ── Node 4: Confirm Send ─────────────────────────────────

def node_confirm_send(state: WASendState) -> str:
    """
    Build the confirmation prompt text.
    Returns the spoken text + __CONFIRM_MIC__ marker.
    """
    state.status = "pending_confirm"

    confirmation = (
        f"I've drafted a message to {state.selected_contact}: "
        f"'{state.draft_message}'. "
        f"Shall I send it, sir?"
    )

    print(f"[WA_SEND] Awaiting confirmation for: {state.draft_message}")
    return confirmation + "__CONFIRM_MIC__"


# ── Node 5: Handle Confirmation ──────────────────────────

def node_handle_confirmation(state: WASendState, user_response: str) -> WASendState:
    """
    Process the user's yes/no confirmation response.
    Uses simple pattern matching for binary yes/no — no LLM needed.
    """
    cleaned = user_response.strip().lower()

    positive = re.search(
        r"\b(yes|yeah|yep|yup|sure|send|go ahead|do it|send it|go for it|please|confirm|affirmative)\b",
        cleaned,
    )
    negative = re.search(
        r"\b(no|nah|nope|cancel|skip|stop|don't|abort|never mind|forget it)\b",
        cleaned,
    )

    if positive and not negative:
        state.confirmed = True
        print("[WA_SEND] User confirmed: YES")
    elif negative:
        state.confirmed = False
        state.status = "cancelled"
        print("[WA_SEND] User confirmed: NO")
    else:
        # Ambiguous — treat as negative for safety
        state.confirmed = False
        state.status = "cancelled"
        print(f"[WA_SEND] Ambiguous response: '{user_response}', treating as cancel for safety")

    return state


# ── Node 6: Send Message ─────────────────────────────────

async def node_send_message(state: WASendState) -> WASendState:
    """
    Send the drafted message via Baileys connector.
    SAFETY: Hard gate — refuses to execute unless confirmed=True.
    """
    from services.whatsapp_baileys_service import send_whatsapp_message

    # Hard safety gate
    if not state.confirmed:
        state.status = "error"
        state.error = "Send blocked: confirmation was not received."
        print("[WA_SEND] SAFETY: Send blocked — not confirmed")
        return state

    state.status = "sending"

    result = await send_whatsapp_message(state.selected_chat_id, state.draft_message)

    if result.get("success"):
        state.status = "sent"
        print(f"[WA_SEND] Message sent to {state.selected_contact} ({state.selected_chat_id})")
    else:
        state.status = "error"
        state.error = result.get("error", "Unknown send error")
        print(f"[WA_SEND] Send failed: {state.error}")

    return state


# ── Node 7: Handle Failure ───────────────────────────────

def node_handle_failure(state: WASendState) -> str:
    """Generate a graceful error response based on the failure mode."""
    error = state.error or "An unknown error occurred."

    # Clear the failed workflow
    clear_workflow(state.session_id)

    return f"I'm sorry, sir. {error}"


# ── Disambiguation Helper ─────────────────────────────────

def build_disambiguation_prompt(state: WASendState) -> str:
    """Build a voice prompt listing multiple contact matches."""
    names = [m["chat_name"] for m in state.matches]
    options = ", ".join(f"{i+1}. {name}" for i, name in enumerate(names))

    return (
        f"I found multiple contacts matching '{state.contact_query}': "
        f"{options}. "
        f"Which one would you like to message, sir?"
        f"__CONFIRM_MIC__"
    )


def handle_disambiguation_response(state: WASendState, user_response: str) -> WASendState:
    """Process the user's disambiguation selection."""
    cleaned = user_response.strip().lower()

    # Try to match by number
    num_match = re.search(r"\b(\d+)\b", cleaned)
    if num_match:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(state.matches):
            match = state.matches[idx]
            state.selected_contact = match["chat_name"]
            state.selected_chat_id = match["chat_id"]
            state.status = "resolving"  # continue workflow
            print(f"[WA_SEND] Disambiguated by number: {state.selected_contact}")
            return state

    # Try to match by name
    for match in state.matches:
        if match["chat_name"].lower() in cleaned or cleaned in match["chat_name"].lower():
            state.selected_contact = match["chat_name"]
            state.selected_chat_id = match["chat_id"]
            state.status = "resolving"
            print(f"[WA_SEND] Disambiguated by name: {state.selected_contact}")
            return state

    # Check for cancel
    if re.search(r"\b(cancel|skip|never mind|forget it|no)\b", cleaned):
        state.status = "cancelled"
        return state

    # Couldn't resolve
    state.status = "error"
    state.error = "I couldn't determine which contact you meant, sir. Please try again with a more specific name."
    return state
