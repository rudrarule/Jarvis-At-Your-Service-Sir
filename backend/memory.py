"""
memory.py — J.A.R.V.I.S In-Memory User Memory System
Extracts and stores personal facts from user messages,
then provides them as context for LLM calls.
"""
import re

# ── In-Memory Storage ──────────────────────────────────────
_user_memory: dict[str, str] = {}

# ── Pattern Definitions ───────────────────────────────────
# Each tuple: (regex pattern, memory key, group index for value)
_PATTERNS = [
    # Name detection
    (r"my name is (\w+)",                    "name"),
    (r"i(?:'| a)m (\w+)",                    "name"),
    (r"call me (\w+)",                       "name"),

    # Preferences
    (r"i (?:really )?like (.+?)(?:\.|,|!|$)", "likes"),
    (r"i love (.+?)(?:\.|,|!|$)",            "loves"),
    (r"i prefer (.+?)(?:\.|,|!|$)",          "prefers"),
    (r"i hate (.+?)(?:\.|,|!|$)",            "hates"),

    # Personal info
    (r"i(?:'| a)m (\d{1,3}) years old",      "age"),
    (r"my age is (\d{1,3})",                 "age"),
    (r"i live in (.+?)(?:\.|,|!|$)",         "location"),
    (r"i(?:'| a)m from (.+?)(?:\.|,|!|$)",   "location"),
    (r"i work (?:at|for|in) (.+?)(?:\.|,|!|$)", "occupation"),
    (r"i(?:'| a)m a (.+?)(?:\.|,|!|$)",      "role"),
    (r"my favorite (.+?) is (.+?)(?:\.|,|!|$)", "_favorite"),  # special handler
]


def extract_memory(message: str) -> dict[str, str]:
    """
    Scan a user message for personal facts and store them.
    Returns a dict of newly extracted facts (for logging/debug).
    """
    text = message.strip()
    extracted: dict[str, str] = {}

    for pattern, key in _PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        if key == "_favorite":
            # "my favorite language is Python" → favorite_language: Python
            category = match.group(1).strip().lower().replace(" ", "_")
            value = match.group(2).strip()
            mem_key = f"favorite_{category}"
            _user_memory[mem_key] = value
            extracted[mem_key] = value
        else:
            value = match.group(1).strip()
            _user_memory[key] = value
            extracted[key] = value

    if extracted:
        print(f"🧠 Memory updated: {extracted}")

    return extracted


def get_memory_context() -> str:
    """
    Return all stored user facts as a formatted context string
    that can be prepended to the LLM system prompt.
    """
    if not _user_memory:
        return ""

    # Build human-readable lines
    _LABELS = {
        "name":       "User's name is",
        "age":        "User is {v} years old",
        "location":   "User lives in",
        "occupation": "User works at/in",
        "role":       "User is a",
        "likes":      "User likes",
        "loves":      "User loves",
        "prefers":    "User prefers",
        "hates":      "User dislikes",
    }

    lines = []
    for key, value in _user_memory.items():
        if key in _LABELS:
            template = _LABELS[key]
            if "{v}" in template:
                lines.append(f"{template.format(v=value)}.")
            else:
                lines.append(f"{template} {value}.")
        elif key.startswith("favorite_"):
            category = key.replace("favorite_", "").replace("_", " ")
            lines.append(f"User's favorite {category} is {value}.")
        else:
            lines.append(f"User's {key}: {value}.")

    return "\n".join(lines)


def get_raw_memory() -> dict[str, str]:
    """Return a copy of the raw memory dict (for API/debug)."""
    return dict(_user_memory)


def clear_memory() -> None:
    """Clear all stored memory."""
    _user_memory.clear()
    print("🧠 Memory cleared.")
