import hmac
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
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

    return app


app = create_app()
