import hashlib
import hmac
import json
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Response

import app.main as main_module
from app.main import create_app, extract_final_text


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("CONTROL_API_KEY", "control-test-key")
    monkeypatch.setenv("HERMES_API_KEY", "hermes-test-key")
    monkeypatch.setenv("OPENTODO_WEBHOOK_SECRET", "whsec_test-secret")
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.db"))
    monkeypatch.setenv("VOICE_TEMP_DIR", str(tmp_path / "voice"))


def test_extract_final_text_ignores_tool_calls() -> None:
    payload = {
        "output": [
            {"type": "function_call", "name": "some_tool"},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Done."}],
            },
        ]
    }
    assert extract_final_text(payload) == "Done."


@pytest.mark.asyncio
async def test_opentodo_reminder_webhook_is_verified_and_deduplicated() -> None:
    app = create_app(MockTransport(lambda request: Response(500)))
    payload = {
        "version": 1,
        "id": "delivery-1",
        "event": "reminder",
        "createdAt": 1760000000000,
        "title": "OpenTodo",
        "message": "A reminder is due",
        "url": "https://todo.example/?task=task-1",
        "task": {"id": "task-1", "title": "Drink water"},
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = "v1=" + hmac.new(
        b"whsec_test-secret", timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    webhook_headers = {
        "X-OpenTodo-Timestamp": timestamp,
        "X-OpenTodo-Signature": signature,
        "Content-Type": "application/json",
    }
    auth = {"Authorization": "Bearer control-test-key"}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/webhooks/opentodo", content=body, headers=webhook_headers
            )
            duplicate = await client.post(
                "/webhooks/opentodo", content=body, headers=webhook_headers
            )
            notifications = await client.get("/notifications", headers=auth)

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert len(notifications.json()["items"]) == 1
    assert notifications.json()["items"][0]["task_title"] == "Drink water"


@pytest.mark.asyncio
async def test_opentodo_webhook_rejects_bad_signature() -> None:
    app = create_app(MockTransport(lambda request: Response(500)))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhooks/opentodo",
                content=b"{}",
                headers={
                    "X-OpenTodo-Timestamp": str(int(time.time())),
                    "X-OpenTodo-Signature": "v1=wrong",
                },
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_opentodo_routine_notice_is_queued() -> None:
    app = create_app(MockTransport(lambda request: Response(500)))
    payload = {
        "version": 1,
        "id": "routine-delivery-1",
        "event": "routine",
        "createdAt": 1760000000000,
        "title": "OpenTodo",
        "message": "Straighten your back and check your posture.",
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = "v1=" + hmac.new(
        b"whsec_test-secret", timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            accepted = await client.post(
                "/webhooks/opentodo",
                content=body,
                headers={
                    "X-OpenTodo-Timestamp": timestamp,
                    "X-OpenTodo-Signature": signature,
                    "Content-Type": "application/json",
                },
            )
            notifications = await client.get(
                "/notifications",
                headers={"Authorization": "Bearer control-test-key"},
            )

    assert accepted.status_code == 202
    item = notifications.json()["items"][0]
    assert item["event"] == "routine"
    assert item["message"] == "Straighten your back and check your posture."


@pytest.mark.asyncio
async def test_command_forwards_to_hermes() -> None:
    async def hermes_handler(request: httpx.Request) -> Response:
        assert request.headers["Authorization"] == "Bearer hermes-test-key"
        assert b'"input":"List my boards"' in request.content
        return Response(
            200,
            json={
                "id": "resp_123",
                "status": "completed",
                "output": [
                    {"type": "function_call", "name": "list_projects"},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "No boards."}],
                    },
                ],
            },
        )

    app = create_app(MockTransport(hermes_handler))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/command",
                headers={"Authorization": "Bearer control-test-key"},
                json={"text": "List my boards", "conversation": "voice-main"},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "No boards."
    assert payload["response_id"] == "resp_123"
    assert payload["conversation"] == "voice-main"
    assert payload["created_at"]


@pytest.mark.asyncio
async def test_command_rejects_invalid_key() -> None:
    app = create_app(MockTransport(lambda request: Response(500)))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/command",
                headers={"Authorization": "Bearer wrong"},
                json={"text": "List my boards"},
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chunked_voice_session_returns_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(arguments, **kwargs):
        if arguments[0] == "ffmpeg":
            from pathlib import Path
            Path(arguments[-1]).write_bytes(b"RIFF-fake-wave")
            return main_module.subprocess.CompletedProcess(arguments, 0, b"", b"")
        return main_module.subprocess.CompletedProcess(
            arguments, 0, stdout="Create a Home board.\n", stderr=""
        )

    monkeypatch.setattr(main_module.subprocess, "run", fake_run)
    app = create_app(MockTransport(lambda request: Response(500)))
    headers = {"Authorization": "Bearer control-test-key"}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            started = await client.post(
                "/voice/sessions", headers=headers,
                json={"mime_type": "audio/webm;codecs=opus"},
            )
            session_id = started.json()["id"]
            first = await client.put(
                f"/voice/sessions/{session_id}/chunks/0",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=b"first",
            )
            second = await client.put(
                f"/voice/sessions/{session_id}/chunks/1",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=b"second",
            )
            finalized = await client.post(
                f"/voice/sessions/{session_id}/finalize", headers=headers
            )

    assert started.status_code == 201
    assert first.status_code == 204
    assert second.status_code == 204
    assert finalized.status_code == 200
    assert finalized.json()["transcript"] == "Create a Home board."


