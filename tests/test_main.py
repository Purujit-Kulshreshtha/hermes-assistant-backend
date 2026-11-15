import httpx
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Response

from app.main import create_app, extract_final_text


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTROL_API_KEY", "control-test-key")
    monkeypatch.setenv("HERMES_API_KEY", "hermes-test-key")


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
    assert response.json() == {
        "text": "No boards.",
        "response_id": "resp_123",
        "conversation": "voice-main",
    }


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
