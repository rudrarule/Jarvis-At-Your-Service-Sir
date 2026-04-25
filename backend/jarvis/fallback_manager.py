"""
Fallback TTS manager.

Fallback order:
1. Edge-TTS via JarvisVoice
2. Piper executable + local model, if configured
3. pyttsx3 emergency local voice
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from .tts_engine import JarvisVoice, VoiceAdapter, VoiceEngineError


class PiperVoice:
    """
    Piper adapter.

    Configure with:
    - PIPER_EXE_PATH=C:\\path\\to\\piper.exe
    - PIPER_MODEL_PATH=C:\\path\\to\\voice.onnx
    """

    def __init__(
        self,
        exe_path: str | None = None,
        model_path: str | None = None,
        ffplay_path: str | None = None,
    ) -> None:
        self.exe_path = exe_path or os.getenv("PIPER_EXE_PATH", "")
        self.model_path = model_path or os.getenv("PIPER_MODEL_PATH", "")
        self.ffplay_path = ffplay_path or shutil.which("ffplay")
        self._current_process: asyncio.subprocess.Process | None = None

    @property
    def available(self) -> bool:
        return bool(
            self.exe_path
            and self.model_path
            and Path(self.exe_path).exists()
            and Path(self.model_path).exists()
        )

    async def speak(self, text: str) -> None:
        wav_bytes = await self.synthesize_to_bytes(text)
        if not self.ffplay_path:
            raise VoiceEngineError("Piper synthesized audio, but ffplay is unavailable.")

        process = await asyncio.create_subprocess_exec(
            self.ffplay_path,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            "-i",
            "pipe:0",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._current_process = process
        try:
            if process.stdin:
                process.stdin.write(wav_bytes)
                await process.stdin.drain()
                process.stdin.close()
            await process.wait()
        finally:
            self._current_process = None

    async def synthesize_to_bytes(self, text: str) -> bytes:
        if not self.available:
            raise VoiceEngineError("Piper is not configured.")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            output_path = temp.name

        try:
            process = await asyncio.create_subprocess_exec(
                self.exe_path,
                "--model",
                self.model_path,
                "--output_file",
                output_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate(text.encode("utf-8"))
            if process.returncode != 0:
                raise VoiceEngineError(
                    f"Piper failed: {stderr.decode('utf-8', errors='ignore')}"
                )
            return Path(output_path).read_bytes()
        finally:
            try:
                Path(output_path).unlink(missing_ok=True)
            except Exception:
                pass

    async def stop(self) -> None:
        if self._current_process and self._current_process.returncode is None:
            self._current_process.kill()
            await self._current_process.wait()

    async def pause(self) -> None:
        return None

    async def resume(self) -> None:
        return None


class Pyttsx3Voice:
    """Emergency local TTS adapter. Not natural, but it keeps J.A.R.V.I.S audible."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = asyncio.Lock()

    async def speak(self, text: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._speak_blocking, text)

    async def synthesize_to_bytes(self, text: str) -> bytes:
        raise VoiceEngineError("pyttsx3 does not provide HTTP audio bytes here.")

    async def stop(self) -> None:
        if self._engine:
            await asyncio.to_thread(self._engine.stop)

    async def pause(self) -> None:
        return None

    async def resume(self) -> None:
        return None

    def _speak_blocking(self, text: str) -> None:
        import pyttsx3

        if self._engine is None:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 178)
            self._engine.setProperty("volume", 1.0)
            self._select_male_voice()

        self._engine.say(text)
        self._engine.runAndWait()

    def _select_male_voice(self) -> None:
        voices = self._engine.getProperty("voices") or []
        for voice in voices:
            haystack = f"{voice.id} {voice.name}".lower()
            if "male" in haystack or "david" in haystack or "mark" in haystack:
                self._engine.setProperty("voice", voice.id)
                return


class FallbackVoiceManager:
    """Try voice adapters in order and keep the queue API engine-agnostic."""

    def __init__(self, primary: JarvisVoice | None = None) -> None:
        self.primary = primary or JarvisVoice()
        self.adapters: list[VoiceAdapter] = [
            self.primary,
            PiperVoice(),
            Pyttsx3Voice(),
        ]
        self.last_engine: str | None = None
        self.last_error: str | None = None

    async def speak(self, text: str) -> None:
        errors: list[str] = []
        for adapter in self.adapters:
            try:
                await adapter.speak(text)
                self.last_engine = adapter.__class__.__name__
                self.last_error = None
                return
            except Exception as exc:
                errors.append(f"{adapter.__class__.__name__}: {exc}")
                self.last_error = str(exc)
        raise VoiceEngineError("All TTS engines failed: " + " | ".join(errors))

    async def synthesize_to_bytes(self, text: str) -> bytes:
        for adapter in self.adapters:
            try:
                data = await adapter.synthesize_to_bytes(text)
                self.last_engine = adapter.__class__.__name__
                self.last_error = None
                return data
            except Exception as exc:
                self.last_error = str(exc)
        raise VoiceEngineError("No TTS engine could synthesize HTTP audio bytes.")

    async def stop(self) -> None:
        await asyncio.gather(*(adapter.stop() for adapter in self.adapters), return_exceptions=True)

    async def pause(self) -> None:
        await asyncio.gather(*(adapter.pause() for adapter in self.adapters), return_exceptions=True)

    async def resume(self) -> None:
        await asyncio.gather(*(adapter.resume() for adapter in self.adapters), return_exceptions=True)

    async def set_voice(self, voice_name: str) -> None:
        await self.primary.set_voice(voice_name)

    async def set_rate(self, rate: str | int) -> None:
        await self.primary.set_rate(rate)

    async def set_pitch(self, pitch: str | int) -> None:
        await self.primary.set_pitch(pitch)

    async def warm_start(self) -> None:
        await self.primary.warm_start()

    async def benchmark_latency(self, text: str = "Systems online, sir.") -> dict[str, float | str]:
        return await self.primary.benchmark_latency(text)

