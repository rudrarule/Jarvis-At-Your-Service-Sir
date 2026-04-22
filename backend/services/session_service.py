"""
session_service.py — In-memory conversational session store
"""
from typing import List, Dict

# In-memory store: { session_id: [{"role": "role", "content": "message"}] }
chat_sessions: Dict[str, List[Dict[str, str]]] = {}

def get_session(session_id: str) -> List[Dict[str, str]]:
    """Retrieve existing session or return empty session."""
    return chat_sessions.get(session_id, [])

def append_message(session_id: str, role: str, content: str):
    """Append a message to the session."""
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []
    
    chat_sessions[session_id].append({"role": role, "content": content})

    # Limit to last 10 messages to avoid token overflow
    if len(chat_sessions[session_id]) > 10:
        chat_sessions[session_id] = chat_sessions[session_id][-10:]

def get_session_history(session_id: str, limit: int = 10) -> List[Dict[str, str]]:
    """Get the most recent history for a session."""
    session = get_session(session_id)
    return session[-limit:] if limit else session
