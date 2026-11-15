import httpx
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Response

from app.main import create_app, extract_final_text


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("CONTROL_API_KEY", "control-test-key")
    monkeypatch.setenv("HERMES_API_KEY", "hermes-test-key")
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.db"))


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
