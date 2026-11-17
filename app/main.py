import asyncio
import hmac
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
import uuid
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.board import (
    BoardDocument,
    BoardState,
    clear_board,
    initialize_board_storage,
    load_board,
    save_board,
)
from app.task_cache import initialize_task_cache


DEFAULT_CONVERSATION = "voice-main"


class Settings:
    def __init__(self) -> None:
        self.control_api_key = os.environ.get("CONTROL_API_KEY", "")
        self.hermes_api_key = os.environ.get("HERMES_API_KEY", "")
        self.hermes_url = os.environ.get(
            "HERMES_URL",
            "http://127.0.0.1:8642/p/voice/v1/responses",
        )
        self.hermes_model = os.environ.get("HERMES_MODEL", "voice")
        self.hermes_session_generation = os.environ.get(
            "HERMES_SESSION_GENERATION", "1"
        ).strip()
        self.opentodo_webhook_secret = os.environ.get("OPENTODO_WEBHOOK_SECRET", "")
        self.hex_bin = os.environ.get("HEX_BIN", "hex")
        self.ffmpeg_bin = os.environ.get("FFMPEG_BIN", "ffmpeg")
        self.request_timeout = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "120"))
        self.history_db_path = Path(
            os.environ.get("HISTORY_DB_PATH", "data/history.db")
        )
        self.voice_temp_dir = Path(os.environ.get(
            "VOICE_TEMP_DIR", str(self.history_db_path.parent / "voice")
        ))
        self.voice_max_bytes = int(os.environ.get(
            "VOICE_MAX_BYTES", str(50 * 1024 * 1024)
        ))

        if not self.control_api_key:
            raise RuntimeError("CONTROL_API_KEY is required")
        if not self.hermes_api_key:
            raise RuntimeError("HERMES_API_KEY is required")
        if not self.hermes_session_generation or len(self.hermes_session_generation) > 40:
            raise RuntimeError("HERMES_SESSION_GENERATION must be 1-40 characters")


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation: str | None = Field(default=None, min_length=1, max_length=100)


class CommandResponse(BaseModel):
    text: str
    response_id: str
    conversation: str | None = None
    created_at: str


class HistoryItem(BaseModel):
    user: str
    assistant: str
    response_id: str
    created_at: str


class HistoryResponse(BaseModel):
    conversation: str
    items: list[HistoryItem]


class HealthResponse(BaseModel):
    status: str = "ok"


class JobAccepted(BaseModel):
    id: str
    status: str = "queued"
    acknowledgement: str | None = None


class JobResponse(BaseModel):
    id: str
    status: str
    text: str
    conversation: str
    response: str | None = None
    acknowledgement: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class NotificationItem(BaseModel):
    cursor: int
    id: str
    event: str
    message: str
    task_title: str | None = None
    task_id: str | None = None
    url: str | None = None
    created_at: int


class NotificationResponse(BaseModel):
    items: list[NotificationItem]
    cursor: int


class VoiceSessionRequest(BaseModel):
    mime_type: Literal[
        "audio/webm", "audio/webm;codecs=opus", "audio/ogg",
        "audio/ogg;codecs=opus", "audio/mp4", "audio/wav",
    ]


class VoiceSessionResponse(BaseModel):
    id: str
    status: str


class VoiceTranscriptionResponse(BaseModel):
    id: str
    status: str
    transcript: str


class AppSettings(BaseModel):
    wake_word: str = Field(default="Nancy", min_length=1, max_length=40)
    keyboard_trigger: Literal["rightOption", "leftOption", "disabled"] = "rightOption"
    tts_voice: str = Field(default="af_heart", min_length=1, max_length=40)
    tts_speed: float = Field(default=1.0, ge=0.6, le=1.5)
    end_silence_seconds: float = Field(default=1.4, ge=0.5, le=3.0)
    acknowledgement_phrases: list[str] = Field(
        default_factory=lambda: [
            "Got it.",
            "Working on it.",
            "I'll bring that up.",
            "Just one second.",
            "Let me check.",
        ],
        min_length=1,
        max_length=20,
    )
    activation_phrases: list[str] = Field(
        default_factory=lambda: ["Hmm?", "Yes?", "Go on.", "Ready."],
        min_length=1,
        max_length=20,
    )
    stop_phrases: list[str] = Field(
        default_factory=lambda: [
            "That'll be all",
            "That will be all",
            "That's all",
            "Stop listening",
            "Goodbye Nancy",
        ],
        min_length=1,
        max_length=20,
    )
    silence_phrases: list[str] = Field(
        default_factory=lambda: [
            "Stop talking",
            "Be quiet",
            "Quiet",
            "Enough",
        ],
        min_length=1,
        max_length=20,
    )


