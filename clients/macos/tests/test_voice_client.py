import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


CLIENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIR))

import voice_client  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class VoiceClientTests(unittest.TestCase):
    def test_environment_key_takes_precedence(self):
        with patch.dict("os.environ", {"CONTROL_API_KEY": "test-key"}):
            self.assertEqual(voice_client.read_api_key(), "test-key")

    @patch("voice_client.urllib.request.urlopen")
    def test_send_command_returns_only_text(self, urlopen):
        urlopen.return_value = FakeResponse(
            json.dumps({"text": "Created the task.", "response_id": "resp_1"}).encode()
        )

        result = voice_client.send_command(
            "https://example.test/command",
            "secret",
            "Create a task",
            "voice-main",
        )

        self.assertEqual(result, "Created the task.")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(
            json.loads(request.data),
            {"text": "Create a task", "conversation": "voice-main"},
        )

    @patch("voice_client.run_command")
    def test_record_with_hex(self, run_command):
        run_command.side_effect = ["", "Buy paint"]
        with patch("builtins.input", return_value=""):
            result = voice_client.record_with_hex(Path("/Applications/Hex.app/hex"))
        self.assertEqual(result, "Buy paint")

    @patch("voice_client.urllib.request.urlopen")
    def test_fetch_history(self, urlopen):
        urlopen.return_value = FakeResponse(
            json.dumps(
                {
                    "conversation": "voice-main",
                    "items": [
                        {
                            "user": "Create a task",
                            "assistant": "Created it.",
                            "response_id": "resp_1",
                            "created_at": "2026-11-15T12:00:00Z",
                        }
                    ],
                }
            ).encode()
        )

        items = voice_client.fetch_history(
            "https://example.test/command", "secret", "voice-main", 50
        )

        self.assertEqual(items[0]["assistant"], "Created it.")
        request = urlopen.call_args.args[0]
        self.assertIn("/history?", request.full_url)
        self.assertIn("conversation=voice-main", request.full_url)


if __name__ == "__main__":
    unittest.main()
