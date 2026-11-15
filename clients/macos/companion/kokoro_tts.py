"""Persistent Kokoro/MLX speaker for Apple Silicon."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path


class TTSUnavailable(RuntimeError):
    pass


class KokoroSpeaker:
    def __init__(self) -> None:
        try:
            import mlx.core as mx
            import numpy as np
            import soundfile as sf
            from mlx_audio.tts.utils import load_model
        except ImportError as exc:
            raise TTSUnavailable(str(exc)) from exc
        self.mx, self.np, self.sf = mx, np, sf
        self.model = load_model("mlx-community/Kokoro-82M-bf16")
        self.voice = "af_heart"
        self.speed = 1.0
        self.cache = Path(tempfile.gettempdir()) / "nancy-kokoro-cache"
        self.cache.mkdir(exist_ok=True)

    def configure(self, voice: str, speed: float) -> None:
        self.voice, self.speed = voice, speed

    def _render(self, text: str) -> Path:
        digest = hashlib.sha256(
            f"{self.voice}|{self.speed}|{text}".encode()
        ).hexdigest()[:20]
        output = self.cache / f"{digest}.wav"
        if output.exists():
            return output
        chunks, sample_rate = [], 24000
        for result in self.model.generate(
            text=text, voice=self.voice, speed=self.speed, lang_code="a"
        ):
            self.mx.eval(result.audio)
            chunks.append(self.np.asarray(result.audio))
            sample_rate = getattr(result, "sample_rate", sample_rate)
        if not chunks:
            raise RuntimeError("Kokoro returned no audio")
        self.sf.write(output, self.np.concatenate(chunks), sample_rate)
        return output

    def prepare(self, phrases: list[str]) -> None:
        for phrase in phrases:
            self._render(phrase)

    def speak(self, text: str) -> None:
        subprocess.run(["afplay", str(self._render(text))], check=True)

    def start(self, text: str) -> subprocess.Popen:
        return subprocess.Popen(
            ["afplay", str(self._render(text))],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
