import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import receiver


class ExtractChatIdTests(unittest.TestCase):
    def test_message_chat(self):
        self.assertEqual(
            receiver.extract_chat_id({"message": {"chat": {"id": 123}}}),
            "123",
        )

    def test_callback_query_chat(self):
        self.assertEqual(
            receiver.extract_chat_id(
                {"callback_query": {"message": {"chat": {"id": -1001}}}}
            ),
            "-1001",
        )

    def test_unknown_update_has_no_chat(self):
        self.assertIsNone(receiver.extract_chat_id({"poll": {"id": "x"}}))


class ConfigTests(unittest.TestCase):
    def test_load_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"enabled": false}', encoding="utf-8")
            self.assertEqual(receiver.load_config(str(path)), {"enabled": False})

    def test_invalid_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(receiver.ReceiverError):
                receiver.load_config(str(path))


class DispatchTests(unittest.TestCase):
    def test_dispatch_envelope(self):
        captured = {}

        def fake_http_json(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["body"] = kwargs.get("body")
            return 204, None

        client = receiver.GitHubDispatchClient(
            token="token",
            repository="owner/repo",
            event_type="telegram_update",
        )
        with patch("receiver.http_json", side_effect=fake_http_json):
            client.dispatch({"update_id": 42, "message": {"chat": {"id": 7}, "text": "hi"}})

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], "https://api.github.com/repos/owner/repo/dispatches")
        self.assertEqual(captured["body"]["event_type"], "telegram_update")
        payload = captured["body"]["client_payload"]
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["update_id"], 42)
        self.assertEqual(payload["chat_id"], "7")
        self.assertEqual(payload["update"]["message"]["text"], "hi")

    def test_missing_update_id_rejected(self):
        client = receiver.GitHubDispatchClient("token", "owner/repo", "telegram_update")
        with self.assertRaises(receiver.ReceiverError):
            client.dispatch({"message": {}})


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_disabled_check_does_not_require_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"enabled": false}', encoding="utf-8")
            args = type("Args", (), {"config": str(path)})()
            self.assertEqual(receiver.command_check(args), 0)

    def test_runtime_requires_dispatch_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "consumer_repository": "owner/repo",
                        "event_type": "telegram_update",
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "TELEGRAM_BOT_TOKEN": "bot-token",
                "TELEGRAM_CHAT_ID": "123",
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(receiver.ReceiverError):
                    receiver.Runtime.from_environment(str(path))


if __name__ == "__main__":
    unittest.main()
