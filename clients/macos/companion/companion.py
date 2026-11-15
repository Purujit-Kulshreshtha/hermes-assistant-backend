#!/usr/bin/env python3
"""Always-on Hex companion with a server-configurable activation phrase."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from kokoro_tts import KokoroSpeaker, TTSUnavailable
from audio_capture import AudioUnavailable, UtteranceRecorder


HEX = Path("/Applications/Hex.app/Contents/MacOS/hex")
KEYCHAIN_SERVICE = "hermes-voice-control"


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

    def wait(self, job_id: str) -> str:
        while True:
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
    armed = False
    try:
        while True:
            settings = api.settings()
            wake_word = settings["wake_word"]
            if speaker:
                speaker.configure(settings["tts_voice"], settings["tts_speed"])
                speaker.prepare(settings["acknowledgement_phrases"])
            print(f"Listening for “{wake_word}”…", flush=True)
            audio = recorder.capture_utterance()
            try:
                transcript = transcribe(args.hex_bin, recorder, audio)
            except RuntimeError as exc:
                print(exc, file=sys.stderr)
                print("Listening again…", file=sys.stderr)
                continue
            if not transcript:
                continue
            print(f"Heard: {transcript}")
            command = ""
            if armed:
                command, armed = transcript, False
            else:
                detected, remainder = extract_after_wake_word(transcript, wake_word)
                if detected and remainder:
                    command = remainder
                elif detected:
                    armed = True
                    print("Wake word detected; waiting for the instruction…")
            if not command:
                continue
            print(f"You: {command}")
            job_id = api.submit(command, args.conversation)
            acknowledgement = random.choice(settings["acknowledgement_phrases"])
            print(f"Nancy: {acknowledgement}")
            if speaker:
                speaker.speak(acknowledgement)
            answer = api.wait(job_id)
            print(f"Nancy: {answer}")
            if speaker:
                speaker.speak(answer)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
