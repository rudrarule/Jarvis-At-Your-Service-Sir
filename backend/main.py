import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, PlainTextResponse

from models.chat_model import ChatRequest, ChatResponse, TTSRequest
from services.llm_service import generate_response
from services.memory_service import get_all_memories, clear_all_memories
from services import text_to_speech_service
from services.whatsapp_service import (
    send_whatsapp_message,
    is_busy,
    set_busy,
    is_user_allowed,
    BUSY_RESPONSE,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm local subsystems while keeping startup responsive."""
    asyncio.create_task(text_to_speech_service.warm_start())
    yield


app = FastAPI(
    title="Holo Core Nexus API",
    description="Backend API for the J.A.R.V.I.S holographic AI assistant",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "online", "system": "J.A.R.V.I.S", "version": "0.3.0", "memory": "ChromaDB RAG", "channels": ["web", "whatsapp"]}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "modules": {"neural_net": True, "voice": True, "memory": "chromadb", "whatsapp": True, "automation": False}}


@app.post("/chat")
async def chat(request: ChatRequest):
    """Send a message to J.A.R.V.I.S. Tool calls are handled natively by the LLM."""
    reply = await generate_response(request.message, request.session_id)
    return {"reply": reply}


@app.post("/tts")
async def tts(request: TTSRequest):
    """Convert text to speech using local Edge-TTS. Returns MP3 audio."""
    audio = await text_to_speech_service.text_to_speech(request.text)
    if audio is None:
        return {"error": "Local TTS failed. Install edge-tts and ffmpeg/ffplay, or configure Piper fallback."}
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/tts/speak")
async def tts_speak(request: TTSRequest):
    """Speak text on the backend machine via the local voice queue."""
    await text_to_speech_service.speak_locally(request.text, interrupt=True)
    return {"status": "queued"}


@app.post("/tts/stop")
async def tts_stop():
    """Interrupt current and queued TTS playback."""
    await text_to_speech_service.stop()
    return {"status": "stopped"}


@app.post("/tts/pause")
async def tts_pause():
    await text_to_speech_service.pause()
    return {"status": "paused"}


@app.post("/tts/resume")
async def tts_resume():
    await text_to_speech_service.resume()
    return {"status": "resumed"}


@app.post("/tts/voice")
async def tts_set_voice(voice_name: str = Form(...)):
    await text_to_speech_service.set_voice(voice_name)
    return {"voice": voice_name}


@app.post("/tts/rate")
async def tts_set_rate(rate: str = Form(...)):
    await text_to_speech_service.set_rate(rate)
    return {"rate": rate}


@app.post("/tts/pitch")
async def tts_set_pitch(pitch: str = Form(...)):
    await text_to_speech_service.set_pitch(pitch)
    return {"pitch": pitch}


@app.get("/tts/voices")
async def tts_voices():
    return {"suggested_voices": text_to_speech_service.suggested_voices()}


@app.get("/tts/benchmark")
async def tts_benchmark(text: str = "Systems online, sir."):
    return await text_to_speech_service.benchmark(text)


@app.get("/memory")
async def view_memory():
    """View what J.A.R.V.I.S remembers about the user (from ChromaDB)."""
    memories = get_all_memories()
    return {"memory": memories, "count": len(memories)}


@app.delete("/memory")
async def wipe_memory():
    """Clear all stored memories from ChromaDB."""
    clear_all_memories()
    return {"status": "Memory wiped, sir. Starting fresh."}


# ── WhatsApp Integration (Twilio Webhook) ─────────────────

@app.post("/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(""),
    From: str = Form(""),
):
    """
    Twilio WhatsApp Webhook.
    Receives incoming messages, routes through Jarvis brain, replies via Twilio.
    Uses sender phone number as session_id for per-user conversation memory.
    """
    # ── Validate incoming data ──
    if not Body or not From:
        print("[WA] WARN: Received empty message or missing sender.")
        return PlainTextResponse("Missing fields", status_code=400)

    sender = From.strip()
    message = Body.strip()
    print(f"[WA] Incoming from {sender}: {message}")

    # ── Security: Check allowed users ──
    if not is_user_allowed(sender):
        print(f"[WA] BLOCKED: Unauthorized user {sender}")
        return PlainTextResponse("Unauthorized", status_code=403)

    # ── Busy Mode: Skip LLM entirely for instant response ──
    if is_busy():
        print(f"[WA] BUSY: Auto-responding to {sender}")
        await send_whatsapp_message(sender, BUSY_RESPONSE)
        return PlainTextResponse("OK", status_code=200)

    # ── Route through Jarvis brain (single LLM call) ──
    try:
        reply = await generate_response(message, session_id=sender)
    except Exception as e:
        print(f"[WA] ERROR: Jarvis brain - {type(e).__name__}: {e}")
        reply = "My systems encountered an error, sir. Please try again momentarily."

    # ── Send reply back via Twilio ──
    sent = await send_whatsapp_message(sender, reply)
    if not sent:
        print(f"[WA] WARN: Failed to deliver reply to {sender}")

    return PlainTextResponse("OK", status_code=200)


@app.post("/whatsapp/busy")
async def toggle_busy(enable: bool = Form(True)):
    """Toggle Jarvis busy mode. When active, all WhatsApp messages get an auto-response."""
    set_busy(enable)
    state = "ACTIVE" if is_busy() else "INACTIVE"
    print(f"[WA] Busy mode: {state}")
    return {"busy_mode": is_busy(), "message": f"Busy mode {state.lower()}, sir."}


@app.get("/whatsapp/status")
async def whatsapp_status():
    """Check WhatsApp integration status."""
    return {
        "channel": "whatsapp",
        "busy_mode": is_busy(),
        "auto_response": BUSY_RESPONSE if is_busy() else None,
    }