def extract_final_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    if not parts:
        raise ValueError("Hermes returned no assistant text")
    return "\n".join(parts)


def hermes_conversation_id(conversation: str, generation: str) -> str:
    """Version the upstream runtime session without changing Nancy's UI history."""
    return f"{conversation}::runtime-{generation}"


ACTION_WORDS = re.compile(
    r"\b(add|archive|assign|cancel|change|complete|create|delete|edit|email|"
    r"mark|move|postpone|remove|rename|remind|reschedule|schedule|send|set|"
    r"share|update)\b",
    re.IGNORECASE,
)


def is_action_request(text: str) -> bool:
    return bool(ACTION_WORDS.search(text))


def concise_action_result(request: str, answer: str) -> str:
    if not is_action_request(request):
        return answer
    failure_markers = (
        "can't", "cannot", "couldn't", "could not", "failed", "failure",
        "unable", "not allowed", "not permitted", "need more", "blocked",
        "error", "nothing was", "wasn't able", "was not able",
    )
    if any(marker in answer.casefold() for marker in failure_markers):
        return answer
    return "Done."


def initialize_history(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation TEXT NOT NULL,
                user_text TEXT NOT NULL,
                assistant_text TEXT NOT NULL,
                response_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_sessions (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                total_bytes INTEGER NOT NULL DEFAULT 0,
                transcript TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_chunks (
                session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                PRIMARY KEY (session_id, sequence),
                FOREIGN KEY (session_id) REFERENCES voice_sessions(id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                conversation TEXT NOT NULL,
                user_text TEXT NOT NULL,
                assistant_text TEXT,
                acknowledgement TEXT,
                response_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        job_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "acknowledgement" not in job_columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN acknowledgement TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO app_settings (id, value) VALUES (1, ?)",
            (AppSettings().model_dump_json(),),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id TEXT NOT NULL UNIQUE,
                event TEXT NOT NULL,
                message TEXT NOT NULL,
                task_title TEXT,
                task_id TEXT,
                url TEXT,
                created_at INTEGER NOT NULL,
                received_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS interactions_conversation_id
            ON interactions (conversation, id)
            """
        )
    initialize_board_storage(path)
    initialize_task_cache(path)


def save_interaction(
    path: Path,
    conversation: str,
    user_text: str,
    assistant_text: str,
    response_id: str,
    created_at: str,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO interactions
                (conversation, user_text, assistant_text, response_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation, user_text, assistant_text, response_id, created_at),
        )


def load_history(path: Path, conversation: str, limit: int) -> list[HistoryItem]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT user_text, assistant_text, response_id, created_at
            FROM (
                SELECT id, user_text, assistant_text, response_id, created_at
                FROM interactions
                WHERE conversation = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (conversation, limit),
        ).fetchall()
    return [
        HistoryItem(
            user=row[0],
            assistant=row[1],
            response_id=row[2],
            created_at=row[3],
        )
        for row in rows
    ]


def load_app_settings(path: Path) -> AppSettings:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE id = 1"
        ).fetchone()
    return AppSettings.model_validate_json(row[0]) if row else AppSettings()


def save_app_settings(path: Path, value: AppSettings) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO app_settings (id, value) VALUES (1, ?)",
            (value.model_dump_json(),),
        )


def save_notification(path: Path, payload: dict[str, Any]) -> None:
    task = payload.get("task") or {}
    message = payload.get("message") or payload.get("body") or "A reminder is due"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO notification_events
                (delivery_id, event, message, task_title, task_id, url,
                 created_at, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["id"], payload.get("event", "reminder"), message,
                task.get("title"), task.get("id"), payload.get("url"),
                int(payload.get("createdAt") or time.time() * 1000),
                datetime.now(UTC).isoformat(),
            ),
        )


def load_notifications(path: Path, after: int, limit: int = 100) -> NotificationResponse:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT cursor, delivery_id, event, message, task_title, task_id,
                   url, created_at
            FROM notification_events
            WHERE cursor > ?
            ORDER BY cursor ASC
            LIMIT ?
            """,
            (after, limit),
        ).fetchall()
    items = [
        NotificationItem(
            cursor=row[0], id=row[1], event=row[2], message=row[3],
            task_title=row[4], task_id=row[5], url=row[6], created_at=row[7],
        )
        for row in rows
    ]
    return NotificationResponse(items=items, cursor=items[-1].cursor if items else after)


def valid_opentodo_signature(
    secret: str, timestamp: str, body: bytes, signature: str,
    tolerance_seconds: int = 300,
) -> bool:
    try:
        fresh = abs(time.time() - int(timestamp)) <= tolerance_seconds
    except (TypeError, ValueError):
        return False
    expected = "v1=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return fresh and hmac.compare_digest(expected, signature)


def create_voice_session(path: Path, temp_dir: Path, mime_type: str) -> VoiceSessionResponse:
    session_id = uuid.uuid4().hex
    now = time.time()
    (temp_dir / session_id).mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO voice_sessions (id, status, mime_type, created_at, updated_at)
            VALUES (?, 'recording', ?, ?, ?)
            """,
            (session_id, mime_type, now, now),
        )
    return VoiceSessionResponse(id=session_id, status="recording")


def cleanup_voice_sessions(path: Path, temp_dir: Path, max_age_seconds: int = 86400) -> None:
    cutoff = time.time() - max_age_seconds
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT id FROM voice_sessions WHERE updated_at < ?", (cutoff,)
        ).fetchall()
        for (session_id,) in rows:
            shutil.rmtree(temp_dir / session_id, ignore_errors=True)
            connection.execute(
                "DELETE FROM voice_chunks WHERE session_id = ?", (session_id,)
            )
        connection.execute("DELETE FROM voice_sessions WHERE updated_at < ?", (cutoff,))


def save_voice_chunk(
    path: Path, temp_dir: Path, session_id: str, sequence: int,
    body: bytes, max_bytes: int,
) -> None:
    if not body or len(body) > 2 * 1024 * 1024:
        raise ValueError("Voice chunks must be between 1 byte and 2 MiB")
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT status, total_bytes FROM voice_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            raise KeyError("Voice session not found")
        if row[0] != "recording":
            raise RuntimeError("Voice session is no longer recording")
        previous = connection.execute(
            "SELECT size FROM voice_chunks WHERE session_id = ? AND sequence = ?",
            (session_id, sequence),
        ).fetchone()
        new_total = row[1] - (previous[0] if previous else 0) + len(body)
        if new_total > max_bytes:
            raise OverflowError("Voice recording is too large")
        chunk_path = temp_dir / session_id / f"{sequence:06d}.chunk"
        chunk_path.write_bytes(body)
        connection.execute(
            """
            INSERT OR REPLACE INTO voice_chunks (session_id, sequence, path, size)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, sequence, str(chunk_path), len(body)),
        )
        connection.execute(
            "UPDATE voice_sessions SET total_bytes = ?, updated_at = ? WHERE id = ?",
            (new_total, time.time(), session_id),
        )


def transcribe_voice_session(
    path: Path, temp_dir: Path, session_id: str, ffmpeg_bin: str, hex_bin: str,
) -> str:
    with sqlite3.connect(path) as connection:
        session = connection.execute(
            "SELECT status, mime_type, transcript FROM voice_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not session:
            raise KeyError("Voice session not found")
        if session[0] == "completed" and session[2]:
            return session[2]
        if session[0] != "recording":
            raise RuntimeError("Voice session cannot be finalized")
        chunks = connection.execute(
            """
            SELECT sequence, path FROM voice_chunks
            WHERE session_id = ? ORDER BY sequence
            """,
            (session_id,),
        ).fetchall()
        if not chunks or [row[0] for row in chunks] != list(range(len(chunks))):
            raise ValueError("Voice recording has missing chunks")
        connection.execute(
            "UPDATE voice_sessions SET status = 'processing', updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
    directory = temp_dir / session_id
    extension = {
        "audio/ogg": "ogg", "audio/ogg;codecs=opus": "ogg",
        "audio/mp4": "mp4", "audio/wav": "wav",
    }.get(session[1], "webm")
    joined = directory / f"recording.{extension}"
    normalized = directory / "recording.wav"
    try:
        with joined.open("wb") as output:
            for _, chunk_path in chunks:
                output.write(Path(chunk_path).read_bytes())
        subprocess.run(
            [ffmpeg_bin, "-nostdin", "-y", "-i", str(joined), "-ar", "16000",
             "-ac", "1", str(normalized)],
            check=True, capture_output=True, timeout=120,
        )
        result = subprocess.run(
            [hex_bin, "transcribe", str(normalized)],
            check=True, capture_output=True, text=True, timeout=300,
        )
        transcript = result.stdout.strip()
        if not transcript:
            raise ValueError("Hex returned an empty transcript")
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                UPDATE voice_sessions SET status = 'completed', transcript = ?,
                    updated_at = ? WHERE id = ?
                """,
                (transcript, time.time(), session_id),
            )
            connection.execute("DELETE FROM voice_chunks WHERE session_id = ?", (session_id,))
        for item in directory.iterdir():
            item.unlink(missing_ok=True)
        directory.rmdir()
        return transcript
    except Exception as exc:
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE voice_sessions SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (str(exc)[:1000], time.time(), session_id),
            )
        raise


def create_job(path: Path, body: CommandRequest) -> JobAccepted:
    job_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO jobs
                (id, status, conversation, user_text, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?, ?)
            """,
            (job_id, body.conversation or DEFAULT_CONVERSATION, body.text, now, now),
        )
    return JobAccepted(id=job_id)


def load_job(path: Path, job_id: str) -> JobResponse | None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT id, status, user_text, conversation, assistant_text,
                   acknowledgement, error, created_at, updated_at
            FROM jobs WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return None
    return JobResponse(
        id=row[0], status=row[1], text=row[2], conversation=row[3],
        response=row[4], acknowledgement=row[5], error=row[6],
        created_at=row[7], updated_at=row[8]
    )


HERMES_PROGRESS_INSTRUCTIONS = """
Before calling any tool or beginning substantive work, emit one brief user-facing
commentary sentence stating what you understood and what you are about to do.
Make it specific to this request, not a generic acknowledgement. Then continue the
same turn and complete the work. Do not claim success until the work is complete.
""".strip()


async def stream_hermes_job(
    app: FastAPI, settings: Settings, job: JobResponse, job_id: str,
) -> dict[str, Any]:
    completed: dict[str, Any] | None = None
    final_text: str | None = None
    event_name = ""
    data_lines: list[str] = []

    def handle_event(name: str, data: str) -> None:
        nonlocal completed, final_text
        if not data or data == "[DONE]":
            return
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return
        event_type = event.get("type") or name
        progress = ""
        if event_type == "message.interim" and event.get("text"):
            progress = str(event["text"]).strip()
        elif event_type in {"response.output_item.added", "response.output_item.done"}:
            item = event.get("item") or {}
            if item.get("type") == "message" and item.get("phase") == "commentary":
                progress = "\n".join(
                    str(part.get("text", ""))
                    for part in item.get("content", [])
                    if part.get("type") == "output_text" and part.get("text")
                ).strip()
        if progress:
            with sqlite3.connect(settings.history_db_path) as connection:
                connection.execute(
                    """
                    UPDATE jobs SET acknowledgement = ?, updated_at = ?
                    WHERE id = ? AND acknowledgement IS NULL
                    """,
                    (progress[:500], datetime.now(UTC).isoformat(), job_id),
                )
        elif event_type == "response.output_text.done" and event.get("text"):
            final_text = str(event["text"])
        elif event_type == "response.completed":
            completed = event.get("response") or event
        elif event_type in {"response.failed", "error"}:
            detail = event.get("error") or event.get("message") or "Hermes stream failed"
            raise ValueError(str(detail))

    async with app.state.hermes_client.stream(
        "POST",
        settings.hermes_url,
        headers={"Authorization": f"Bearer {settings.hermes_api_key}"},
        json={
            "model": settings.hermes_model,
            "input": job.text,
            "conversation": hermes_conversation_id(
                job.conversation, settings.hermes_session_generation
            ),
            "instructions": HERMES_PROGRESS_INSTRUCTIONS,
            "stream": True,
        },
    ) as response:
        response.raise_for_status()
        if "text/event-stream" not in response.headers.get("content-type", ""):
            return json.loads((await response.aread()).decode())
        async for line in response.aiter_lines():
            if not line:
                handle_event(event_name, "\n".join(data_lines))
                event_name = ""
                data_lines = []
            elif line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        handle_event(event_name, "\n".join(data_lines))

    if completed:
        return completed
    if final_text:
        return {
            "id": f"stream_{job_id}",
            "status": "completed",
            "output": [{
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": final_text}],
            }],
        }
    raise ValueError("Hermes stream ended without a completed response")


async def process_job(app: FastAPI, job_id: str) -> None:
    settings: Settings = app.state.settings
    job = load_job(settings.history_db_path, job_id)
    if not job:
        return
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(settings.history_db_path) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (now, job_id),
        )
    try:
        payload = await stream_hermes_job(app, settings, job, job_id)
        if payload.get("status") != "completed":
            raise ValueError(f"Unexpected Hermes status: {payload.get('status')}")
        answer = concise_action_result(job.text, extract_final_text(payload))
        now = datetime.now(UTC).isoformat()
        save_interaction(
            settings.history_db_path, job.conversation, job.text, answer,
            payload["id"], now,
        )
        with sqlite3.connect(settings.history_db_path) as connection:
            connection.execute(
                """
                UPDATE jobs SET status = 'completed', assistant_text = ?,
                    response_id = ?, updated_at = ? WHERE id = ?
                """,
                (answer, payload["id"], now, job_id),
            )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        with sqlite3.connect(settings.history_db_path) as connection:
            connection.execute(
                "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (str(exc), datetime.now(UTC).isoformat(), job_id),
            )


def create_app(transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = Settings()
        initialize_history(settings.history_db_path)
        app.state.settings = settings
        app.state.hermes_client = httpx.AsyncClient(
            timeout=settings.request_timeout,
            transport=transport,
        )
        settings.voice_temp_dir.mkdir(parents=True, exist_ok=True)
        cleanup_voice_sessions(settings.history_db_path, settings.voice_temp_dir)
        app.state.transcription_lock = asyncio.Semaphore(1)
        yield
        await app.state.hermes_client.aclose()

    app = FastAPI(
        title="Hermes Voice Control API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    def authenticate(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        expected = request.app.state.settings.control_api_key
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ")
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post(
        "/command",
        response_model=CommandResponse,
        dependencies=[Depends(authenticate)],
    )
    async def command(body: CommandRequest, request: Request) -> CommandResponse:
        settings: Settings = request.app.state.settings
        hermes_body: dict[str, Any] = {
            "model": settings.hermes_model,
            "input": body.text,
        }
        if body.conversation:
            hermes_body["conversation"] = hermes_conversation_id(
                body.conversation, settings.hermes_session_generation
            )

        try:
            response = await request.app.state.hermes_client.post(
                settings.hermes_url,
                headers={
                    "Authorization": f"Bearer {settings.hermes_api_key}",
                    "Content-Type": "application/json",
                },
                json=hermes_body,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "completed":
                raise ValueError(f"Unexpected Hermes status: {payload.get('status')}")
            final_text = extract_final_text(payload)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Hermes request failed",
            ) from exc

        created_at = datetime.now(UTC).isoformat()
        conversation = body.conversation or "default"
        save_interaction(
            settings.history_db_path,
            conversation,
            body.text,
            final_text,
            payload["id"],
            created_at,
        )
        return CommandResponse(
            text=final_text,
            response_id=payload["id"],
            conversation=body.conversation,
            created_at=created_at,
        )

    @app.get(
        "/history",
        response_model=HistoryResponse,
        dependencies=[Depends(authenticate)],
    )
    async def history(
        request: Request,
        conversation: str = DEFAULT_CONVERSATION,
        limit: int = 100,
    ) -> HistoryResponse:
        if not 1 <= limit <= 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        settings: Settings = request.app.state.settings
        return HistoryResponse(
            conversation=conversation,
            items=load_history(settings.history_db_path, conversation, limit),
        )

    @app.post(
        "/commands",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(authenticate)],
    )
    async def commands(
        body: CommandRequest,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> JobAccepted:
        accepted = create_job(request.app.state.settings.history_db_path, body)
        background_tasks.add_task(process_job, request.app, accepted.id)
        return accepted

    @app.get(
        "/commands/{job_id}",
        response_model=JobResponse,
        dependencies=[Depends(authenticate)],
    )
    async def command_status(job_id: str, request: Request) -> JobResponse:
        job = load_job(request.app.state.settings.history_db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Command not found")
        return job

    @app.post(
        "/voice/sessions",
        response_model=VoiceSessionResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(authenticate)],
    )
    async def start_voice_session(
        body: VoiceSessionRequest, request: Request,
    ) -> VoiceSessionResponse:
        settings: Settings = request.app.state.settings
        return create_voice_session(
            settings.history_db_path, settings.voice_temp_dir, body.mime_type
        )

    @app.put(
        "/voice/sessions/{session_id}/chunks/{sequence}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(authenticate)],
    )
    async def upload_voice_chunk(
        session_id: str, sequence: int, request: Request,
    ) -> None:
        if sequence < 0 or sequence > 9999:
            raise HTTPException(status_code=422, detail="Invalid chunk sequence")
        content_length = int(request.headers.get("Content-Length", "0") or 0)
        if content_length > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Voice chunk is too large")
        body = await request.body()
        settings: Settings = request.app.state.settings
        try:
            save_voice_chunk(
                settings.history_db_path, settings.voice_temp_dir, session_id,
                sequence, body, settings.voice_max_bytes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc

    @app.post(
        "/voice/sessions/{session_id}/finalize",
        response_model=VoiceTranscriptionResponse,
        dependencies=[Depends(authenticate)],
    )
    async def finalize_voice_session(
        session_id: str, request: Request,
    ) -> VoiceTranscriptionResponse:
        settings: Settings = request.app.state.settings
        try:
            async with request.app.state.transcription_lock:
                transcript = await asyncio.to_thread(
                    transcribe_voice_session,
                    settings.history_db_path, settings.voice_temp_dir, session_id,
                    settings.ffmpeg_bin, settings.hex_bin,
                )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise HTTPException(status_code=502, detail="Transcription failed") from exc
        return VoiceTranscriptionResponse(
            id=session_id, status="completed", transcript=transcript
        )

    @app.delete(
        "/voice/sessions/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(authenticate)],
    )
    async def cancel_voice_session(session_id: str, request: Request) -> None:
        settings: Settings = request.app.state.settings
        with sqlite3.connect(settings.history_db_path) as connection:
            row = connection.execute(
                "SELECT status FROM voice_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Voice session not found")
            if row[0] == "processing":
                raise HTTPException(status_code=409, detail="Transcription is processing")
            connection.execute("DELETE FROM voice_chunks WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM voice_sessions WHERE id = ?", (session_id,))
        shutil.rmtree(settings.voice_temp_dir / session_id, ignore_errors=True)

    @app.get(
        "/settings",
        response_model=AppSettings,
        dependencies=[Depends(authenticate)],
    )
    async def get_settings(request: Request) -> AppSettings:
        return load_app_settings(request.app.state.settings.history_db_path)

    @app.put(
        "/settings",
        response_model=AppSettings,
        dependencies=[Depends(authenticate)],
    )
    async def put_settings(value: AppSettings, request: Request) -> AppSettings:
        value.wake_word = value.wake_word.strip()
        value.acknowledgement_phrases = [
            phrase.strip() for phrase in value.acknowledgement_phrases if phrase.strip()
        ]
        value.activation_phrases = [
            phrase.strip() for phrase in value.activation_phrases if phrase.strip()
        ]
        value.stop_phrases = [
            phrase.strip() for phrase in value.stop_phrases if phrase.strip()
        ]
        value.silence_phrases = [
            phrase.strip() for phrase in value.silence_phrases if phrase.strip()
        ]
        if not all((
            value.wake_word,
            value.acknowledgement_phrases,
            value.activation_phrases,
            value.stop_phrases,
            value.silence_phrases,
        )):
            raise HTTPException(status_code=422, detail="Settings cannot be empty")
        save_app_settings(request.app.state.settings.history_db_path, value)
        return value

    @app.post("/webhooks/opentodo", status_code=status.HTTP_202_ACCEPTED)
    async def opentodo_webhook(request: Request) -> dict[str, bool]:
        settings: Settings = request.app.state.settings
        secret = settings.opentodo_webhook_secret
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenTodo webhook is not configured",
            )
        body = await request.body()
        timestamp = request.headers.get("X-OpenTodo-Timestamp", "")
        signature = request.headers.get("X-OpenTodo-Signature", "")
        if not valid_opentodo_signature(secret, timestamp, body, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid webhook body") from exc
        if payload.get("event") in {"reminder", "routine"}:
            save_notification(settings.history_db_path, payload)
        return {"accepted": True}

    @app.get(
        "/notifications",
        response_model=NotificationResponse,
        dependencies=[Depends(authenticate)],
    )
    async def notifications(
        request: Request, after: int = 0, limit: int = 100,
    ) -> NotificationResponse:
        if after < 0 or not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="Invalid notification cursor")
        return load_notifications(
            request.app.state.settings.history_db_path, after, limit
        )

    @app.get(
        "/board",
        response_model=BoardState,
        dependencies=[Depends(authenticate)],
    )
    async def get_board(
        request: Request, conversation: str = DEFAULT_CONVERSATION,
    ) -> BoardState:
        value = load_board(request.app.state.settings.history_db_path, conversation)
        if not value:
            raise HTTPException(status_code=404, detail="No visual board yet")
        return value

    @app.put(
        "/board",
        response_model=BoardState,
        dependencies=[Depends(authenticate)],
    )
    async def put_board(value: BoardDocument, request: Request) -> BoardState:
        return save_board(request.app.state.settings.history_db_path, value)

    @app.delete(
        "/board",
        response_model=BoardState,
        dependencies=[Depends(authenticate)],
    )
    async def delete_board(
        request: Request, conversation: str = DEFAULT_CONVERSATION,
    ) -> BoardState:
        return clear_board(request.app.state.settings.history_db_path, conversation)

    @app.get(
        "/board/events",
        dependencies=[Depends(authenticate)],
    )
    async def board_events(
        request: Request,
        conversation: str = DEFAULT_CONVERSATION,
        after: int = 0,
    ) -> StreamingResponse:
        if after < 0:
            raise HTTPException(status_code=422, detail="Invalid board revision")

        async def stream() -> AsyncIterator[str]:
            revision = after
            keepalive_at = time.monotonic()
            while not await request.is_disconnected():
                value = load_board(
                    request.app.state.settings.history_db_path, conversation
                )
                if value and value.revision > revision:
                    revision = value.revision
                    yield f"event: board\ndata: {value.model_dump_json()}\n\n"
                    keepalive_at = time.monotonic()
                elif time.monotonic() - keepalive_at >= 15:
                    yield ": keepalive\n\n"
                    keepalive_at = time.monotonic()
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


app = create_app()
