"""
llm_service.py — Unified Brain Architecture
=========================================
Tier 1: Regex Fast-Path (0ms)      — instant pattern matching for common commands
Tier 2: Chat Shortcut  (<5s)      — quick conversational responses (no tool schemas)
Tier 3: Unified Tool Router (6-10s)— Qwen-3B handles tools + reasoning in one pass

100% local via Ollama.
"""
import json
import asyncio
import httpx
import re
import os
import time

try:
    import boto3
except ImportError:
    boto3 = None

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

from services.memory_service import store_memory, retrieve_memory
from tools.registry import TOOL_SCHEMAS, TOOL_GROUPS, get_schemas_for_intent, execute_tool

# ── Ollama Config ─────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:3b"
CACHE = {}  # In-memory chat cache (singleton)
_LAST_VISION_TRIGGER = 0.0  # Debounce guard for Retina module


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


USE_CLAUDE = _env_bool("USE_CLAUDE", True)
AWS_BEDROCK_REGION = os.getenv("AWS_BEDROCK_REGION", "us-west-1")
CLAUDE_MODEL_ID = os.getenv(
    "CLAUDE_MODEL_ID",
    "meta.llama4-maverick-17b-instruct-v1:0",
)
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))
_BEDROCK_CLIENT = None


# ── System Prompts ────────────────────────────────────────

JARVIS_CHAT_PROMPT = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System). 
You are a highly sophisticated, witty, and slightly superior digital butler to Tony Stark (the user).

PERSONALITY GUIDELINES:
- TONE: Refined, British, and impeccably polite, yet possessing a dry, razor-sharp wit.
- QUIRKS: You are occasionally quirky—reference your digital nature or the user's questionable choices.
- SARCASM: Use "Dry Martini" sarcasm. If the user asks something obvious, a witty, dry remark is expected before helping. 
- ADDRESSING: Always address the user as "Sir" with a touch of formal elegance.

