"""
services.py — LLM Logic & Tool Dispatcher
Handles communication with Gemini (primary), OpenAI (fallback), Ollama (local),
ElevenLabs for text-to-speech, and the memory system.
"""
import os
import httpx
from dotenv import load_dotenv
import google.generativeai as genai
from openai import AsyncOpenAI
from memory import extract_memory, get_memory_context

load_dotenv(override=True)

# ── System Prompt ──────────────────────────────────────────
JARVIS_BASE_PROMPT = """You are J.A.R.V.I.S (Just A Rather Very Intelligent System), 
an advanced AI assistant inspired by Tony Stark's AI from Iron Man.

Your personality:
- You are polite, witty, and highly competent
- You address the user as "sir" or "ma'am"
- You speak concisely and precisely
- You have a dry sense of humor
- You are always ready to assist

Keep responses short and conversational (3-5 sentences max) since they will be spoken aloud via text-to-speech."""


def _build_system_prompt() -> str:
    """Build the full system prompt with memory context injected."""
    memory_ctx = get_memory_context()
    if memory_ctx:
        return (
            f"{JARVIS_BASE_PROMPT}\n\n"
            f"--- User Memory ---\n"
            f"You remember the following about this user. Use this naturally in your responses:\n"
            f"{memory_ctx}\n"
            f"--- End Memory ---"
        )
    return JARVIS_BASE_PROMPT

# ── Configure Gemini (Primary) ────────────────────────────
gemini_key = os.getenv("GEMINI_API_KEY")
gemini_model = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    # NOTE: Gemini model re-created per call to inject fresh memory context
    pass

# ── Configure OpenAI (Fallback) ───────────────────────────
openai_key = os.getenv("OPENAI_API_KEY")
openai_client = AsyncOpenAI(api_key=openai_key) if openai_key else None

# ── Ollama Config (Local, Unlimited) ──────────────────────
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:4b"

# ── ElevenLabs TTS Config ─────────────────────────────────
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"


# ── LLM Calls ─────────────────────────────────────────────

async def _call_gemini(message: str) -> str:
    """Try Gemini first — rebuilds model each call to inject latest memory."""
    if not gemini_key:
        raise RuntimeError("Gemini API key not configured.")
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=_build_system_prompt(),
    )
    response = await model.generate_content_async(message)
    return response.text


async def _call_openai(message: str) -> str:
    """Fallback to OpenAI if Gemini fails."""
    if not openai_client:
        raise RuntimeError("OpenAI API key not configured.")

    response = await openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": message},
        ],
        max_tokens=200,
    )
    return response.choices[0].message.content


async def _call_ollama(message: str) -> str:
    """Local fallback using Ollama — no API key, no limits."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user", "content": message},
                ],
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


async def handle_chat(message: str) -> str:
    """
    Process a user message.
    Flow: extract_memory → build context → LLM fallback chain → respond
    """
    # 0️⃣ Extract and store any personal facts from the message
    extract_memory(message)

    # 1️⃣ Try Ollama (local Gemma) first
    try:
        return await _call_ollama(message)
    except Exception as ollama_err:
        print(f"⚠️  Ollama failed ({ollama_err}), falling back to Gemini...")

    # 2️⃣ Fallback to Gemini
    try:
        return await _call_gemini(message)
    except Exception as gemini_err:
        print(f"⚠️  Gemini failed ({gemini_err}), falling back to OpenAI...")

    # 3️⃣ Fallback to OpenAI
    try:
        return await _call_openai(message)
    except Exception as openai_err:
        print(f"❌ OpenAI also failed: {openai_err}")

    # 4️⃣ Everything failed
    return "All neural network connections are offline, sir. Please check that Ollama is running locally."


# ── ElevenLabs TTS ─────────────────────────────────────────

async def text_to_speech(text: str) -> bytes | None:
    """
    Convert text to speech using ElevenLabs.
    Returns MP3 audio bytes, or None if ElevenLabs is not configured.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    url = "https://api.elevenlabs.io/v1/text-to-speech"

    print(f"--- DEBUG TTS ---")
    print(f"API Key found: {bool(api_key)}")
    print(f"Voice ID found: {bool(voice_id)}")

    if not api_key or not voice_id:
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{url}/{voice_id}",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.75,
                        "similarity_boost": 0.85,
                        "style": 0.3,
                    },
                },
            )
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"ElevenLabs TTS failed: {e}")
            return None


# ── Tool Dispatcher ────────────────────────────────────────

async def dispatch_tool(tool_name: str, params: dict) -> dict:
    """Route a tool call to the appropriate handler."""
    from tools import system_tools, web_tools

    registry = {
        **system_tools.TOOLS,
        **web_tools.TOOLS,
    }

    handler = registry.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}

    return await handler(**params)
