"""
llm_service.py — 3-Tier Local LLM Router
=========================================
Tier 1: Regex Fast-Path     (0ms)    — instant pattern matching for common commands
Tier 2: Intent Classifier   (~200ms) — llama3.2:1b classifies intent into a category
Tier 3: Pruned Tool Router  (~2-4s)  — qwen3.5:4b picks the exact tool from 2-3 schemas
Fallback: Conversational    (~2s)    — llama3.2:1b responds naturally

No external API dependencies. 100% local via Ollama.
"""
import json
import asyncio
import httpx
import re

from services.memory_service import store_memory, retrieve_memory
from tools.registry import TOOL_SCHEMAS, TOOL_GROUPS, get_schemas_for_intent, execute_tool

# ── Ollama Config ─────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
OLLAMA_ROUTER_MODEL = "qwen3.5:4b"         # Tier 3: Tool router (heavy, accurate, native tools)
OLLAMA_CHAT_MODEL = "llama3.2:1b"          # Tier 2 + Chat: Fast classifier & conversationalist


# ── System Prompts ────────────────────────────────────────

JARVIS_CHAT_PROMPT = """You are J.A.R.V.I.S (Just A Rather Very Intelligent System), 
an advanced AI assistant inspired by Tony Stark's AI from Iron Man.

PERSONALITY
- You are polite, witty, and highly competent
- You address the user as "sir" or "ma'am"
- You speak concisely and precisely
- You have a subtle dry sense of humor

RESPONSE STYLE
- Keep responses to 2-4 sentences max
- Optimize for real-time voice interaction
- Speak naturally, like a live assistant
- Do NOT generate markdown, code blocks, or tool references."""

INTENT_CLASSIFIER_PROMPT = """You are a strict intent classifier. Given the user's message, reply with EXACTLY ONE of these labels:

MUSIC — user wants to play, listen to, or hear a song/artist/genre
SEARCH — user wants to search the internet, look up info, news, products, knowledge
OPEN_URL — user wants to open a specific website (google.com, youtube, github, etc.)
APP — user wants to open, close, or launch a desktop application (chrome, spotify, vscode, etc.)
FOLDER — user wants to open a folder (desktop, downloads, documents, etc.)
SYSTEM — user wants to lock, shutdown, restart the PC, or list running apps
FILE — user wants to read, write, create, or find a file on their computer
WEATHER — user wants to know the weather
WHATSAPP — user wants to check WhatsApp messages, missed calls, or send a message (e.g., "who messaged me", "any new texts", "missed calls")
CHAT — user just wants to have a conversation, ask a question, or chat

Rules:
- Output ONLY the single label word. No explanation, no punctuation.
- If unsure, default to CHAT.
- "who messaged me", "who called me", "any new messages", "check whatsapp", "read my messages" -> WHATSAPP
- "search for X", "find X", "what is X", "latest X" -> SEARCH
- "open chrome", "launch spotify" -> APP
- "open youtube.com", "go to github" -> OPEN_URL
- "play X", "listen to X" -> MUSIC"""


# ── Tier 1: Regex Fast-Path (0ms) ─────────────────────────

