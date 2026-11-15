#!/usr/bin/env python3
"""Push-to-talk macOS client for Hex and the Hermes control API."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_API_URL = "https://voice-api.builtforyou.live/command"
DEFAULT_CONVERSATION = "voice-main"
DEFAULT_HEX_BIN = Path("/Applications/Hex.app/Contents/MacOS/hex")
KEYCHAIN_SERVICE = "hermes-voice-control"


class ClientError(RuntimeError):
    """An expected client failure with a user-readable message."""


def run_command(args: list[str], *, capture: bool = False) -> str:
    try:
        result = subprocess.run(
            args,
            check=True,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        raise ClientError(f"Command not found: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ClientError(detail or f"Command failed: {' '.join(args)}") from exc
    return result.stdout.strip() if capture else ""


def read_api_key() -> str:
    if key := os.environ.get("CONTROL_API_KEY"):
        return key
    try:
        return run_command(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture=True,
        )
    except ClientError as exc:
        raise ClientError(
            "Control key not found. Run ./setup-keychain.sh first."
        ) from exc


def ensure_hex(hex_bin: Path) -> None:
    if not hex_bin.is_file():
        raise ClientError(f"Hex was not found at {hex_bin}")
    run_command([str(hex_bin), "start"])


def record_with_hex(hex_bin: Path) -> str:
    run_command([str(hex_bin), "dictation", "start", "--raw"])
    try:
        input("Recording… press Enter to stop. ")
    except (EOFError, KeyboardInterrupt):
        run_command([str(hex_bin), "dictation", "cancel"])
        raise

    transcript = run_command(
        [str(hex_bin), "dictation", "stop", "--print"],
        capture=True,
    )
    if not transcript:
        raise ClientError("Hex did not detect any speech.")
    return transcript


def send_command(
    api_url: str,
    api_key: str,
    text: str,
    conversation: str,
) -> str:
    body = json.dumps(
        {"text": text, "conversation": conversation},
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(
        api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=130) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("detail", exc.reason)
        except (json.JSONDecodeError, AttributeError):
            detail = exc.reason
        raise ClientError(f"Server returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ClientError(f"Could not reach the control server: {exc.reason}") from exc

    answer = payload.get("text")
    if not isinstance(answer, str) or not answer.strip():
        raise ClientError("The control server returned no response text.")
    return answer.strip()


def fetch_history(
    api_url: str,
    api_key: str,
    conversation: str,
    limit: int,
) -> list[dict[str, str]]:
    history_url = api_url.rsplit("/", 1)[0] + "/history?" + urllib.parse.urlencode(
        {"conversation": conversation, "limit": limit}
    )
    request = urllib.request.Request(
        history_url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise ClientError(f"Could not load chat history: {exc}") from exc
    items = payload.get("items", [])
    return items if isinstance(items, list) else []


def print_history(items: list[dict[str, str]]) -> None:
    if not items:
        print("No previous messages in this conversation.")
        return
    print("\nPrevious messages:")
    for item in items:
        print(f"You: {item.get('user', '')}")
        print(f"Hermes: {item.get('assistant', '')}\n")


def speak(text: str) -> None:
    run_command(["say", text])


def interact(args: argparse.Namespace, api_key: str) -> None:
    ensure_hex(args.hex_bin)
    try:
        print_history(
            fetch_history(
                args.api_url,
                api_key,
                args.conversation,
                args.history_limit,
            )
        )
    except ClientError as exc:
        print(f"Warning: {exc}", file=sys.stderr)
    print("Ready. Press Enter to speak, or type q then Enter to quit.")
    while True:
        try:
            action = input("\n[Enter = speak] ").strip().lower()
            if action in {"q", "quit", "exit"}:
                return
            transcript = record_with_hex(args.hex_bin)
            print(f"You: {transcript}")
            answer = send_command(
                args.api_url,
                api_key,
                transcript,
                args.conversation,
            )
            print(f"Hermes: {answer}")
            if not args.no_speak:
                speak(answer)
        except ClientError as exc:
            print(f"Error: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nStopped.")
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default=os.environ.get("CONTROL_API_URL", DEFAULT_API_URL),
    )
    parser.add_argument(
        "--conversation",
        default=os.environ.get("VOICE_CONVERSATION", DEFAULT_CONVERSATION),
    )
    parser.add_argument(
        "--hex-bin",
        type=Path,
        default=Path(os.environ.get("HEX_BIN", DEFAULT_HEX_BIN)),
    )
    parser.add_argument("--no-speak", action="store_true")
    parser.add_argument("--history-limit", type=int, default=50)
    parser.add_argument(
        "--text",
        help="Send text directly instead of starting the push-to-talk loop.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        api_key = read_api_key()
        if args.text:
            answer = send_command(
                args.api_url,
                api_key,
                args.text,
                args.conversation,
            )
            print(answer)
            if not args.no_speak:
                speak(answer)
        else:
            interact(args, api_key)
    except ClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
