"""
text_to_speech_service.py — ElevenLabs TTS & Tool Dispatcher
Kept separate from the LLM service to avoid circular imports.
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)


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
