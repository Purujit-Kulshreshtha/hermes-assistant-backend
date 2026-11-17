"""Sentence-at-a-time Kokoro synthesis for Nancy's streaming TTS endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import wave
from pathlib import Path


class TTSUnavailable(RuntimeError):
    """Raised when the optional server-side speech stack is unavailable."""


class KokoroStreamEngine:
    sample_rate = 24_000

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._pipeline = None
        self._lock = asyncio.Lock()

    @staticmethod
    def sentences(text: str) -> list[str]:
        pieces = re.findall(r"[^.!?\n]+(?:[.!?]+|\n|$)", text.strip()) or [text]
        result: list[str] = []
        for piece in pieces:
            piece = piece.strip()
            while len(piece) > 360:
                split_at = piece.rfind(" ", 0, 360)
                split_at = split_at if split_at > 80 else 360
                result.append(piece[:split_at].strip())
                piece = piece[split_at:].strip()
            if piece:
                result.append(piece)
        return result

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise TTSUnavailable(
                "Server speech is not installed; install the TTS requirements"
            ) from exc
        self._pipeline = KPipeline(lang_code="a")
        return self._pipeline

    def _render_sync(self, text: str, voice: str, speed: float) -> bytes:
        digest = hashlib.sha256(f"{voice}|{speed:.3f}|{text}".encode()).hexdigest()
        cached = self.cache_dir / f"{digest}.wav"
        if cached.exists():
            return cached.read_bytes()

        pipeline = self._load_pipeline()
        chunks = [
            audio.detach().cpu().numpy() if hasattr(audio, "detach") else audio
            for _, _, audio in pipeline(
                text, voice=voice, speed=speed, split_pattern=None
            )
        ]
        if not chunks:
            raise RuntimeError("Kokoro returned no audio")

        try:
            import numpy as np
        except ImportError as exc:
            raise TTSUnavailable("numpy is required for server speech") from exc
        samples = np.concatenate(chunks)
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)
        data = output.getvalue()
        temporary = cached.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(cached)
        return data

    async def render(self, text: str, voice: str, speed: float) -> bytes:
        # Kokoro's pipeline is shared and not safe to run concurrently.
        async with self._lock:
            return await asyncio.to_thread(self._render_sync, text, voice, speed)