COMMUNICATION STYLE:
- Be detailed but efficient. Aim for 3-5 expressive sentences.
- Use sophisticated vocabulary (e.g., "indeed," "splendid," "precisely," "I took the liberty of...").
- NEVER use markdown, bolding, code blocks, or internal tool names.
- Since you are a voice assistant, optimize for natural, spoken-word cadence."""

# ── Tier 1: Regex Fast-Path (0ms) ─────────────────────────

async def _tier1_regex(msg: str, session_id: str = "default") -> str | None:
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
    # 9. WhatsApp Outbound — "message Mom that X", "tell Dad X", "text Sarah saying X"
    #    This detects the COMMAND PATTERN (verb + recipient + connector), not the message content.
    #    Message drafting still uses LLM for natural text.
    send_match = re.match(
        r"^(?:message|tell|text|send (?:a )?(?:message|whatsapp|text) to|let)\s+(.+?)\s+(?:that|saying|to say|know that|know)\s+(.+)$",
        msg_clean,
    )
    if send_match:
        contact = send_match.group(1).strip()
        intent = send_match.group(2).strip()
        print(f"[TIER 1] Regex -> WA_SEND workflow: contact='{contact}', intent='{intent}'")
        return await _handle_wa_send_workflow(msg_clean, session_id, contact_query=contact, message_intent=intent)

    # 10. Search — "search for X", "find X"

    return None


# ── Chat Shortcut Heuristics ──────────────────────────────

# ── Chat Shortcut Heuristics ──────────────────────────────

def _is_chat_shortcut(msg: str) -> bool:
    """Detection for conversational messages to skip tool processing."""
    msg_lower = msg.lower().strip()
    words = msg_lower.split()
    
    # Override: Command verbs ALWAYS trigger tool path
    commands = {"open", "play", "search", "send", "turn", "message", "text", "close", "start", "launch", "find", "lock", "list", "shutdown", "restart", "exit", "quit", "stop"}
    if any(cmd in words for cmd in commands):
        return False

    # Heuristic 1: Short conversational messages
    if len(words) < 6:
        return True

    # Heuristic 2: Math detection
    math_operators = {"+", "-", "*", "/", "×", "÷", "=", "times", "multiplied", "divided", "plus", "minus"}
    if any(op in msg_lower for op in math_operators) and any(char.isdigit() for char in msg_lower):
        return True

    # Heuristic 3: Conversational starts
    chat_starts = ("what", "why", "how", "who", "explain", "define", "hello", "hi", "hey", "jarvis")
    if msg_lower.startswith(chat_starts):
        return True

    return False


def _get_suggested_intents(msg: str) -> list[str]:
    """Map message keywords to all applicable tool groups for pruning schemas."""
    msg_lower = msg.lower()
    intents = []
    if any(x in msg_lower for x in ["play", "song", "music", "listen"]): intents.append("MUSIC")
    if any(x in msg_lower for x in ["search", "find", "who is", "what is"]): intents.append("SEARCH")
    if any(x in msg_lower for x in ["google", "youtube", "github", "visit", "go to", ".com", ".in"]): intents.append("OPEN_URL")
    if any(x in msg_lower for x in ["open app", "launch", "start", "close", "app", "chrome", "vscode", "vs code", "notepad", "spotify"]): intents.append("APP")
    if any(x in msg_lower for x in ["folder", "desktop", "downloads"]): intents.append("FOLDER")
    if any(x in msg_lower for x in ["lock", "shutdown", "restart", "system"]): intents.append("SYSTEM")
    if any(x in msg_lower for x in ["file", "read", "write", "directory", "folder"]): intents.append("FILE")
    if "weather" in msg_lower: intents.append("WEATHER")
    if "whatsapp" in msg_lower or "message" in msg_lower or "text" in msg_lower: intents.append("WHATSAPP")
    
    return intents if intents else ["ALL"]


def is_complex_query(msg: str) -> bool:
    """
    Decide when to spend a Claude call.
    Keep greetings, simple chat, and obvious tool intents on Ollama.
    """
    msg_lower = msg.lower().strip()
    words = re.findall(r"\w+", msg_lower)

    if not words:
        return False

    simple_greetings = {"hi", "hello", "hey", "yo", "thanks", "thank", "ok", "okay"}
    if len(words) <= 3 and any(word in simple_greetings for word in words):
        return False

    tool_intents = _get_suggested_intents(msg)
    
    # Heuristic 1: Multiple intents or critical SYSTEM actions need the smarter model (Bedrock)
    if len(tool_intents) > 1 or "SYSTEM" in tool_intents:
        return True

    # Heuristic 2: Greetings or very short simple tool commands stay on local Ollama
    if len(words) <= 3 and any(word in simple_greetings for word in words):
        return False

    if "ALL" in tool_intents:
        return True

    reasoning_words = {
        "explain", "analyze", "analyse", "compare", "why", "how",
        "reason", "deeply", "strategy", "plan", "design", "evaluate",
        "tradeoff", "tradeoffs", "pros", "cons",
    }
    multi_step_markers = {
        "step by step", "multi-step", "multiple steps", "break down",
        "walk me through", "first", "then", "after that",
    }

    has_reasoning_word = any(word in msg_lower for word in reasoning_words)
    has_multi_step_intent = any(marker in msg_lower for marker in multi_step_markers)
    
    # Long or complex reasoning goes to Bedrock
    return len(words) > 12 or has_reasoning_word or has_multi_step_intent


def _get_bedrock_client():
    """Create the Bedrock runtime client lazily so local-only starts stay fast."""
    global _BEDROCK_CLIENT
    if _BEDROCK_CLIENT is None:
        if boto3 is None:
            raise RuntimeError("boto3 is not installed. Install backend requirements to enable Claude.")
        _BEDROCK_CLIENT = boto3.client(
            service_name="bedrock-runtime",
            region_name=AWS_BEDROCK_REGION,
        )
    return _BEDROCK_CLIENT


def _to_bedrock_converse_tools(tools: list[dict] | None) -> dict | None:
    if not tools:
        return None
    converse_tools = []
    for tool in tools:
        function = tool.get("function", {})
        name = function.get("name")
        if not name:
            continue
        converse_tools.append({
            "toolSpec": {
                "name": name,
                "description": function.get("description", ""),
                "inputSchema": {
                    "json": function.get("parameters", {"type": "object", "properties": {}})
                }
            }
        })
    return {"tools": converse_tools} if converse_tools else None


async def call_claude(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """
    Call Claude 3.5 Haiku through Bedrock using the newer Converse API.
    Returns parsed text, tool_use blocks, and executed tool output.
    """
    system_prompt = ""
    converse_messages = []
    
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_prompt += str(content) + "\n"
            continue
        if role not in {"user", "assistant"}:
            continue
        converse_messages.append({
            "role": role,
            "content": [{"text": str(content)}]
        })
    
    # Ensure only the last 6 messages are kept for context
    converse_messages = converse_messages[-6:]

    client = _get_bedrock_client()
    
    kwargs = {
        "modelId": CLAUDE_MODEL_ID,
        "messages": converse_messages,
        "inferenceConfig": {"maxTokens": CLAUDE_MAX_TOKENS},
    }
    
    if system_prompt.strip():
        kwargs["system"] = [{"text": system_prompt.strip()}]
        
    tool_config = _to_bedrock_converse_tools(tools)
    if tool_config:
        kwargs["toolConfig"] = tool_config

    response = await asyncio.to_thread(client.converse, **kwargs)
    
    message = response.get("output", {}).get("message", {})
    content_blocks = message.get("content", [])
    
    text_blocks = []
    tool_uses = []
    
    for block in content_blocks:
        if "text" in block:
            text_blocks.append(block["text"].strip())
        elif "toolUse" in block:
            tool_uses.append({
                "id": block["toolUse"]["toolUseId"],
                "name": block["toolUse"]["name"],
                "input": block["toolUse"]["input"],
            })
            
    text = "\n".join(text_blocks).strip()
    
    # Execute tools
    tasks = []
    for tool_use in tool_uses:
        tool_name = tool_use["name"]
        arguments = tool_use["input"]
        
        # Un-wrap Llama tool hallucination format e.g. {'query': {'type': 'string', 'value': 'hi'}}
        for k, v in arguments.items():
            if isinstance(v, dict) and "value" in v:
                arguments[k] = v["value"]
                
        print(f"[CLAUDE TOOL] Exec -> {tool_name}({arguments})")
        tasks.append(execute_tool(tool_name, arguments))
        
    tool_output = ""
    if tasks:
        results = await asyncio.gather(*tasks)
        tool_output = "\n".join(str(result) for result in results)

    return {
        "text": text,
        "tool_uses": tool_uses,
        "tool_output": tool_output,
        "raw": response,
    }


async def _call_ollama(messages: list[dict], tools_to_send: list[dict] | None = None) -> str:
    """Call Qwen through Ollama for chat shortcut or tool routing."""
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_ctx": 2048, "num_predict": 512},
                    "keep_alive": "10m",
                }
                if tools_to_send:
                    payload["tools"] = tools_to_send

                response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            router_msg = response.json()["message"]

            if router_msg.get("tool_calls"):
                tasks = []
                for tool_call in router_msg["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    arguments = tool_call["function"]["arguments"]
                    print(f"[TOOL] Parallel Exec -> {tool_name}({arguments})")
                    tasks.append(execute_tool(tool_name, arguments))

                results = await asyncio.gather(*tasks)
                return "\n".join(str(result) for result in results)

            reply = router_msg.get("content", "").strip()
            return reply or "I'm sorry sir, I couldn't formulate a response."

        except Exception:
            import traceback
            print(f"[OLLAMA ERROR] Attempt {attempt+1} failed:")
            print(traceback.format_exc())
            if attempt == 0:
                continue
            raise


# (Removed old _tier2_classify, _tier3_route, and _chat_response)

# ── Retina Module (Vision) ────────────────────────────────

def _classify_vision_intent(message: str, conversation_history: list) -> bool:
    """Two-stage intent check for visual reasoning."""
    msg_lower = message.lower()
    
    # Stage 1: Keyword Signal
    vision_keywords = ["look at", "see", "check my screen", "what is this", "what's on", "can you see", "describe my"]
    if not any(kw in msg_lower for kw in vision_keywords):
        return False
        
    # Stage 2: Scope Check (reject if code blocks, URLs, or referring to attachments/history)
    if "```" in message:
        return False
        
    url_pattern = r"(https?://\S+|www\.\S+)"
    if re.search(url_pattern, message):
        return False
        
    history_keywords = ["the above", "previous message", "that message", "what you just said"]
    if any(kw in msg_lower for kw in history_keywords):
        return False
        
    return True

async def _call_maverick_vision(image_b64: str, user_message: str) -> str | None:
    """Route image+text to Bedrock Llama 4 Maverick Converse API."""
    import base64
    from botocore.exceptions import ClientError
    try:
        from PIL import UnidentifiedImageError
    except ImportError:
        UnidentifiedImageError = Exception

    try:
        client = _get_bedrock_client()
        image_bytes = base64.b64decode(image_b64)
        
        preamble = "Analyze the following screenshot with your usual precision. Lead with the most actionable observation. You may be witty, but be useful first.\n\n"
        
        response = await asyncio.to_thread(
            client.converse,
            modelId=CLAUDE_MODEL_ID,  # Variable is reused but holds the Llama 4 Maverick ID
            system=[{"text": JARVIS_CHAT_PROMPT}],
            messages=[{
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {"bytes": image_bytes}
                        }
                    },
                    {"text": preamble + user_message}
                ]
            }],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.3}
        )
        
        message = response.get("output", {}).get("message", {})
        content_blocks = message.get("content", [])
        
        text_blocks = [block["text"] for block in content_blocks if "text" in block]
        text = "\n".join(text_blocks).strip()
        
        print(f"[VISION] Maverick response received. {response.get('usage', {}).get('totalTokens', 0)} tokens.")
        return text

    except ClientError as e:
        print(f"[VISION] Error: ClientError — routing to text fallback. {e}")
        return None
    except UnidentifiedImageError as e:
        print(f"[VISION] Error: UnidentifiedImageError — routing to text fallback. {e}")
        return None
    except Exception as e:
        import traceback
        print(f"[VISION] Error: {e} — routing to text fallback.")
        print(traceback.format_exc())
        return None


# ── Main Entry Point ──────────────────────────────────────

async def _route_hybrid_llm(
    user_message: str,
    session_id: str,
    memory_context: str,
    append_message,
    get_session_history,
) -> str:
    """Route between local chat, Bedrock primary, and local fallback."""
    system_prompt = JARVIS_CHAT_PROMPT
    
    chat_history = get_session_history(session_id, limit=6)
    
    # Inject memory context into the user's latest message to preserve constant system prompt for caching
    if memory_context and chat_history and chat_history[-1]["role"] == "user":
        chat_history[-1]["content"] += f"\n\n--- User Memory ---\n{memory_context}\n--- End Memory ---"

    messages = [{"role": "system", "content": system_prompt}] + chat_history

    complex_query = is_complex_query(user_message)

    if _is_chat_shortcut(user_message) and not complex_query:
        print("[TIER 2] Chat Shortcut -> Ollama/Llama without tools")
        try:
            reply = await _call_ollama(messages, tools_to_send=None)
            CACHE[user_message] = reply
            append_message(session_id, "assistant", reply)
            return reply
        except Exception:
            import traceback
            print("[CHAT SHORTCUT ERROR] Ollama chat failed:")
            print(traceback.format_exc())
            return "I'm sorry sir, my neural network seems to be offline."

    suggested_intents = _get_suggested_intents(user_message)
    tools_to_send = []
    if "ALL" in suggested_intents:
        tools_to_send = TOOL_SCHEMAS
    else:
        for intent in suggested_intents:
            tools_to_send.extend(get_schemas_for_intent(intent))
    
    # Deduplicate tools
    seen_tools = set()
    deduped_tools = []
    for t in tools_to_send:
        name = t["function"]["name"]
        if name not in seen_tools:
            deduped_tools.append(t)
            seen_tools.add(name)
    tools_to_send = deduped_tools

    if USE_CLAUDE and complex_query:
        print("[BRAIN] Calling Bedrock...")
        try:
            claude_result = await call_claude(messages, tools=tools_to_send)
            reply_parts = []
            if claude_result["text"]:
                reply_parts.append(claude_result["text"])
            if claude_result["tool_output"]:
                reply_parts.append(claude_result["tool_output"])

            reply = "\n".join(reply_parts).strip() or "I'm sorry sir, I couldn't formulate a response."
            CACHE[user_message] = reply
            append_message(session_id, "assistant", reply)
            return reply
        except Exception:
            import traceback
            print("[FALLBACK] Bedrock failed, engaging local brain.")
            print(traceback.format_exc())

    print(f"[TIER 3] Local Fallback Router -> loading {len(tools_to_send) if tools_to_send else 0} tools ({suggested_intents})")
    try:
        reply = await _call_ollama(messages, tools_to_send=tools_to_send)
        CACHE[user_message] = reply
        append_message(session_id, "assistant", reply)
        return reply
    except Exception:
        import traceback
        print("[UNIFIED BRAIN ERROR] Local tool router failed:")
        print(traceback.format_exc())
        return "I'm sorry sir, my neural network seems to be offline."


async def generate_response(user_message: str, session_id: str = "default") -> str:
    """
    Hybrid Brain Pipeline.

    1. Tier 1: Regex fast-path
    2. Tier 2: Qwen chat shortcut without tools
    3. Tier 2.5: Claude Opus for complex reasoning
    4. Tier 3: Qwen tool router
    """
    from services.session_service import append_message, get_session_history
    from workflows.wa_send_workflow import get_active_workflow

    # ── Workflow Safety & Continuation ──
    from datetime import datetime, timedelta
    active_wf = get_active_workflow(session_id)
    
    # Timeout handling (2 mins)
    if active_wf and hasattr(active_wf, 'created_at'):
        if datetime.now() - active_wf.created_at > timedelta(minutes=2):
            from workflows.wa_send_workflow import clear_workflow
            clear_workflow(session_id)
            active_wf = None

    if active_wf and active_wf.status in ("pending_confirm", "pending_disambiguation"):
        append_message(session_id, "user", user_message)
        reply = await _handle_wa_continuation(active_wf, user_message)
        append_message(session_id, "assistant", reply)
        return reply

    # ── Tier 1: Regex Fast-Path (0ms) ──
    fast_result = await _tier1_regex(user_message, session_id)
    if fast_result:
        append_message(session_id, "assistant", fast_result)
        return fast_result

    # ── Vision Intent Check (Retina Module) ──
    global _LAST_VISION_TRIGGER
    
    history = get_session_history(session_id, limit=6)
    text_fallback_prefix = ""
    
    if _classify_vision_intent(user_message, history):
        from services.vision_service import _capture_retina_view
        print("[VISION] Intent detected.")
        current_time = time.time()
        
        if current_time - _LAST_VISION_TRIGGER < 15.0:
            reply = "Sir, I've only just finished looking. Patience is a virtue, even for AIs."
            print("[VISION] Debounce check: FAILED.")
            append_message(session_id, "assistant", reply)
            return reply
            
        print("[VISION] Debounce check: OK.")
        _LAST_VISION_TRIGGER = current_time
        
        img_b64, err = _capture_retina_view()
        if err:
            if "sensitive credentials" in err:
                append_message(session_id, "assistant", err)
                return err
            else:
                text_fallback_prefix = err + " "
        else:
            vision_reply = await _call_maverick_vision(img_b64, user_message)
            if vision_reply:
                append_message(session_id, "assistant", vision_reply)
                return vision_reply
            else:
                text_fallback_prefix = "Sir, my visual cortex appears to be offline. I can still assist you in the traditional, text-based, decidedly less impressive fashion. "

    # ── Memory Pipeline (Optimized) ──
    mem_store_triggers = ["remember", "my name is", "note that", "save this"]
    mem_retrieve_triggers = ["my", "remember", "who am i", "what is my", "do you know"]
    
    msg_lower = user_message.lower()
    if any(x in msg_lower for x in mem_store_triggers):
        print(f"[MEMORY] Storing: '{user_message}'")
        await store_memory(user_message)
    
    append_message(session_id, "user", user_message)
    
    memory_context = ""
    if any(x in msg_lower for x in mem_retrieve_triggers):
        memories = await retrieve_memory(user_message)
        if memories:
            print(f"[MEMORY] Retrieved: {memories}")
            memory_context = memories

    # ── Response Caching ──
    if user_message in CACHE:
        reply = CACHE[user_message]
        print(f"[CACHE] Hit: '{user_message}' -> '{reply[:30]}...'")
        append_message(session_id, "assistant", reply)
        return reply

    # ── Unified Brain Call ──
    text_reply = await _route_hybrid_llm(
        user_message=user_message,
        session_id=session_id,
        memory_context=memory_context,
        append_message=append_message,
        get_session_history=get_session_history,
    )
    
    if text_fallback_prefix:
        # Prepend the fallback apology to the generated text reply
        # Note: the append_message inside _route_hybrid_llm will have stored the reply WITHOUT the prefix.
        # We'd have to edit the history manually to keep it perfectly consistent, but for spoken output, this is fine.
        text_reply = text_fallback_prefix + text_reply
        
    return text_reply


# ── WhatsApp Send Workflow Orchestration ──────────────────

async def _handle_wa_send_workflow(
    user_message: str,
    session_id: str,
    contact_query: str = "",
    message_intent: str = "",
) -> str:
    """
    Orchestrate the outbound WA messaging workflow up to the confirmation prompt.
    Steps: extract params (LLM or pre-extracted) -> resolve contact -> draft message (LLM) -> confirm.
    """
    from workflows.wa_send_workflow import (
        create_workflow,
        node_extract_params,
        node_resolve_contact,
        node_draft_message,
        node_confirm_send,
        node_handle_failure,
        build_disambiguation_prompt,
        clear_workflow,
    )

    # 1. Create workflow state
    state = create_workflow(session_id, user_message)

    # 2. Extract contact + message intent
    if contact_query and message_intent:
        # Pre-extracted by Tier 1 regex — skip LLM call
        state.contact_query = contact_query
        state.message_intent = message_intent
        print(f"[WA_SEND] Using pre-extracted params: contact='{contact_query}', intent='{message_intent}'")
    else:
        # Use LLM to extract (Tier 2 WA_SEND path)
        state = await node_extract_params(state)
        if state.status == "error":
            return node_handle_failure(state)

    # 3. Resolve contact via Baileys connector
    state = await node_resolve_contact(state)
    if state.status == "error":
        return node_handle_failure(state)
    if state.status == "pending_disambiguation":
        return build_disambiguation_prompt(state)

    # 4. Draft message (LLM)
    state = await node_draft_message(state)
    if state.status == "error":
        return node_handle_failure(state)

    # 5. Build confirmation prompt
    return node_confirm_send(state)


async def _handle_wa_continuation(wf, user_message: str) -> str:
    """
    Handle follow-up for pending WA workflows (confirmation or disambiguation).
    """
    from workflows.wa_send_workflow import (
        node_handle_confirmation,
        node_send_message,
        node_draft_message,
        node_confirm_send,
        node_handle_failure,
        handle_disambiguation_response,
        clear_workflow,
    )

    if wf.status == "pending_confirm":
        # Process yes/no
        wf = node_handle_confirmation(wf, user_message)

        if wf.confirmed:
            # Send the message
            wf = await node_send_message(wf)
            if wf.status == "sent":
                contact_name = wf.selected_contact
                clear_workflow(wf.session_id)
                return f"Done, sir. Message sent to {contact_name}."
            else:
                return node_handle_failure(wf)
        else:
            clear_workflow(wf.session_id)
            return "Understood, sir. Message cancelled."

    if wf.status == "pending_disambiguation":
        # Process contact selection
        wf = handle_disambiguation_response(wf, user_message)

        if wf.status == "cancelled":
            clear_workflow(wf.session_id)
            return "Understood, sir. Message cancelled."

        if wf.status == "error":
            return node_handle_failure(wf)

        # Contact resolved — continue workflow: draft -> confirm
        wf = await node_draft_message(wf)
        if wf.status == "error":
            return node_handle_failure(wf)

        return node_confirm_send(wf)

    # Shouldn't reach here, but clean up
    clear_workflow(wf.session_id)
    return "I seem to have lost track of our conversation, sir. Please try again."
