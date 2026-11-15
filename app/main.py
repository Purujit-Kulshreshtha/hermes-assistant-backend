import hmac
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field


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


def create_app(transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = Settings()
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

        return CommandResponse(
            text=final_text,
            response_id=payload["id"],
            conversation=body.conversation,
        )

    return app


app = create_app()
