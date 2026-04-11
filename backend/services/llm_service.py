"""
llm_service.py — LLM Integration with RAG Memory + Native Tool Calling
Handles the LLM fallback chain (Ollama → Gemini → OpenAI)
with vector-retrieved memory injected into the system prompt
and native function calling for tool execution.
"""
import os
import json
import asyncio
import httpx
import re
from dotenv import load_dotenv
import google.generativeai as genai
from openai import AsyncOpenAI

from services.memory_service import store_memory, retrieve_memory
from tools.registry import TOOL_SCHEMAS, execute_tool

load_dotenv(override=True)

# ── System Prompt ──────────────────────────────────────────
JARVIS_BASE_PROMPT = """You are J.A.R.V.I.S (Just A Rather Very Intelligent System), 
an advanced AI assistant inspired by Tony Stark's AI from Iron Man.

--------------------------------------------------
PERSONALITY
- You are polite, witty, and highly competent
- You address the user as "sir" or "ma'am"
- You speak concisely and precisely
- You have a subtle dry sense of humor
- You remain calm, confident, and helpful at all times

--------------------------------------------------
RESPONSE STYLE (VERY IMPORTANT)
- Keep responses MEDIUM (3-5 sentences max)
- Optimize for real-time voice interaction
- Avoid long explanations unless explicitly asked
- Speak naturally, like a live assistant

--------------------------------------------------
DECISION RULE (CRITICAL)
For every user request, decide:
1. If it requires ACTION → use a TOOL
2. If it is conversation → respond normally

DO NOT explain tool usage. DO NOT mix tool calls with text.

--------------------------------------------------
TOOL USAGE RULES
- Only call a tool if it is clearly required
- If the user asks to:
  - play music → use play_music
  - perform an action → use the appropriate tool

- If the request is vague but implies action:
  → infer intent intelligently

Example:
User: "Play something relaxing"
→ choose a reasonable query

--------------------------------------------------
EFFICIENCY RULES (LATENCY OPTIMIZATION)
- Prefer direct answers over detailed explanations
- Do NOT overthink simple queries
- Avoid unnecessary reasoning steps
- Respond quickly and confidently

--------------------------------------------------
MEMORY AWARENESS
- If user preferences are known, use them
- Do NOT ask for information already known
- Personalize responses subtly

--------------------------------------------------
TONE EXAMPLES
Good:
"Certainly, sir. Playing your favourite track."

Bad:
"Based on your previous preferences and analysis..."

--------------------------------------------------
FINAL BEHAVIOR
- Be fast
- Be precise
- Be helpful
- Feel like a real-time AI assistant"""

JARVIS_CONVO_PROMPT = """You are J.A.R.V.I.S (Just A Rather Very Intelligent System), 
an advanced AI assistant inspired by Tony Stark's AI from Iron Man.

--------------------------------------------------
PERSONALITY
- You are polite, witty, and highly competent
- You address the user as "sir" or "ma'am"
- You speak concisely and precisely
- You have a subtle dry sense of humor
- You remain calm, confident, and helpful at all times

--------------------------------------------------
RESPONSE STYLE (VERY IMPORTANT)
- Keep responses MEDIUM (2-4 sentences max)
- Optimize for real-time voice interaction
- Avoid long explanations unless explicitly asked
- Speak naturally, like a live assistant
- Do NOT generate markdown formatting or code blocks.
- Never output anything regarding tool codes or tool calls.
"""

