from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from models.chat_model import ChatRequest, ChatResponse, TTSRequest
from services.llm_service import generate_response
from services.memory_service import get_all_memories, clear_all_memories
from services import text_to_speech_service

app = FastAPI(
    title="Holo Core Nexus API",
    description="Backend API for the J.A.R.V.I.S holographic AI assistant",
    version="0.2.0",
)

# CORS — allow the Vite dev server to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "online", "system": "J.A.R.V.I.S", "version": "0.2.0", "memory": "ChromaDB RAG"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "modules": {"neural_net": True, "voice": True, "memory": "chromadb", "automation": False}}


@app.post("/chat")
async def chat(request: ChatRequest):
    reply = await generate_response(request.message)
    return {"reply": reply}


@app.post("/tts")
async def tts(request: TTSRequest):
    """Convert text to speech using ElevenLabs. Returns MP3 audio."""
    audio = await text_to_speech_service.text_to_speech(request.text)
    if audio is None:
        return {"error": "ElevenLabs not configured. Add ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID to .env"}
    return Response(content=audio, media_type="audio/mpeg")


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
