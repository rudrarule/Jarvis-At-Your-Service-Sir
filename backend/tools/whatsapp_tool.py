"""
whatsapp_tool.py — WhatsApp tool functions for J.A.R.V.I.S
Provides tool-callable functions that the LLM can invoke to check
WhatsApp messages, missed calls, and send messages via the Baileys connector.
"""

from services.whatsapp_baileys_service import (
    get_whatsapp_briefing,
    get_unread_summary,
    get_missed_calls,
    send_whatsapp_message,
    clear_unread,
    clear_missed_calls,
)


async def whatsapp_briefing() -> str:
    """Get a full WhatsApp briefing — unread messages and missed calls."""
    return await get_whatsapp_briefing()


async def whatsapp_unread() -> str:
    """Get unread WhatsApp messages summary."""
    from services.whatsapp_formatter import format_whatsapp_briefing
    data = await get_unread_summary()

    if data.get("error"):
        return f"I'm unable to reach the WhatsApp connector, sir. {data['error']}"

    # Format as a briefing with 0 missed calls
    return format_whatsapp_briefing(data, {"count": 0, "calls": []})


async def whatsapp_missed_calls() -> str:
    """Get missed WhatsApp calls."""
    from services.whatsapp_formatter import format_whatsapp_briefing
    data = await get_missed_calls()

    if data.get("error"):
        return f"I'm unable to reach the WhatsApp connector, sir. {data['error']}"

    # Format as a briefing with 0 unread messages
    return format_whatsapp_briefing({"chats": []}, data)


async def whatsapp_send(contact: str, message: str) -> str:
    """Send a WhatsApp message to a contact."""
    from services.contact_resolver import resolve_contact

    resolved_contact = contact
    resolved = await resolve_contact(contact)
    if resolved.get("status") == "single":
        match = resolved["match"]
        resolved_contact = match["chat_id"]
    elif resolved.get("status") == "multiple":
        options = ", ".join(m["chat_name"] for m in resolved.get("matches", [])[:5])
        return f"I found multiple contacts for {contact}: {options}. Please be more specific, sir."
    elif "@" not in contact:
        return f"I couldn't find a WhatsApp contact named {contact}, sir."

    result = await send_whatsapp_message(resolved_contact, message)

    if result.get("success"):
        return f"Message sent to {contact}, sir."
    else:
        return f"Failed to send message, sir. {result.get('error', 'Unknown error')}"


async def whatsapp_summarize_group(group_name: str = "") -> str:
    """Summarize recent activity in a WhatsApp group (e.g. the family group)."""
    from services.whatsapp_intelligence import summarize_group
    return await summarize_group(group_name or None)


async def whatsapp_action_items() -> str:
    """Show only the unread WhatsApp messages that require a reply or action."""
    from services.whatsapp_intelligence import action_items
    return await action_items()