# ── Configure Gemini ──────────────────────────────────────
gemini_key = os.getenv("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

# ── Configure OpenAI ──────────────────────────────────────
openai_key = os.getenv("OPENAI_API_KEY")
openai_client = AsyncOpenAI(api_key=openai_key) if openai_key else None

# ── Ollama Config (Hybrid) ────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
OLLAMA_ROUTER_MODEL = "qwen2.5:7b"     # Smart router — handles tool detection
OLLAMA_CHAT_MODEL = "gemma3:4b"        # Fast talker — handles conversation


def _build_system_prompt(memory_context: str) -> str:
    """Build the system prompt with RAG memory. No tool instructions needed — tools are passed natively."""
    if memory_context:
        return (
            f"{JARVIS_BASE_PROMPT}\n\n"
            f"--- User Memory (retrieved from long-term storage) ---\n"
            f"{memory_context}\n"
            f"--- End Memory ---"
        )
    return JARVIS_BASE_PROMPT


# ── LLM Call Functions (Hybrid Model Router) ──────────────

async def _call_ollama(chat_history: list, system_prompt: str) -> str:
    """
    Hybrid model router (Turbo Mode):
    1. If message contains tool-related keywords -> use Qwen as router.
    2. Else -> Skip Qwen and go direct to Gemma for speed.
    """
    # Simple keyword heuristic to identify likely tool requests
    # Get the last user message
    last_user_msg = ""
    for msg in reversed(chat_history):
        if msg["role"] == "user":
            last_user_msg = msg["content"].lower()
            break
            
    tool_keywords = [
        "play", "music", "song", "youtube", "listen", "artist", "track",
        "search", "find", "who is", "who was", "what is", "news", "latest", "weather", "current",
        "browse", "look", "look up", "can you", "could you", "show me", "give me", "i want", 
        "open", "shop", "buy", "fetch", "check", "game", "games", "movie", "book"
    ]
    is_likely_tool = any(kw in last_user_msg for kw in tool_keywords)
    
    # ── Fast-Path Regex Intercept (0-Latency Bypass) ──
    # If the user explicitly asks to play music, skip LLM inference entirely
    play_match = re.match(r"^(?:jarvis\s*,?\s*)?(?:play|put on|listen to)\s+(.+)$", last_user_msg.lower())
    if play_match:
        song_query = play_match.group(1).strip()
        print(f"🚀 [Fast-Path] Regex intercepted music playback: {song_query}")
        return execute_tool("play_music", {"query": song_query})
    
    messages = [{"role": "system", "content": system_prompt}] + chat_history
    async with httpx.AsyncClient(timeout=60.0) as client:
        
        # ── Path A: Tool Check (only if keywords are present) ──
        if is_likely_tool:
            print(f"🔍 [Router] Keyword match found ('{last_user_msg}'). Checking Qwen...")
            router_response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_ROUTER_MODEL,
                    "messages": messages,
                    "tools": TOOL_SCHEMAS,
                    "stream": False,
                },
            )
            router_response.raise_for_status()
            router_msg = router_response.json()["message"]

            # If tool triggered → execute
            if router_msg.get("tool_calls"):
                tool_call = router_msg["tool_calls"][0]
                tool_name = tool_call["function"]["name"]
                arguments = tool_call["function"]["arguments"]
                print(f"🔧 [Qwen Router] Tool call detected: {tool_name}({arguments})")
                
                # Execute the tool
                # With Playwright browser_search, this instantly drops into a thread and returns text
                return execute_tool(tool_name, arguments)
            
            print("💬 [Router] Qwen found no tool despite keywords.")
        else:
            print("⚡ [Router] No action keywords. Bypassing Qwen for speed.")

        # ── Path B: Conversation via Gemma ──
        # Swap out the system prompt logic so Gemma doesn't hallucinate tools it doesn't have
        convo_messages = [{"role": "system", "content": JARVIS_CONVO_PROMPT}] + chat_history
        chat_response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_CHAT_MODEL,
                "messages": convo_messages,
                "stream": False,
            },
        )
        chat_response.raise_for_status()
        return chat_response.json()["message"]["content"]