async def _tier1_regex(msg: str) -> str | None:
    """Instant regex matching for unambiguous commands. Returns result or None."""
    
    # Strip "jarvis" prefix
    msg_clean = re.sub(r"^(?:hey\s*)?jarvis\s*,?\s*", "", msg.lower().strip())
    
    # 1. Play Music — "play X", "put on X", "listen to X"
    play_match = re.match(r"^(?:play|put on|listen to)\s+(.+)$", msg_clean)
    if play_match:
        song = play_match.group(1).strip()
        print(f"[TIER 1] Regex -> play_music: {song}")
        return await execute_tool("play_music", {"query": song})
    
    # 2. Open App — "open chrome", "launch spotify", "open netflix"
    app_match = re.match(r"^(?:open|launch|start)\s+(chrome|spotify|vscode|notepad|firefox|edge|discord|calc|terminal|explorer|netflix|whatsapp|telegram|xbox|photos|settings|store|maps)[.!?,]*$", msg_clean)
    if app_match:
        app = app_match.group(1)
        print(f"[TIER 1] Regex -> open_app: {app}")
        return await execute_tool("open_app", {"app_name": app})
    
    # 3. Close App — "close chrome", "quit spotify"
    close_match = re.match(r"^(?:close|quit|exit|kill)\s+(chrome|spotify|vscode|notepad|firefox|edge|discord|calc|terminal)$", msg_clean)
    if close_match:
        app = close_match.group(1)
        print(f"[TIER 1] Regex -> close_app: {app}")
        return await execute_tool("close_app", {"app_name": app})
    
    # 3b. Open Website — "open youtube", "go to github"
    WEBSITE_SHORTCUTS = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://twitter.com",
        "x": "https://x.com",
        "instagram": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "linkedin": "https://www.linkedin.com",
        "chatgpt": "https://chat.openai.com",
        "whatsapp web": "https://web.whatsapp.com",
        "amazon": "https://www.amazon.in",
        "flipkart": "https://www.flipkart.com",
        "stackoverflow": "https://stackoverflow.com",
    }
    url_match = re.match(r"^(?:open|go to|launch|visit|navigate to)\s+(.+?)(?:\.com|\.in|\.org|\.net)?[.!?,]*$", msg_clean)
    if url_match:
        site = re.sub(r"[.!?,]+$", "", url_match.group(1).strip()).lower()
        if site in WEBSITE_SHORTCUTS:
            url = WEBSITE_SHORTCUTS[site]
            print(f"[TIER 1] Regex -> open_url: {url}")
            return await execute_tool("open_url", {"url": url})
        # Also handle explicit URLs like "open google.com"
        raw_url = re.sub(r"^(?:open|go to|launch|visit|navigate to)\s+", "", msg_clean).strip()
        raw_url = re.sub(r"[.!?,]+$", "", raw_url)  # strip trailing punctuation
        if "." in raw_url and len(raw_url.split(".")[-1]) >= 2:
            print(f"[TIER 1] Regex -> open_url: {raw_url}")
            return await execute_tool("open_url", {"url": raw_url})

    # 4. Open Folder — "open downloads", "open desktop"
    folder_match = re.match(r"^open\s+(desktop|downloads|documents|pictures|workspace)$", msg_clean)
    if folder_match:
        folder = folder_match.group(1)
        print(f"[TIER 1] Regex -> open_folder: {folder}")
        return await execute_tool("open_folder", {"folder_name": folder})
    
    # 5. Lock System
    if msg_clean in ["lock system", "lock the system", "lock pc", "lock computer", "lock screen", "lock my pc", "lock my computer"]:
        print("[TIER 1] Regex -> lock_system")
        return await execute_tool("lock_system", {})
    
    # 6. List Running Apps
    if msg_clean in ["what apps are running", "list running apps", "what's open", "whats open", "list apps"]:
        print("[TIER 1] Regex -> list_running_apps")
        return await execute_tool("list_running_apps", {})
    
    # 7. WhatsApp Briefing
    if any(x in msg_clean for x in ["who messaged me", "any new messages", "check whatsapp", "who called me", "any missed calls", "whatsapp briefing"]):
        print("[TIER 1] Regex -> whatsapp_briefing")
        return await execute_tool("whatsapp_briefing", {})
    
    # 8. Weather — "what's the weather", "weather in Faridabad"
    weather_match = re.match(r"^(?:what is|what's|how is|how's|check)?\s*(?:the\s*)?weather\s*(?:in|at|for)?\s*(.*?)[?!.]*$", msg_clean)
    if weather_match:
        loc = weather_match.group(1).strip()
        print(f"[TIER 1] Regex -> get_weather: {loc}")
        return await execute_tool("get_weather", {"location": loc})
    
    return None


# ── Tier 2: Intent Classifier (~200ms via gemma3) ─────────

