import hmac
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


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
        self.opentodo_webhook_secret = os.environ.get("OPENTODO_WEBHOOK_SECRET", "")
        self.request_timeout = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "120"))
        self.history_db_path = Path(
            os.environ.get("HISTORY_DB_PATH", "data/history.db")
        )

        if not self.control_api_key:
            raise RuntimeError("CONTROL_API_KEY is required")
        if not self.hermes_api_key:
            raise RuntimeError("HERMES_API_KEY is required")


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


class JobResponse(BaseModel):
    id: str
    status: str
    text: str
    conversation: str
    response: str | None = None
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
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                conversation TEXT NOT NULL,
                user_text TEXT NOT NULL,
                assistant_text TEXT,
                response_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
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
            SELECT id, status, user_text, conversation, assistant_text, error,
                   created_at, updated_at
            FROM jobs WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return None
    return JobResponse(
        id=row[0], status=row[1], text=row[2], conversation=row[3],
        response=row[4], error=row[5], created_at=row[6], updated_at=row[7]
    )


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
        response = await app.state.hermes_client.post(
            settings.hermes_url,
            headers={"Authorization": f"Bearer {settings.hermes_api_key}"},
            json={
                "model": settings.hermes_model,
                "input": job.text,
                "conversation": job.conversation,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "completed":
            raise ValueError(f"Unexpected Hermes status: {payload.get('status')}")
        answer = extract_final_text(payload)
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
            hermes_body["conversation"] = body.conversation

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
        if payload.get("event") == "reminder":
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

    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


app = create_app()