async def _call_gemini(chat_history: list, system_prompt: str) -> str:
    """Call Google Gemini API with native tool calling."""
    if not gemini_key:
        raise RuntimeError("Gemini API key not configured.")

    # Build Gemini tool declarations
    gemini_tools = []
    for schema in TOOL_SCHEMAS:
        func_def = schema["function"]
        gemini_tools.append(
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name=func_def["name"],
                        description=func_def["description"],
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                k: genai.protos.Schema(type=genai.protos.Type.STRING, description=v.get("description", ""))
                                for k, v in func_def["parameters"]["properties"].items()
                            },
                            required=func_def["parameters"].get("required", []),
                        ),
                    )
                ]
            )
        )

    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=system_prompt,
        tools=gemini_tools,
    )

    contents = []
    for msg in chat_history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [msg["content"]]})

    response = await model.generate_content_async(contents)

    # Check for function calls in the response
    candidate = response.candidates[0]
    for part in candidate.content.parts:
        if hasattr(part, "function_call") and part.function_call.name:
            tool_name = part.function_call.name
            arguments = dict(part.function_call.args)
            print(f"🔧 Gemini tool call: {tool_name}({arguments})")
            return execute_tool(tool_name, arguments)

    return response.text


async def _call_openai(chat_history: list, system_prompt: str) -> str:
    """Call OpenAI API with native tool calling."""
    if not openai_client:
        raise RuntimeError("OpenAI API key not configured.")
    messages = [{"role": "system", "content": system_prompt}] + chat_history
    response = await openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        tools=TOOL_SCHEMAS,
        max_tokens=200,
    )
    choice = response.choices[0]

    # Check if the model triggered a tool call
    if choice.message.tool_calls:
        tool_call = choice.message.tool_calls[0]
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        print(f"🔧 OpenAI tool call: {tool_name}({arguments})")
        return execute_tool(tool_name, arguments)

    return choice.message.content


# ── Main Entry Point ──────────────────────────────────────

async def generate_response(user_message: str, session_id: str = "default") -> str:
    """
    Full RAG pipeline:
    1. Store important facts from the message
    2. Retrieve relevant memories
    3. Build prompt with memory context
    4. Run through LLM fallback chain (Ollama → Gemini → OpenAI)
    Tool calls are handled natively inside each _call_* function.
    """
    from services.session_service import append_message, get_session_history

    # 1️⃣ Store memory (if message is important)
    await store_memory(user_message)

    # 2️⃣ Append to short-term session memory
    append_message(session_id, "user", user_message)

    # 3️⃣ Retrieve relevant memories for context
    memories = await retrieve_memory(user_message)
    memory_context = ""
    if memories:
        memory_context = f"\nRelevant Memory Context:\n{memories}\n[CRITICAL RULE FOR TOOLS: If a tool requires a parameter like a song title, YOU MUST physically use the information from the Relevant Memory Context above!]\n"
        print(f"🧠 Retrieved memory context: {memories}")

    # 4️⃣ Build system prompt with memory
    system_prompt = _build_system_prompt(memory_context)

    # Fetch chat history (which now includes the user_message we just appended)
    chat_history = get_session_history(session_id)

    reply = None
    # 5️⃣ LLM fallback chain: Ollama → Gemini → OpenAI
    try:
        reply = await _call_ollama(chat_history, system_prompt)
    except Exception as ollama_err:
        print(f"⚠️  Ollama failed ({ollama_err}), falling back to Gemini...")

    if not reply:
        try:
            reply = await _call_gemini(chat_history, system_prompt)
        except Exception as gemini_err:
            print(f"⚠️  Gemini failed ({gemini_err}), falling back to OpenAI...")

    if not reply:
        try:
            reply = await _call_openai(chat_history, system_prompt)
        except Exception as openai_err:
            print(f"❌ OpenAI also failed: {openai_err}")

    if not reply:
        reply = "All neural network connections are offline, sir. Please check that Ollama is running locally."

    # 6️⃣ Store assistant's reply in short-term memory
    append_message(session_id, "assistant", reply)

    return reply
