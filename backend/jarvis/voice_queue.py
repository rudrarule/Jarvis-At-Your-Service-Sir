"""
Async sentence-level TTS queue for J.A.R.V.I.S.

LLM token stream -> sentence chunker -> queue -> single playback worker.
This prevents overlapping speech and supports stop/pause/resume controls.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import AsyncIterable

from .fallback_manager import FallbackVoiceManager
from .tts_engine import VoiceAdapter


SENTENCE_RE = re.compile(r"(.+?[.!?](?:\s+|$))", re.DOTALL)


class SentenceChunker:
    """Incrementally split token streams into natural speech chunks."""

    def __init__(self, min_chars: int = 24, max_chars: int = 260) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        chunks: list[str] = []

        while True:
            match = SENTENCE_RE.match(self._buffer)
            if not match:
                break
            sentence = " ".join(match.group(1).split())
            self._buffer = self._buffer[match.end() :]
            if sentence:
                chunks.append(sentence)

        if len(self._buffer) >= self.max_chars:
            split_at = self._buffer.rfind(",", 0, self.max_chars)
            if split_at < self.min_chars:
                split_at = self._buffer.rfind(" ", 0, self.max_chars)
            if split_at < self.min_chars:
                split_at = self.max_chars
            chunk = " ".join(self._buffer[:split_at].split())
            self._buffer = self._buffer[split_at:]
            if chunk:
                chunks.append(chunk)

        return chunks

    def flush(self) -> list[str]:
        final = " ".join(self._buffer.split())
        self._buffer = ""
        return [final] if final else []


@dataclass
class VoiceJob:
    text: str
    interrupt: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


class VoiceQueue:
    """Producer-consumer queue around a single voice adapter."""

    def __init__(self, engine: VoiceAdapter | None = None) -> None:
        self.engine = engine or FallbackVoiceManager()
        self.queue: asyncio.Queue[VoiceJob | None] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._paused = asyncio.Event()
        self._paused.set()
        self._stopped = False
        self._current_text: str | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._worker_task and not self._worker_task.done())

    @property
    def current_text(self) -> str | None:
        return self._current_text

    async def start(self) -> None:
        if self.is_running:
            return
        self._stopped = False
        self._worker_task = asyncio.create_task(self._worker(), name="jarvis-voice-queue")

    async def close(self) -> None:
        self._stopped = True
        await self.queue.put(None)
        if self._worker_task:
            await self._worker_task
        await self.engine.stop()

    async def say(self, text: str, interrupt: bool = False) -> None:
        """Queue a full text response, split into sentence-sized jobs."""
        await self.start()
        if interrupt:
            await self.stop(clear_queue=True)

        chunker = SentenceChunker()
        chunks = chunker.feed(text) + chunker.flush()
        for chunk in chunks:
            await self.queue.put(VoiceJob(text=chunk, interrupt=False))

    async def stream(self, chunks: AsyncIterable[str], interrupt: bool = False) -> None:
        """Queue text as tokens arrive from a streaming LLM."""
        await self.start()
        if interrupt:
            await self.stop(clear_queue=True)

        chunker = SentenceChunker()
        async for token in chunks:
            for sentence in chunker.feed(token):
                await self.queue.put(VoiceJob(text=sentence))

        for sentence in chunker.flush():
            await self.queue.put(VoiceJob(text=sentence))

    async def stop(self, clear_queue: bool = True) -> None:
        """Interrupt active speech and optionally clear pending chunks."""
        if clear_queue:
            self._drain_queue()
        await self.engine.stop()
        self._paused.set()

    async def pause(self) -> None:
        """Pause playback and stop consuming new chunks."""
        self._paused.clear()
        await self.engine.pause()

    async def resume(self) -> None:
        """Resume playback and queue consumption."""
        self._paused.set()
        await self.engine.resume()

    def _drain_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def _worker(self) -> None:
        while not self._stopped:
            job = await self.queue.get()
            try:
                if job is None:
                    return
                await self._paused.wait()
                if job.interrupt:
                    await self.stop(clear_queue=True)
                self._current_text = job.text
                await self.engine.speak(job.text)
            finally:
                self._current_text = None
                self.queue.task_done()

