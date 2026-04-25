"""
text_to_speech_service.py - local TTS service facade.

The public functions here keep the FastAPI layer decoupled from the concrete
voice engine. Edge-TTS is the primary adapter today; Piper/Coqui can replace it
later behind the same manager/queue API.
"""
from jarvis.fallback_manager import FallbackVoiceManager
from jarvis.tts_engine import JARVIS_VOICE_SUGGESTIONS, VoiceEngineError
from jarvis.voice_queue import VoiceQueue


_voice_manager = FallbackVoiceManager()
_voice_queue = VoiceQueue(_voice_manager)


async def warm_start() -> None:
    """Prime the primary voice engine during app startup."""
    await _voice_manager.warm_start()


async def text_to_speech(text: str) -> bytes | None:
    """
    Convert text to MP3 bytes for HTTP clients.

    The current frontend expects the /tts endpoint to return audio/mpeg. Edge
    TTS supports that directly. Offline fallbacks still work for local playback
    through speak_locally(), but may not be able to return MP3 bytes.
    """
    try:
        return await _voice_manager.synthesize_to_bytes(text)
    except VoiceEngineError as exc:
        print(f"[TTS ERROR] HTTP synthesis failed: {exc}")
        return None


async def speak_locally(text: str, interrupt: bool = True) -> None:
    """Queue local speaker playback on the backend machine."""
    await _voice_queue.say(text, interrupt=interrupt)


async def speak_stream(chunks, interrupt: bool = True) -> None:
    """
    Queue local playback from an async token/sentence stream.

    Example:
        await speak_stream(ollama_token_stream(), interrupt=True)
    """
    await _voice_queue.stream(chunks, interrupt=interrupt)


async def stop() -> None:
    """Interrupt active and queued speech."""
    await _voice_queue.stop(clear_queue=True)


async def pause() -> None:
    """Pause active playback when supported by the adapter."""
    await _voice_queue.pause()


async def resume() -> None:
    """Resume active playback when supported by the adapter."""
    await _voice_queue.resume()


async def set_voice(voice_name: str) -> None:
    await _voice_manager.set_voice(voice_name)


async def set_rate(rate: str | int) -> None:
    await _voice_manager.set_rate(rate)


async def set_pitch(pitch: str | int) -> None:
    await _voice_manager.set_pitch(pitch)


async def benchmark(text: str = "Systems online, sir.") -> dict[str, float | str]:
    return await _voice_manager.benchmark_latency(text)


def suggested_voices() -> list[dict[str, str]]:
    return JARVIS_VOICE_SUGGESTIONS


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
