"""Small energy-based voice activity recorder for the Nancy companion."""

from __future__ import annotations

import os
import queue
import wave
from collections import deque
from pathlib import Path


class AudioUnavailable(RuntimeError):
    pass


class UtteranceRecorder:
    def __init__(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise AudioUnavailable(str(exc)) from exc
        self.np, self.sd = np, sd
        self.sample_rate = 16000
        self.block_seconds = 0.1
        self.block_size = int(self.sample_rate * self.block_seconds)
        self.threshold = float(os.environ.get("NANCY_SPEECH_THRESHOLD", "0.012"))
        self.silence_blocks = 8
        self.max_blocks = 120
        self.pre_roll_blocks = 4
        self.device = os.environ.get("NANCY_AUDIO_DEVICE") or None

    def capture_utterance(self, *, stop_when=None, threshold: float | None = None):
        blocks: queue.Queue = queue.Queue()
        pre_roll = deque(maxlen=self.pre_roll_blocks)
        frames = []
        active = False
        quiet = 0
        effective_threshold = threshold or self.threshold

        def callback(indata, frame_count, time_info, status):
            del frame_count, time_info
            if status:
                print(f"Audio warning: {status}")
            blocks.put(indata.copy())

        try:
            with self.sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.block_size,
                device=self.device,
                callback=callback,
            ):
                while True:
                    if stop_when and stop_when():
                        return None
                    try:
                        block = blocks.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    rms = float(self.np.sqrt(self.np.mean(self.np.square(block))))
                    if not active:
                        pre_roll.append(block)
                        if rms >= effective_threshold:
                            active = True
                            frames.extend(pre_roll)
                        continue
                    frames.append(block)
                    quiet = quiet + 1 if rms < effective_threshold else 0
                    if quiet >= self.silence_blocks or len(frames) >= self.max_blocks:
                        break
        except Exception as exc:
            raise AudioUnavailable(str(exc)) from exc
        return self.np.concatenate(frames, axis=0)

    def write_wav(self, path: Path, audio) -> None:
        pcm = self.np.clip(audio * 32767, -32768, 32767).astype(self.np.int16)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.sample_rate)
            output.writeframes(pcm.tobytes())
