import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import receiver


class ExtractChatIdTests(unittest.TestCase):
    def test_message_chat(self):
        self.assertEqual(receiver.extract_chat_id({"message": {"chat": {"id": 123}}}), "123")

    def test_callback_query_chat(self):
        self.assertEqual(
            receiver.extract_chat_id({"callback_query": {"message": {"chat": {"id": -1001}}}}),
            "-1001",
        )

    def test_unknown_update_has_no_chat(self):
        self.assertIsNone(receiver.extract_chat_id({"poll": {"id": "x"}}))


class MessageContextTests(unittest.TestCase):
    def test_message_context(self):
        self.assertEqual(
            receiver.extract_message_context(
                {
                    "message": {
                        "message_id": 9,
                        "message_thread_id": 3,
                        "chat": {"id": 123},
                    }
                }
            ),
            (123, 9, 3),
        )

    def test_missing_message_context(self):
        self.assertEqual(receiver.extract_message_context({"poll": {}}), (None, None, None))


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


class ConsumerActionTests(unittest.TestCase):
    def test_reply_action(self):
        action = receiver.validate_consumer_action(
            "42",
            {
                "schema_version": 1,
                "event_id": "42",
                "action": "reply",
                "text": "ответ: hi",
            },
        )
        self.assertEqual(action["action"], "reply")
        self.assertEqual(action["text"], "ответ: hi")

    def test_no_reply_action(self):
        action = receiver.validate_consumer_action(
            "42",
            {"schema_version": 1, "event_id": "42", "action": "no_reply"},
        )
        self.assertEqual(action["action"], "no_reply")

    def test_event_id_mismatch_rejected(self):
        with self.assertRaises(receiver.ReceiverError):
            receiver.validate_consumer_action(
                "42",
                {"schema_version": 1, "event_id": "43", "action": "no_reply"},
            )


class RuntimeStoreTests(unittest.TestCase):
    def test_enqueue_orders_pending_ids(self):
        store = receiver.GitHubRuntimeStore("token", "owner/repo", "runtime")
        files = {
            receiver.STATE_PATH: {
                "schema_version": 1,
                "pending": ["10"],
                "updated_at": "x",
            }
        }

        def get_json(path):
            value = files.get(path)
            return dict(value) if value is not None else None

        def put_json(path, data, **kwargs):
            files[path] = json.loads(json.dumps(data))
            return True

        store.get_json = get_json
        store.put_json = put_json

        self.assertEqual(store.enqueue({"update_id": 2, "message": {}}), "queued")
        self.assertEqual(files[receiver.STATE_PATH]["pending"], ["2", "10"])

    def test_completed_update_is_not_requeued(self):
        store = receiver.GitHubRuntimeStore("token", "owner/repo", "runtime")
        store.get_json = lambda path: (
            {"schema_version": 1, "event_id": "2"}
            if path == "runtime/receipts/2.json"
            else None
        )
        self.assertEqual(store.enqueue({"update_id": 2}), "completed")


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_disabled_check_does_not_require_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"enabled": false}', encoding="utf-8")
            args = type("Args", (), {"config": str(path)})()
            self.assertEqual(receiver.command_check(args), 0)

    def test_runtime_requires_queue_token(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            consumer_dir = Path(directory) / "consumer"
            consumer_dir.mkdir()
            (consumer_dir / "consumer.py").write_text("pass", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "runtime_branch": "receiver-runtime",
                        "consumer_image": "python:3.12-slim",
                        "consumer_script": "consumer.py",
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "TELEGRAM_BOT_TOKEN": "bot-token",
                "TELEGRAM_CHAT_ID": "123",
                "RECEIVER_REPOSITORY": "owner/repo",
                "CONSUMER_DIR": str(consumer_dir),
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(receiver.ReceiverError):
                    receiver.Runtime.from_environment(str(config_path))


if __name__ == "__main__":
    unittest.main()