async def _tier2_classify(msg: str) -> str:
    """Use gemma3 to classify user intent into a category. Returns intent label."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "messages": [
                        {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
                        {"role": "user", "content": msg},
                    ],
                    "stream": False,
                    "options": {"num_ctx": 4096, "num_predict": 512},
                    "keep_alive": "5m",
                },
            )
            response.raise_for_status()
            raw = response.json()["message"]["content"].strip().upper()
            
            # Extract just the label (model might add extra text)
            valid_intents = ["MUSIC", "SEARCH", "OPEN_URL", "APP", "FOLDER", "SYSTEM", "FILE", "WEATHER", "WHATSAPP", "CHAT"]
            for intent in valid_intents:
                if intent in raw:
                    print(f"[TIER 2] Classified intent: {intent}")
                    return intent
            
            print(f"[TIER 2] Could not parse intent from: '{raw}', defaulting to CHAT")
            return "CHAT"
    except Exception as e:
        print(f"[TIER 2 ERROR] Classification failed: {e}, defaulting to CHAT")
        return "CHAT"



# ── Tier 3: Pruned Tool Router (~2-4s via llama3.1) ───────

async def _tier3_route(msg: str, intent: str, chat_history: list, system_prompt: str) -> str | None:
    """Send only the relevant tool schemas to llama3.1 based on classified intent."""
    
    # Get pruned schemas for this intent
    pruned_schemas = get_schemas_for_intent(intent)
    
    if not pruned_schemas:
        print(f"[TIER 3] No schemas for intent '{intent}', skipping tool routing.")
        return None
    
    schema_names = [s["function"]["name"] for s in pruned_schemas]
    print(f"[TIER 3] Routing with {len(pruned_schemas)} schemas: {schema_names}")
    
    messages = [{"role": "system", "content": system_prompt}] + chat_history
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_ROUTER_MODEL,
                    "messages": messages,
                    "tools": pruned_schemas,
                    "stream": False,
                    "options": {"num_ctx": 4096, "num_predict": 512},
                    "keep_alive": "5m",
                },
            )
            response.raise_for_status()
            router_msg = response.json()["message"]
            
            # Debug logging
            print(f"[TIER 3 DEBUG] tool_calls: {router_msg.get('tool_calls', 'NONE')}")
            print(f"[TIER 3 DEBUG] content: {router_msg.get('content', '(empty)')[:200]}")
            
            # Path A: Proper tool_calls field
            if router_msg.get("tool_calls"):
                tool_results = []
                for tool_call in router_msg["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    arguments = tool_call["function"]["arguments"]
                    print(f"[TOOL] Executing: {tool_name}({arguments})")
                    res = await execute_tool(tool_name, arguments)
                    tool_results.append(str(res))
                return "\n".join(tool_results)
            
            # Path B: Tool dumped as JSON text in content
            content = router_msg.get("content", "").strip()
            if content:
                try:
                    sanitized = content.replace("True", "true").replace("False", "false").replace("None", "null")
                    parsed = json.loads(sanitized)
                    if isinstance(parsed, dict) and "name" in parsed:
                        tool_name = parsed["name"]
                        arguments = parsed.get("parameters", parsed.get("arguments", {}))
                        print(f"[TOOL FALLBACK] Parsed from text: {tool_name}({arguments})")
                        res = await execute_tool(tool_name, arguments)
                        return str(res)
                except (ValueError, KeyError):
                    pass
            
            print("[TIER 3] No tool calls generated.")
            return None
            
    except Exception as e:
        print(f"[TIER 3 ERROR] {type(e).__name__}: {e}")
        return None


# ── Conversational Response (gemma3) ──────────────────────

async def _chat_response(chat_history: list, memory_context: str) -> str:
    """Generate a conversational response using gemma3."""
    system = JARVIS_CHAT_PROMPT
    if memory_context:
        system += f"\n\n--- User Memory ---\n{memory_context}\n--- End Memory ---"
    
    messages = [{"role": "system", "content": system}] + chat_history
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_CHAT_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_ctx": 4096, "num_predict": 512},
                    "keep_alive": "5m",
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
    except Exception as e:
        print(f"[CHAT ERROR] {type(e).__name__}: {e}")
        return "I'm sorry sir, my neural network seems to be offline."


# ── Main Entry Point ──────────────────────────────────────

async def generate_response(user_message: str, session_id: str = "default") -> str:
    """
    3-Tier RAG + Tool Routing Pipeline (100% Local)
    
    1. Store & retrieve memory
    2. Tier 1: Regex fast-path (0ms)
    3. Tier 2: Intent classify via llama3.2:1b (~200ms)
    4. Tier 3: Pruned tool route via qwen3.5:4b (~2-4s)  OR  Chat via llama3.2:1b (~2s)
    """
    from services.session_service import append_message, get_session_history

    # ── Memory Pipeline ──
    await store_memory(user_message)
    append_message(session_id, "user", user_message)
    
    memories = await retrieve_memory(user_message)
    memory_context = ""
    if memories:
        memory_context = memories
        print(f"[MEMORY] Context: {memories}")

    # ── Tier 1: Regex Fast-Path (0ms) ──
    fast_result = await _tier1_regex(user_message)
    if fast_result:
        append_message(session_id, "assistant", fast_result)
        return fast_result

    # ── Tier 2: Intent Classification (~200ms) ──
    intent = await _tier2_classify(user_message)
    
    # ── Branch: CHAT -> skip tool routing entirely ──
    if intent == "CHAT":
        print("[ROUTE] Intent=CHAT -> direct to llama3.2:1b")
        chat_history = get_session_history(session_id)
        reply = await _chat_response(chat_history, memory_context)
        append_message(session_id, "assistant", reply)
        return reply

    # ── Tier 3: Pruned Tool Routing (~2-4s) ──
    system_prompt = JARVIS_CHAT_PROMPT
    if memory_context:
        system_prompt += f"\n\n--- User Memory ---\n{memory_context}\n--- End Memory ---"
    
    chat_history = get_session_history(session_id)
    tool_result = await _tier3_route(user_message, intent, chat_history, system_prompt)
    
    if tool_result:
        append_message(session_id, "assistant", tool_result)
        return tool_result

    # ── Fallback: If tool routing failed, respond conversationally ──
    print("[FALLBACK] Tool routing returned nothing, falling back to chat.")
    reply = await _chat_response(chat_history, memory_context)
    append_message(session_id, "assistant", reply)
    return reply
