"""
whatsapp_intelligence.py — LLM-backed WhatsApp reasoning for J.A.R.V.I.S

Builds on the data-only Baileys connector. All reasoning (summarization,
action-item extraction) stays here in Python via the shared `call_claude`
Bedrock helper. The connector never sees a prompt.

Public functions:
  - summarize_group(group_name)  → conversational summary of a group thread
  - action_items()               → only the unread messages that need a reply/action
"""

import os
from typing import Optional

from services.whatsapp_baileys_service import (
    get_unread_summary,
    get_chat_messages,
    search_chats,
)

# Auto-reply boilerplate we never want to feed into summaries.
_AUTO_REPLY_FRAGMENTS = (
    "this is jarvis",
    "rudra's personal assistant",
    "rudraksh's personal assistant",
    "he will get back to you",
    "make sure it reaches him",
)

# Default group used when the user just says "summarize the family group"
# without naming one. Override via the FAMILY_GROUP env var or by passing an
# explicit name to summarize_group().
DEFAULT_FAMILY_GROUP = os.getenv("FAMILY_GROUP", "Family")

# Cap how many messages we send to the model to keep latency/cost sane.
_MAX_MESSAGES = 60


def _is_boilerplate(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    return any(frag in t for frag in _AUTO_REPLY_FRAGMENTS)


def _render_transcript(messages: list[dict], limit: int = _MAX_MESSAGES) -> str:
    """Turn raw connector messages into a plain-text transcript for the LLM."""
    lines = []
    for m in messages[-limit:]:
        text = (m.get("text") or "").strip()
        if _is_boilerplate(text):
            continue
        if m.get("from_me"):
            sender = "You"
        else:
            sender = m.get("sender") or "Someone"
        lines.append(f"{sender}: {text}")
    return "\n".join(lines)


async def _resolve_group(group_name: str) -> Optional[dict]:
    """Find the best group match for a name via the connector's search."""
    result = await search_chats(group_name)
    matches = [m for m in result.get("matches", []) if m.get("is_group")]
    if not matches:
        # Fall back to any match (some groups may not be flagged is_group in cache)
        matches = result.get("matches", [])
    if not matches:
        return None
    # Prefer an exact (case-insensitive) name match, else the first result.
    lowered = group_name.strip().lower()
    for m in matches:
        if (m.get("chat_name") or "").strip().lower() == lowered:
            return m
    return matches[0]


async def summarize_group(group_name: Optional[str] = None) -> str:
    """
    Summarize recent activity in a WhatsApp group.

    Args:
        group_name: Name of the group (e.g., "Family"). Falls back to
                    the FAMILY_GROUP default when omitted.

    Returns:
        A short spoken-style summary, or a helpful message if not found.
    """
    name = (group_name or DEFAULT_FAMILY_GROUP).strip()

    group = await _resolve_group(name)
    if not group:
        return (
            f"I couldn't find a group called '{name}' in your chats, sir. "
            "It may not have any recent activity cached yet."
        )

    chat = await get_chat_messages(group["chat_id"])
    if chat.get("error"):
        return f"I'm unable to reach the WhatsApp connector, sir. {chat['error']}"

    transcript = _render_transcript(chat.get("messages", []))
    display_name = group.get("chat_name") or name

    if not transcript.strip():
        return f"There's no recent activity to summarize in {display_name}, sir."

    # Import here to avoid a circular import at module load time.
    from services.llm_service import call_claude

    system = (
        "You are Jarvis, a concise British personal assistant. Summarize the "
        "following WhatsApp group conversation for your employer. Give a brief, "
        "natural spoken summary (2-4 sentences): who said what that matters, any "
        "decisions, plans, or questions directed at him. Skip greetings and chit-chat. "
        "Address him as 'sir'. Do not invent details that aren't in the transcript."
    )
    user = f"Group: {display_name}\n\nConversation:\n{transcript}"

    result = await call_claude(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    summary = (result.get("text") or "").strip()
    if not summary:
        return f"I wasn't able to summarize {display_name} just now, sir."
    return summary


async def action_items() -> str:
    """
    Scan unread WhatsApp messages and surface ONLY the ones that need the
    user's attention — a reply, a decision, or a real-world action.

    Returns:
        A short prioritized list (spoken-style), or an all-clear message.
    """
    data = await get_unread_summary()
    if data.get("error"):
        return f"I'm unable to reach the WhatsApp connector, sir. {data['error']}"

    chats = data.get("chats", [])
    blocks = []
    for chat in chats:
        chat_id = chat.get("chat_id", "")
        if any(x in chat_id.lower() for x in ("newsletter", "broadcast", "status@broadcast")):
            continue
        name = chat.get("chat_name") or chat_id
        is_group = chat_id.endswith("@g.us")
        msgs = []
        for m in chat.get("messages", []):
            text = (m.get("text") or "").strip()
            if _is_boilerplate(text) or text == "[media]":
                continue
            sender = m.get("sender") or name
            msgs.append(f"  - {sender}: {text}")
        if msgs:
            label = f"{name} (group)" if is_group else name
            blocks.append(f"Chat: {label}\n" + "\n".join(msgs))

    if not blocks:
        return "Nothing in your unread WhatsApp messages needs action, sir."

    transcript = "\n\n".join(blocks)

    from services.llm_service import call_claude

    system = (
        "You are Jarvis, a concise British personal assistant. From the unread "
        "WhatsApp messages below, identify ONLY the ones that genuinely require "
        "the user's action — a reply, a decision, a confirmation, a deadline, or a "
        "real task. Ignore FYIs, banter, forwards, newsletters, and auto-replies. "
        "Return a short prioritized list. For each item give the contact/group and "
        "what is being asked of him, in one line. If nothing needs action, say so. "
        "Address him as 'sir'. Do not invent anything not in the messages."
    )

    result = await call_claude(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": transcript},
        ]
    )
    answer = (result.get("text") or "").strip()
    if not answer:
        return "I couldn't assess your unread messages just now, sir."
    return answer