@pytest.mark.asyncio
async def test_history_contains_completed_commands() -> None:
    async def hermes_handler(request: httpx.Request) -> Response:
        return Response(
            200,
            json={
                "id": "resp_history",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Created it."}],
                    }
                ],
            },
        )

    app = create_app(MockTransport(hermes_handler))
    headers = {"Authorization": "Bearer control-test-key"}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/command",
                headers=headers,
                json={"text": "Create it", "conversation": "voice-main"},
            )
            response = await client.get(
                "/history?conversation=voice-main", headers=headers
            )

    assert response.status_code == 200
    assert response.json()["items"][0]["user"] == "Create it"
    assert response.json()["items"][0]["assistant"] == "Created it."


@pytest.mark.asyncio
async def test_visual_board_is_validated_versioned_and_persisted() -> None:
    app = create_app(MockTransport(lambda request: Response(500)))
    headers = {"Authorization": "Bearer control-test-key"}
    document = {
        "conversation": "voice-main",
        "title": "Today",
        "layout": "grid",
        "components": [
            {
                "id": "today-heading",
                "type": "heading",
                "data": {"text": "Your day", "subtitle": "Three items"},
            },
            {
                "id": "today-tasks",
                "type": "task_list",
                "data": {
                    "title": "Tasks",
                    "tasks": [{"title": "Review the proposal", "status": "Todo"}],
                },
            },
        ],
    }
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.put("/board", headers=headers, json=document)
            second = await client.put("/board", headers=headers, json=document)
            loaded = await client.get(
                "/board?conversation=voice-main", headers=headers
            )

    assert first.status_code == 200
    assert first.json()["revision"] == 1
    assert second.json()["revision"] == 2
    assert loaded.json()["title"] == "Today"
    assert loaded.json()["components"][1]["type"] == "task_list"


@pytest.mark.asyncio
async def test_visual_board_rejects_unknown_components_and_fields() -> None:
    app = create_app(MockTransport(lambda request: Response(500)))
    headers = {"Authorization": "Bearer control-test-key"}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            unknown = await client.put(
                "/board",
                headers=headers,
                json={
                    "title": "Unsafe",
                    "components": [{"id": "raw", "type": "html", "data": {}}],
                },
            )
            extra = await client.put(
                "/board",
                headers=headers,
                json={
                    "title": "Unsafe",
                    "components": [{
                        "id": "note",
                        "type": "callout",
                        "data": {"text": "Hello", "javascript": "alert(1)"},
                    }],
                },
            )

    assert unknown.status_code == 422
    assert extra.status_code == 422


@pytest.mark.asyncio
async def test_async_command_and_settings() -> None:
    async def hermes_handler(request: httpx.Request) -> Response:
        return Response(
            200,
            json={
                "id": "resp_async",
                "status": "completed",
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done."}],
                }],
            },
        )

    app = create_app(MockTransport(hermes_handler))
    headers = {"Authorization": "Bearer control-test-key"}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            accepted = await client.post(
                "/commands",
                headers=headers,
                json={"text": "Do it", "conversation": "voice-main"},
            )
            job = await client.get(
                f"/commands/{accepted.json()['id']}", headers=headers
            )
            saved = await client.put(
                "/settings",
                headers=headers,
                json={
                    "wake_word": "Computer",
                    "keyboard_trigger": "leftOption",
                    "tts_voice": "af_bella",
                    "tts_speed": 1.1,
                    "acknowledgement_phrases": ["On it."],
                },
            )
            loaded = await client.get("/settings", headers=headers)

    assert accepted.status_code == 202
    assert job.json()["status"] == "completed"
    assert job.json()["response"] == "Done."
    assert saved.status_code == 200
    assert loaded.json()["wake_word"] == "Computer"
    assert loaded.json()["keyboard_trigger"] == "leftOption"


@pytest.mark.asyncio
async def test_pwa_is_served() -> None:
    app = create_app(MockTransport(lambda request: Response(500)))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/")
    assert response.status_code == 200
    assert "Nancy" in response.text
    assert 'id="voiceButton"' in response.text
    assert 'id="testVoice"' in response.text
    assert '/tts.js' in response.text
    assert 'id="wakeWord"' not in response.text
    assert 'id="keyboardTrigger"' not in response.text
    assert 'id="activityText"' not in response.text
