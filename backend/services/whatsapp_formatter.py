"""
whatsapp_formatter.py — Post-processing for WhatsApp briefings.
Transforms raw connector data into a natural, voice-friendly Jarvis briefing.
"""
import re
import os
from datetime import datetime
from typing import List, Dict, Any

# Auto-reply message to ignore
AUTO_REPLY_TEXT = "Hi, I am Jarvis, Rudra's personal assistant. Sir is a bit busy at the moment, but I assure you he will get back to you shortly."

def format_whatsapp_briefing(unread_data: Dict[str, Any], missed_calls_data: Dict[str, Any]) -> str:
    """
    Main entry point for formatting the briefing.
    Transforms raw data into a polished, Jarvis-style voice report.
    """
    # 1. Process Missed Calls (Highest Priority)
    calls = missed_calls_data.get("calls", [])
    urgent_calls = []
    for call in calls:
        raw_from = call.get("from") or call.get("chat_id") or "Unknown"
        name = _clean_name(call.get("from_name") or raw_from)
        call_type = "video" if call.get("is_video") else "voice"
        urgent_calls.append(f"{name} ({call_type})")

    # 2. Process Unread Messages
    chats = unread_data.get("chats", [])
    direct_chats = []
    group_chats = []
    
    for chat in chats:
        chat_id = chat.get("chat_id", "")
        # Use provided name or fall back to ID
        raw_name = chat.get("chat_name") or chat_id
        chat_name = _clean_name(raw_name)
        
        # Filter Spam/Newsletters/Broadcasts
        if any(x in chat_id.lower() for x in ["newsletter", "broadcast", "status@broadcast"]):
            continue
            
        # Filter and count valid messages
        valid_messages = []
        for msg in chat.get("messages", []):
            text = (msg.get("text") or "").strip()
            
            # Ignore auto-replies (case-insensitive and stripped)
            if not text or text.lower() == AUTO_REPLY_TEXT.lower():
                continue
            
            # Convert [media] to a friendly description
            if text == "[media]":
                text = "a media file"
            
            valid_messages.append(text)
            
        if not valid_messages:
            continue
            
        unread_count = len(valid_messages)
        is_group = "@g.us" in chat_id
        
        chat_info = {
            "name": chat_name,
            "count": unread_count,
            "last_msg": valid_messages[-1]
        }
        
        if is_group:
            group_chats.append(chat_info)
        else:
            direct_chats.append(chat_info)

    # 3. Construct Spoken Briefing
    if not urgent_calls and not direct_chats and not group_chats:
        return "No new updates from WhatsApp, sir."

    greeting = _get_time_greeting()
    intro = f"{greeting}, sir. "
    briefing_parts = []
    
    # ── Part A: Missed Calls (Prioritize First) ──
    if urgent_calls:
        unique_callers = list(set(urgent_calls))
        if len(urgent_calls) == 1:
            briefing_parts.append(f"You have an urgent missed call from {urgent_calls[0]}.")
        elif len(unique_callers) == 1:
            # Multiple calls from the same person/type
            briefing_parts.append(f"You have {len(urgent_calls)} urgent missed calls from {unique_callers[0]}.")
        else:
            # Different people/types
            briefing_parts.append(f"You have {len(urgent_calls)} urgent missed calls.")

    # ── Part B: Direct Messages ──
    if direct_chats:
        if len(direct_chats) == 1:
            chat = direct_chats[0]
            msg_plural = "messages" if chat["count"] > 1 else "a message"
            briefing_parts.append(f"You have {msg_plural} from {chat['name']}.")
        elif len(direct_chats) == 2:
            briefing_parts.append(f"You have messages from {direct_chats[0]['name']} and {direct_chats[1]['name']}.")
        else:
            briefing_parts.append(f"You have unread messages from {len(direct_chats)} different contacts, including {direct_chats[0]['name']} and {direct_chats[1]['name']}.")

    # ── Part C: Group Chats (Merge Repetitive Summaries) ──
    if group_chats:
        if len(group_chats) == 1:
            group = group_chats[0]
            briefing_parts.append(f"There's also some activity in the {group['name']}.")
        else:
            # Merged summary for multiple groups
            briefing_parts.append(f"You also have updates from {len(group_chats)} group chats, mostly routine discussion.")

    # ── Part D: Actionable Ending ──
    full_briefing = intro + " ".join(briefing_parts)
    
    if urgent_calls:
        full_briefing += " The missed calls may need your attention first... it seems quite busy at your end."
    elif len(direct_chats) + len(group_chats) > 3:
        full_briefing += " It seems quite busy at your end, sir."

    return full_briefing

def _clean_name(name: str) -> str:
    """Strip JIDs and format identifiers into clean, human-readable names."""
    if not name:
        return "unsaved contact"

    # Check if it's a group
    is_group_jid = "@g.us" in name
    
    # Remove common JID suffixes
    clean = re.sub(r"@(lid|s\.whatsapp\.net|g\.us)", "", name)
    
    # If it's a group JID and we don't have a better name
    if is_group_jid and re.match(r"^\d", clean):
        return "one of your groups"
        
    # If it looks like a numerical ID (phone number or LID)
    if re.match(r"^\d{10,20}$", clean):
        return "unsaved contact"
        
    # Handle email-like identifiers or dot-separated names
    name_part = clean.split("@")[0]
    name_part = name_part.replace(".", " ").replace("_", " ")
    
    # Clean up any leftover punctuation and title case it
    name_part = re.sub(r"[^\w\s]", "", name_part)
    
    if not name_part.strip():
        return "unsaved contact"
        
    return name_part.strip().title()

def _get_time_greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"
