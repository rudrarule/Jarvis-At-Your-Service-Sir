"""
llm_service.py — LLM Integration with RAG Memory
Handles the LLM fallback chain (Ollama → Gemini → OpenAI)
with vector-retrieved memory injected into the system prompt.
"""
import os
import httpx
from dotenv import load_dotenv
import google.generativeai as genai
from openai import AsyncOpenAI

from services.memory_service import store_memory, retrieve_memory

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

# ── Configure Gemini ──────────────────────────────────────
gemini_key = os.getenv("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

# ── Configure OpenAI ──────────────────────────────────────
openai_key = os.getenv("OPENAI_API_KEY")
openai_client = AsyncOpenAI(api_key=openai_key) if openai_key else None

# ── Ollama Config ─────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:4b"


def _build_system_prompt(memory_context: str) -> str:
    """Build the full system prompt with retrieved memory context and tool descriptions."""
    
    tools_section = (
        "\n\n### TOOL REASONING FRAMEWORK\n"
        "You must analyze every user request using a strict thought process before acting. "
        "You have access to the following tool:\n"
        "- play_music (Input: query string) -> Opens YouTube to play a requested song.\n\n"
        "### REQUIRED OUTPUT FORMAT\n"
        "You MUST structure your ENTIRE reply using exactly these four sections:\n\n"
        "THOUGHT: [Analyze user intent. Do they want music played? Or just a normal question?]\n"
        "TOOL: [Output 'play_music' ONLY if they want to hear a song. Otherwise, output 'None']\n"
        "ARGS: [If TOOL is play_music, output {\"query\": \"song name\"}. Otherwise, output {}]\n"
        "RESPONSE: [Your actual conversational reply to the user. Speak normally as Jarvis.]\n\n"
        "### EXAMPLES\n\n"
        "User: jarvis what's the news about Iran\n"
        "THOUGHT: The user is asking a general knowledge question about current events in Iran.\n"
        "TOOL: None\n"
        "ARGS: {}\n"
        "RESPONSE: Sir, current reports indicate heightened geopolitical activity in the region.\n\n"
        "User: play my favourite song by muse\n"
        "THOUGHT: The user wants to listen to music. I will use the play_music tool for Muse.\n"
        "TOOL: play_music\n"
        "ARGS: {\"query\": \"favourite song by muse\"}\n"
        "RESPONSE: Certainly, sir. Opening YouTube to play Muse for you now.\n"
    )
    
    if memory_context:
        return (
            f"{JARVIS_BASE_PROMPT}\n\n"
            f"--- User Memory (retrieved from long-term storage) ---\n"
            f"{memory_context}\n"
            f"--- End Memory ---"
            f"{tools_section}"
        )
    return JARVIS_BASE_PROMPT + tools_section


# ── LLM Call Functions ────────────────────────────────────

async def _call_ollama(message: str, system_prompt: str) -> str:
    """Call local Ollama model."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


async def _call_gemini(message: str, system_prompt: str) -> str:
    """Call Google Gemini API."""
    if not gemini_key:
        raise RuntimeError("Gemini API key not configured.")
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=system_prompt,
    )
    response = await model.generate_content_async(message)
    return response.text


async def _call_openai(message: str, system_prompt: str) -> str:
    """Call OpenAI API."""
    if not openai_client:
        raise RuntimeError("OpenAI API key not configured.")
    response = await openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        max_tokens=200,
    )
    return response.choices[0].message.content


# ── Main Entry Point ──────────────────────────────────────

async def generate_response(user_message: str) -> str:
    """
    Full RAG pipeline:
    1. Store important facts from the message
    2. Retrieve relevant memories
    3. Build prompt with memory context
    4. Run through LLM fallback chain (Ollama → Gemini → OpenAI)
    """
    # 1️⃣ Store memory (if message is important)
    await store_memory(user_message)

    # 2️⃣ Retrieve relevant memories for context
    memory_context = await retrieve_memory(user_message)
    if memory_context:
        print(f"🔍 Retrieved memory context:\n{memory_context}")

    # 3️⃣ Build system prompt with memory
    system_prompt = _build_system_prompt(memory_context)

    # 4️⃣ LLM fallback chain: Ollama → Gemini → OpenAI
    try:
        return await _call_ollama(user_message, system_prompt)
    except Exception as ollama_err:
        print(f"⚠️  Ollama failed ({ollama_err}), falling back to Gemini...")

    try:
        return await _call_gemini(user_message, system_prompt)
    except Exception as gemini_err:
        print(f"⚠️  Gemini failed ({gemini_err}), falling back to OpenAI...")

    try:
        return await _call_openai(user_message, system_prompt)
    except Exception as openai_err:
        print(f"❌ OpenAI also failed: {openai_err}")

    return "All neural network connections are offline, sir. Please check that Ollama is running locally."
