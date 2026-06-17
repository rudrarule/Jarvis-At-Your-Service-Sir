import asyncio
import os
import sys
import time

# Windows-specific: ProactorEventLoop is required for subprocesses (Playwright, etc.)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, PlainTextResponse, StreamingResponse

from models.chat_model import ChatRequest, ChatResponse, TTSRequest, MusicRequest, AppRequest
from models.overlay_model import OverlayFollowUpRequest
from services.llm_service import generate_response, _fix_markdown
from services.memory_service import get_all_memories, clear_all_memories
from services import text_to_speech_service
from services.overlay_context_service import (
    clear_overlay_history,
    get_overlay_context_public,
    list_overlay_history,
    list_overlay_sessions,
)
from services.overlay_ocr_service import OverlayOcrUnavailable, extract_overlay_text
from services.overlay_service import OverlayCaptureRejected, ask_about_overlay_region, ask_overlay_follow_up
from services.dashboard_event_service import (
    emit_dashboard_event,
    get_dashboard_history,
    get_dashboard_snapshot,
    get_system_health,
    subscribe_dashboard_events,
    unsubscribe_dashboard_events,
)
from services.mission_store import (
    complete_mission,
    create_mission,
    fail_mission,
    get_mission,
    get_mission_events,
    list_missions,
    reset_current_mission_id,
    set_current_mission_id,
)
from services.whatsapp_service import (
    send_whatsapp_message,
    is_busy,
    set_busy,
    is_user_allowed,
    BUSY_RESPONSE,
)
from services import whatsapp_baileys_service as wa_baileys


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm local subsystems while keeping startup responsive."""
    asyncio.create_task(text_to_speech_service.warm_start())

    # ── MCP tools (flag-gated by JARVIS_MCP, fail-open) ──
    # Load on the running loop, merge into ALL_TOOLS, and rebuild the ReAct graph so
    # its ToolNode can execute the new tools. Any failure leaves the agent unchanged.
    try:
        from services.mcp_client import load_mcp_tools, mcp_enabled

        if mcp_enabled():
            mcp_tools = await load_mcp_tools()
            if mcp_tools:
                import workflows.tool_wrapper as tw
                import workflows.master_graph as mg

                tw.ALL_TOOLS.extend(mcp_tools)               # guard reads ALL_TOOLS live
                mg.master_graph_app = mg.build_master_graph()  # rebuild ToolNode w/ MCP tools
                print(f"[MCP] Agent rebuilt with {len(tw.ALL_TOOLS)} total tools.")
    except Exception as exc:
        print(f"[MCP] Integration skipped (fail-open): {exc}")

    await emit_dashboard_event(
        "system.startup",
        {"service": "Holo Core Nexus API", "version": "0.3.0"},
        source="api",
    )
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
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173", 
        "http://127.0.0.1:5173",
        "https://*.ngrok-free.app",
        "https://*.ngrok-free.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "ngrok-skip-browser-warning"],
)


@app.get("/api/status")
async def root():
    return {"status": "online", "system": "J.A.R.V.I.S", "version": "0.3.0", "memory": "ChromaDB RAG", "channels": ["web", "whatsapp"]}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "modules": {"neural_net": True, "voice": True, "memory": "chromadb", "whatsapp": True, "automation": False}}


@app.get("/dashboard/snapshot")
async def dashboard_snapshot():
    return get_dashboard_snapshot()


@app.get("/dashboard/events")
async def dashboard_events(limit: int = 50):
    return {"events": get_dashboard_history(limit)}


@app.get("/dashboard/health")
async def dashboard_health():
    return get_system_health()


@app.get("/dashboard/missions")
async def dashboard_missions(limit: int = 20):
    return {"missions": list_missions(limit)}


@app.get("/dashboard/missions/{mission_id}")
async def dashboard_mission_detail(mission_id: str):
    mission = get_mission(mission_id)
    if not mission:
        return {"mission": None, "events": []}
    return {"mission": mission, "events": get_mission_events(mission_id)}


@app.websocket("/dashboard/ws")
async def dashboard_websocket(websocket: WebSocket):
    await websocket.accept()
    queue = subscribe_dashboard_events()
    try:
        await websocket.send_json({"type": "dashboard.snapshot", "payload": get_dashboard_snapshot()})
        await emit_dashboard_event("dashboard.client_connected", {"subscribers": get_dashboard_snapshot()["subscribers"]}, source="dashboard")

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "system.health",
                        "source": "api",
                        "level": "info",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "payload": get_system_health(),
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe_dashboard_events(queue)
        await emit_dashboard_event("dashboard.client_disconnected", {"subscribers": get_dashboard_snapshot()["subscribers"]}, source="dashboard")


@app.post("/chat")
async def chat(request: ChatRequest):
    """Send a message to J.A.R.V.I.S. Tool calls are handled natively by the LLM."""
    started = time.perf_counter()
    mission = create_mission(request.session_id, request.message)
    mission_id = mission["id"]
    mission_token = set_current_mission_id(mission_id)
    await emit_dashboard_event(
        "mission.started",
        {"mission_id": mission_id, "session_id": request.session_id, "mission": mission},
        source="mission",
    )
    await emit_dashboard_event(
        "agent.request",
        {"mission_id": mission_id, "session_id": request.session_id, "message": request.message},
        source="chat",
    )
    try:
        reply = await generate_response(request.message, request.session_id)
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        failed = fail_mission(mission_id, f"{type(exc).__name__}: {exc}", elapsed_ms)
        await emit_dashboard_event(
            "agent.error",
            {"mission_id": mission_id, "session_id": request.session_id, "error": f"{type(exc).__name__}: {exc}"},
            source="chat",
            level="error",
        )
        await emit_dashboard_event(
            "mission.updated",
            {"mission_id": mission_id, "session_id": request.session_id, "mission": failed},
            source="mission",
            level="error",
        )
        reset_current_mission_id(mission_token)
        raise

    # Single chokepoint: normalize every chat reply into well-formed markdown
    # so the frontend renders bullets/headers instead of a raw-asterisk wall.
    reply = _fix_markdown(reply)

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    completed = complete_mission(mission_id, reply, elapsed_ms)
    await emit_dashboard_event(
        "agent.response",
        {"mission_id": mission_id, "session_id": request.session_id, "duration_ms": elapsed_ms, "reply": reply},
        source="chat",
    )
    await emit_dashboard_event(
        "mission.updated",
        {"mission_id": mission_id, "session_id": request.session_id, "mission": completed},
        source="mission",
    )
    reset_current_mission_id(mission_token)
    return {"reply": reply}


@app.post("/overlay/ask")
async def overlay_ask(
    image: UploadFile = File(...),
    question: str = Form(...),
    session_id: str = Form("overlay"),
    screen_name: str | None = Form(None),
    app_name: str | None = Form(None),
    process_name: str | None = Form(None),
    process_path: str | None = Form(None),
    window_title: str | None = Form(None),
    region_x: int | None = Form(None),
    region_y: int | None = Form(None),
    region_width: int | None = Form(None),
    region_height: int | None = Form(None),
    device_pixel_ratio: float | None = Form(None),
):
    """Analyze a user-selected screen region captured by the desktop overlay."""
    image_bytes = await image.read()
    try:
        return await ask_about_overlay_region(
            image_bytes=image_bytes,
            question=question,
            session_id=session_id,
            content_type=image.content_type,
            metadata={
                "screen_name": screen_name,
                "app_name": app_name,
                "process_name": process_name,
                "process_path": process_path,
                "window_title": window_title,
                "region_x": region_x,
                "region_y": region_y,
                "region_width": region_width,
                "region_height": region_height,
                "device_pixel_ratio": device_pixel_ratio,
            },
        )
    except OverlayCaptureRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/overlay/ask/stream")
async def overlay_ask_stream(
    image: UploadFile = File(...),
    question: str = Form(...),
    session_id: str = Form("overlay"),
    screen_name: str | None = Form(None),
    app_name: str | None = Form(None),
    process_name: str | None = Form(None),
    process_path: str | None = Form(None),
    window_title: str | None = Form(None),
    region_x: int | None = Form(None),
    region_y: int | None = Form(None),
    region_width: int | None = Form(None),
    region_height: int | None = Form(None),
    device_pixel_ratio: float | None = Form(None),
):
    """SSE-compatible overlay ask endpoint. Emits status now and final answer when ready."""
    image_bytes = await image.read()

    async def stream():
        import json

        yield "event: status\ndata: {\"status\":\"analyzing\"}\n\n"
        try:
            result = await ask_about_overlay_region(
                image_bytes=image_bytes,
                question=question,
                session_id=session_id,
                content_type=image.content_type,
                metadata={
                    "screen_name": screen_name,
                    "app_name": app_name,
                    "process_name": process_name,
                    "process_path": process_path,
                    "window_title": window_title,
                    "region_x": region_x,
                    "region_y": region_y,
                    "region_width": region_width,
                    "region_height": region_height,
                    "device_pixel_ratio": device_pixel_ratio,
                },
            )
            yield f"event: final\ndata: {json.dumps(result, ensure_ascii=True)}\n\n"
        except Exception as exc:
            payload = {"error": str(exc)}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=True)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/overlay/follow-up")
async def overlay_follow_up(request: OverlayFollowUpRequest):
    try:
        return await ask_overlay_follow_up(
            context_id=request.context_id,
            question=request.question,
            session_id=request.session_id,
        )
    except OverlayCaptureRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/overlay/ocr")
async def overlay_ocr(image: UploadFile = File(...)):
    image_bytes = await image.read()
    try:
        return extract_overlay_text(image_bytes)
    except OverlayOcrUnavailable as exc:
        return {"text": "", "engine": None, "character_count": 0, "available": False, "detail": str(exc)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/overlay/history")
async def overlay_history(limit: int = 30):
    history = list_overlay_history(limit)
    return {"history": history, "count": len(history)}


@app.get("/overlay/sessions")
async def overlay_sessions(limit: int = 30):
    sessions = list_overlay_sessions(limit)
    return {"sessions": sessions, "count": len(sessions)}


@app.get("/overlay/session/{context_id}")
async def overlay_session_detail(context_id: str):
    session = get_overlay_context_public(context_id)
    if not session:
        raise HTTPException(status_code=404, detail="Overlay session not found.")
    return {"session": session}


@app.delete("/overlay/history")
async def overlay_history_clear():
    clear_overlay_history()
    return {"status": "cleared"}


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


# ── Stark Protocol Orchestration ──────────────────────────

@app.get("/stark-protocol/briefing")
async def stark_briefing():
    import datetime
    import re
    from tools.weather_tool import get_weather
    from services.whatsapp_baileys_service import get_unread_summary, get_missed_calls

    hour = datetime.datetime.now().hour
    if hour < 12:
        greeting = "Good morning, sir."
    elif hour < 18:
        greeting = "Good afternoon, sir."
    else:
        greeting = "Good evening, sir."

    # Schedule / Priority
    calendar_text = "One meeting is scheduled for 3 PM."
    
    # Communications
    unread_data = await get_unread_summary()
    missed_data = await get_missed_calls()
    
    unread_count = unread_data.get("total_messages", 0) if isinstance(unread_data, dict) else 0
    missed_calls = missed_data.get("count", 0) if isinstance(missed_data, dict) else 0
    
    comm_bullets = []
    if missed_calls > 0:
        comm_bullets.append(f"You have {missed_calls} missed call{'s' if missed_calls > 1 else ''} that may need attention.")
    if unread_count > 0:
        comm_bullets.append(f"You have {unread_count} unread message{'s' if unread_count > 1 else ''}.")
        
    if not comm_bullets:
        comm_text = "No urgent messages need attention."
    else:
        comm_text = " ".join(comm_bullets)

    # Environment
    raw_weather = get_weather("") 
    temp_match = re.search(r"([+-]?\d+)[°]?[CF]", raw_weather, re.IGNORECASE)
    
    if temp_match:
        temp = int(temp_match.group(1))
        if temp < 20:
            weather_text = f"It is quite cold outside at {temp} degrees."
        elif temp > 30:
            weather_text = f"It is quite warm outside at {temp} degrees."
        else:
            weather_text = f"It is pleasant outside at {temp} degrees."
    else:
        weather_text = "Weather data is currently unavailable."

    # Systems
    system_text = "Systems are nominal."

    bullets = [calendar_text, comm_text, weather_text, system_text]
    
    spoken_text = f"{greeting} Here is your priority brief. " + " ".join(bullets)
    
    display_bullets = "\n\n".join([f"• {b}" for b in bullets])
    display_text = f"{greeting}\n\nHere is your priority brief.\n\n{display_bullets}"

    return {
        "text": spoken_text,
        "spoken_text": spoken_text,
        "display_text": display_text
    }


@app.post("/stark-protocol/music")
async def stark_music(request: MusicRequest = None):
    from tools.music_tool import play_music
    query = request.query if request else "light rock playlist"
    title, url = play_music(query)
    return {"title": title, "url": url}


@app.post("/stark-protocol/open-app")
async def stark_open_app(request: AppRequest):
    from tools.system_control_tool import open_app
    result = open_app(request.app_name)
    return {"status": result}


# ── Speech-to-Text (for background tab command capture) ────
@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """
    Accepts raw WAV audio, transcribes using faster-whisper (local).
    Used when the browser tab is in the background and webkitSpeechRecognition fails.
    """
    import tempfile, os
    from faster_whisper import WhisperModel

    try:
        audio_bytes = await audio.read()
        if len(audio_bytes) < 100:
            return {"text": ""}

        # Write to temp file for faster-whisper
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        try:
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(temp_path, beam_size=1, language="en")
            text = " ".join(seg.text.strip() for seg in segments).strip()
            print(f"[STT] Transcribed: \"{text}\"")
            return {"text": text}
        finally:
            os.unlink(temp_path)
    except Exception as e:
        print(f"[STT] Error: {e}")
        return {"text": ""}


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


# ── WhatsApp Baileys Connector Integration ─────────────────

@app.get("/wa/health")
async def wa_connector_health():
    """Check if the Baileys WhatsApp connector is alive."""
    return await wa_baileys.connector_health()


@app.get("/wa/unread")
async def wa_unread():
    """Fetch unread WhatsApp messages from Baileys connector."""
    return await wa_baileys.get_unread_summary()


@app.get("/wa/missed-calls")
async def wa_missed_calls(since: int = None):
    """Fetch missed WhatsApp call events."""
    return await wa_baileys.get_missed_calls(since)


@app.post("/wa/send")
async def wa_send_message(chat_id: str = Form(...), text: str = Form(...)):
    """Send a WhatsApp message via the Baileys connector."""
    return await wa_baileys.send_whatsapp_message(chat_id, text)


@app.get("/wa/briefing")
async def wa_briefing():
    """
    Get a raw WhatsApp briefing for Jarvis to summarize.
    Use this when the user asks 'who messaged me?' or 'any missed calls?'
    """
    briefing = await wa_baileys.get_whatsapp_briefing()
    return {"briefing": briefing}


@app.get("/wa/connection")
async def wa_connection():
    """Get the Baileys connector's current connection state."""
    return await wa_baileys.get_connection_state()


@app.post("/wa/clear-unread")
async def wa_clear_unread(chat_id: str = Form(None)):
    """Clear unread messages, optionally for a specific chat."""
    return await wa_baileys.clear_unread(chat_id)


@app.post("/wa/clear-calls")
async def wa_clear_calls():
    """Clear all missed call records."""
    return await wa_baileys.clear_missed_calls()


# Dynamic Uvicorn hot-reload trigger after .env update

import os
from fastapi.staticfiles import StaticFiles

# Serve the compiled React Frontend at the root
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    import sys
    import asyncio
    
    if sys.platform == 'win32':
        # Force ProactorEventLoop before uvicorn starts
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    uvicorn.run(app, host="0.0.0.0", port=8000)
