#!/usr/bin/env python3
"""Always-on Hex companion with a server-configurable activation phrase."""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import os
import random
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from kokoro_tts import KokoroSpeaker, TTSUnavailable
from audio_capture import AudioUnavailable, UtteranceRecorder


HEX = Path("/Applications/Hex.app/Contents/MacOS/hex")
KEYCHAIN_SERVICE = "hermes-voice-control"
HOTKEY_TRIGGERED = threading.Event()


def emit_state(state: str) -> None:
    """Publish a machine-readable state for the macOS menu app."""
    print(f"NANCY_STATE:{state}", flush=True)


def handle_hotkey(_signum, _frame) -> None:
    HOTKEY_TRIGGERED.set()


def keychain_key() -> str:
    if value := os.environ.get("CONTROL_API_KEY"):
        return value
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


class API:
    def __init__(self, base_url: str, key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.key = key

    def request(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=130) as response:
                return json.load(response)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Control API error: {exc}") from exc

    def settings(self) -> dict:
        return self.request("/settings")

    def submit(self, text: str, conversation: str) -> str:
        return self.request(
            "/commands", "POST", {"text": text, "conversation": conversation}
        )["id"]

    def wait(self, job_id: str, timeout: float = 150) -> str:
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError("Hermes did not finish before the command timeout")
            job = self.request(f"/commands/{job_id}")
            if job["status"] == "completed":
                return job["response"]
            if job["status"] == "failed":
                raise RuntimeError(job.get("error") or "Command failed")
            time.sleep(0.9)


def extract_after_wake_word(transcript: str, wake_word: str) -> tuple[bool, str]:
    match = re.search(rf"\b{re.escape(wake_word)}\b", transcript, flags=re.IGNORECASE)
    if not match:
        return False, ""
    remainder = transcript[match.end():].strip(" ,.!?:;-—")
    return True, remainder


def normalize_phrase(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9']+", " ", value.lower()).split())


def matches_stop_phrase(transcript: str, phrases: list[str]) -> bool:
    normalized = normalize_phrase(transcript)
    return any(normalize_phrase(phrase) in normalized for phrase in phrases)


def is_wake_word_only(transcript: str, wake_word: str) -> bool:
    return normalize_phrase(transcript) == normalize_phrase(wake_word)


def is_likely_echo(
    transcript: str,
    spoken_texts: list[str],
    similarity_threshold: float = 0.78,
) -> bool:
    """Return true when a transcript is probably Nancy's speaker output."""
    heard = normalize_phrase(transcript)
    if not heard:
        return False
    heard_tokens = heard.split()
    for spoken_text in spoken_texts:
        spoken = normalize_phrase(spoken_text)
        if not spoken:
            continue
        if heard == spoken:
            return True
        if len(heard_tokens) >= 3 and (heard in spoken or spoken in heard):
            return True
        if SequenceMatcher(None, heard, spoken).ratio() >= similarity_threshold:
            return True
        spoken_tokens = set(spoken.split())
        token_overlap = sum(token in spoken_tokens for token in heard_tokens)
        if len(heard_tokens) >= 4 and token_overlap / len(heard_tokens) >= 0.85:
            return True
    return False


def transcribe(hex_bin: Path, recorder: UtteranceRecorder, audio) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        path = Path(handle.name)
    try:
        recorder.write_wav(path, audio)
        try:
            result = subprocess.run(
                [str(hex_bin), "transcribe", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "unknown Hex error").strip()
            raise RuntimeError(f"Hex transcription failed: {detail}") from exc
        return result.stdout.strip()
    finally:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://voice-api.builtforyou.live")
    parser.add_argument("--conversation", default="voice-main")
    parser.add_argument("--hex-bin", type=Path, default=HEX)
    parser.add_argument("--print-only", action="store_true", help="Do not synthesize speech")
    args = parser.parse_args()
    signal.signal(signal.SIGUSR1, handle_hotkey)
    if not args.hex_bin.is_file():
        print(f"Hex not found at {args.hex_bin}", file=sys.stderr)
        return 1

    api = API(args.base_url, keychain_key())
    subprocess.run([str(args.hex_bin), "start"], check=True)
    try:
        recorder = UtteranceRecorder()
    except AudioUnavailable as exc:
        print(f"Audio capture is unavailable: {exc}", file=sys.stderr)
        print("Run ./install-kokoro.sh again after installing PortAudio.", file=sys.stderr)
        return 1
    speaker = None
    if not args.print_only:
        try:
            speaker = KokoroSpeaker()
        except TTSUnavailable as exc:
            print(f"Kokoro is not installed: {exc}", file=sys.stderr)
            print("Run ./install-kokoro.sh or start with --print-only.", file=sys.stderr)
            return 1

    print("Nancy companion is running. Press Ctrl+C to stop.")
    emit_state("idle")
    active = False
    pending_transcript = ""
    try:
        while True:
            settings = api.settings()
            wake_word = settings["wake_word"]
            recorder.configure_end_silence(settings["end_silence_seconds"])
            if speaker:
                speaker.configure(settings["tts_voice"], settings["tts_speed"])
                speaker.prepare(
                    settings["acknowledgement_phrases"]
                    + settings["activation_phrases"]
                    + ["Okay."]
                )

            if pending_transcript:
                transcript, pending_transcript = pending_transcript, ""
            else:
                label = "Listening for your next instruction…" if active else f"Listening for “{wake_word}”…"
                print(label, flush=True)
                if active:
                    emit_state("listening")
                audio = recorder.capture_utterance(
                    stop_when=HOTKEY_TRIGGERED.is_set if not active else None
                )
                if HOTKEY_TRIGGERED.is_set():
                    HOTKEY_TRIGGERED.clear()
                    if not active:
                        active = True
                        cue = random.choice(settings["activation_phrases"])
                        print(f"Nancy: {cue}")
                        emit_state("speaking")
                        if speaker:
                            speaker.speak(cue)
                        emit_state("listening")
                        print("Conversation activated by keyboard.")
                    continue
                if audio is None:
                    continue
                try:
                    transcript = transcribe(args.hex_bin, recorder, audio)
                except RuntimeError as exc:
                    print(exc, file=sys.stderr)
                    print("Listening again…", file=sys.stderr)
                    continue
                if not transcript:
                    continue
                print(f"Heard: {transcript}")

            if not active:
                detected, _ = extract_after_wake_word(transcript, wake_word)
                if not detected:
                    continue
                active = True
                cue = random.choice(settings["activation_phrases"])
                print(f"Nancy: {cue}")
                emit_state("speaking")
                if speaker:
                    speaker.speak(cue)
                emit_state("listening")
                print("Conversation active. Say a stop phrase when you're finished.")
                continue

            if (
                is_wake_word_only(transcript, wake_word)
                or matches_stop_phrase(transcript, settings["stop_phrases"])
            ):
                active = False
                print("Nancy: Okay. Conversation closed.")
                emit_state("speaking")
                if speaker:
                    speaker.speak("Okay.")
                emit_state("idle")
                continue

            if matches_stop_phrase(transcript, settings["silence_phrases"]):
                print("Nancy: Speech stopped. Still listening.")
                continue

            print(f"You: {transcript}")
            try:
                job_id = api.submit(transcript, args.conversation)
            except RuntimeError as exc:
                print(f"Could not submit command: {exc}", file=sys.stderr)
                continue
            acknowledgement = random.choice(settings["acknowledgement_phrases"])
            print(f"Nancy: {acknowledgement}")
            emit_state("speaking")
            if speaker:
                speaker.speak(acknowledgement)
            emit_state("processing")
            try:
                answer = api.wait(job_id)
            except RuntimeError as exc:
                print(f"Command failed: {exc}", file=sys.stderr)
                print("Returning to active listening…", file=sys.stderr)
                emit_state("listening")
                continue
            print(f"Nancy: {answer}")
            if speaker:
                emit_state("speaking")
                player = speaker.start(answer)
                barge_threshold = float(
                    os.environ.get("NANCY_BARGE_IN_THRESHOLD", "0.035")
                )
                echo_threshold = float(
                    os.environ.get("NANCY_ECHO_SIMILARITY", "0.78")
                )
                spoken_context = [answer, acknowledgement]
                while player.poll() is None:
                    interrupted_audio = recorder.capture_utterance(
                        stop_when=lambda: player.poll() is not None,
                        threshold=barge_threshold,
                    )
                    if interrupted_audio is None:
                        break
                    try:
                        candidate = transcribe(
                            args.hex_bin, recorder, interrupted_audio
                        )
                    except RuntimeError as exc:
                        print(exc, file=sys.stderr)
                        continue
                    if not candidate:
                        continue
                    if is_likely_echo(candidate, spoken_context, echo_threshold):
                        print(f"Ignored speaker echo: {candidate}")
                        continue
                    pending_transcript = candidate
                    print(f"Interrupted by: {pending_transcript}")
                    player.terminate()
                    try:
                        player.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        player.kill()
                        player.wait()
                    break
                if player.poll() is None:
                    player.wait()
                if not pending_transcript:
                    # Closing and reopening the input stream drops speaker audio
                    # still buffered by macOS after playback finishes.
                    time.sleep(float(os.environ.get("NANCY_ECHO_COOLDOWN", "0.6")))
                emit_state("listening")
            else:
                emit_state("listening")
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
