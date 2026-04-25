"""
Interactive CLI harness for the J.A.R.V.I.S local TTS stack.

Run from backend/:
    python -m jarvis.test_tts

Or use the wrapper:
    python test_tts.py
"""
from __future__ import annotations

import asyncio

from .fallback_manager import FallbackVoiceManager
from .tts_engine import JARVIS_VOICE_SUGGESTIONS
from .voice_queue import VoiceQueue


HELP = """
Commands:
  /voices                  Show suggested J.A.R.V.I.S voices
  /voice <name>            Switch Edge voice live
  /rate <+/-percent>       Example: /rate +8%
  /pitch <+/-Hz>           Example: /pitch -4Hz
  /bench [text]            Measure Edge-TTS first-audio latency
  /pause                   Pause active playback
  /resume                  Resume active playback
  /stop                    Interrupt speech and clear queue
  /help                    Show this help
  /quit                    Exit
"""


async def main() -> None:
    manager = FallbackVoiceManager()
    queue = VoiceQueue(manager)
    await queue.start()

    print("J.A.R.V.I.S Local TTS Harness")
    print("Warming voice engine...")
    await manager.warm_start()
    print(HELP)

    try:
        while True:
            raw = await asyncio.to_thread(input, "jarvis-tts> ")
            text = raw.strip()
            if not text:
                continue

            if text in {"/quit", "/exit"}:
                break
            if text == "/help":
                print(HELP)
                continue
            if text == "/voices":
                for voice in JARVIS_VOICE_SUGGESTIONS:
                    print(f"  {voice['name']}: {voice['style']}")
                continue
            if text.startswith("/voice "):
                voice_name = text.removeprefix("/voice ").strip()
                await manager.set_voice(voice_name)
                print(f"Voice set to {voice_name}")
                continue
            if text.startswith("/rate "):
                rate = text.removeprefix("/rate ").strip()
                await manager.set_rate(rate)
                print(f"Rate set to {rate}")
                continue
            if text.startswith("/pitch "):
                pitch = text.removeprefix("/pitch ").strip()
                await manager.set_pitch(pitch)
                print(f"Pitch set to {pitch}")
                continue
            if text.startswith("/bench"):
                bench_text = text.removeprefix("/bench").strip() or "Systems online, sir."
                result = await manager.benchmark_latency(bench_text)
                print(
                    "Benchmark: "
                    f"first_audio={result['time_to_first_audio_ms']}ms, "
                    f"full={result['full_synthesis_ms']}ms, "
                    f"voice={result['voice']}"
                )
                continue
            if text == "/pause":
                await queue.pause()
                print("Paused.")
                continue
            if text == "/resume":
                await queue.resume()
                print("Resumed.")
                continue
            if text == "/stop":
                await queue.stop(clear_queue=True)
                print("Stopped.")
                continue

            await queue.say(text, interrupt=True)
    finally:
        await queue.close()


if __name__ == "__main__":
    asyncio.run(main())

