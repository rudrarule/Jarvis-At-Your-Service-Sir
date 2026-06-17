import sys
import os
import asyncio

# Suppress pygame welcome print message to avoid corrupting MCP stdio stream
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp.server.fastmcp import FastMCP
from services import text_to_speech_service

mcp = FastMCP("AlwaysOnVoice")

@mcp.tool()
async def speak_text(text: str, interrupt: bool = True) -> str:
    """
    Speak a given text locally on the host machine.
    Set interrupt=True to cut off any active speech.
    """
    if os.getenv("JARVIS_MUTE") == "true":
        return f"[MUTE] Successfully simulated speaking: '{text}'"
    try:
        await text_to_speech_service.speak_locally(text, interrupt=interrupt)
        return f"Successfully spoke text locally: '{text}'"
    except Exception as e:
        return f"Failed to speak text: {e}"

@mcp.tool()
async def stop_speaking() -> str:
    """
    Stop any currently active or queued local speech immediately.
    """
    try:
        await text_to_speech_service.stop()
        return "Speech interrupted and voice queue cleared."
    except Exception as e:
        return f"Failed to stop speech: {e}"

@mcp.tool()
async def set_voice_parameters(voice_name: str = None, rate: str = None, pitch: str = None) -> str:
    """
    Configure J.A.R.V.I.S's voice settings.
    voice_name: Name of the voice (e.g., 'en-US-GuyNeural').
    rate: Speech rate adjustment (e.g., '+10%', '-5%').
    pitch: Speech pitch adjustment (e.g., '+0Hz', '-2Hz').
    """
    actions = []
    try:
        if voice_name:
            await text_to_speech_service.set_voice(voice_name)
            actions.append(f"voice set to {voice_name}")
        if rate:
            await text_to_speech_service.set_rate(rate)
            actions.append(f"rate set to {rate}")
        if pitch:
            await text_to_speech_service.set_pitch(pitch)
            actions.append(f"pitch set to {pitch}")
        return f"Updated settings: {', '.join(actions) if actions else 'no changes'}"
    except Exception as e:
        return f"Failed to configure voice: {e}"

@mcp.tool()
async def list_available_voices() -> str:
    """
    List all available suggested voices for J.A.R.V.I.S.
    """
    try:
        voices = text_to_speech_service.suggested_voices()
        return "\n".join([f"- {v.get('name')} ({v.get('lang')}) - {v.get('gender')}" for v in voices])
    except Exception as e:
        return f"Failed to retrieve voices list: {e}"

if __name__ == "__main__":
    mcp.run()
