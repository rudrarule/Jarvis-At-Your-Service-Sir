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
    allow_origins=["*"],
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


import json
import re

@app.post("/chat")
async def chat(request: ChatRequest):
    reply = await generate_response(request.message)
    
    final_response = reply

    # ── Parse ReAct Structure ──
    try:
        # Extract the RESPONSE block (what the user actually hears)
        response_match = re.search(r"RESPONSE:\s*(.*)", reply, re.DOTALL | re.IGNORECASE)
        if response_match:
            final_response = response_match.group(1).strip()

        # Check if a tool needs to be executed
        tool_match = re.search(r"TOOL:\s*([A-Za-z0-9_]+)", reply)
        args_match = re.search(r"ARGS:\s*(\{.*\})", reply, re.DOTALL)
        
        if tool_match and args_match:
            tool_name = tool_match.group(1).strip()
            if tool_name.lower() != "none" and tool_name != "":
                
                args_json = args_match.group(1).strip()
                try:
                    args = json.loads(args_json)
                except:
                    args = {}
                
                # Execute specific tools
                if tool_name == "play_music":
                    query = args.get("query", "")
                    if query:
                        from tools.music_tool import play_music
                        title, url = play_music(query)
                        if url:
                            final_response = f"Certainly, sir. Playing {title} on YouTube now."
                        else:
                            final_response = "I apologize, sir. I couldn't find that song on YouTube."
                            
    except Exception as e:
        print(f"🚀 Tool parse error: {e}")
        pass # Fallback to standard reply if parsing hard crashes
            
    # Extra sanitization just in case
    final_response = re.sub(r"(?i)(THOUGHT|TOOL|ARGS|RESPONSE):\s*.*?\n", "", final_response)
    final_response = final_response.strip()
    if not final_response:
        final_response = "I have processed your request, sir."
    
    return {"reply": final_response}


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
