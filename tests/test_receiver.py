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


class TelegramClientTests(unittest.TestCase):
    def test_send_reply_uses_reply_parameters(self):
        client = receiver.TelegramClient("token")
        with patch.object(
            client,
            "call",
            return_value={"message_id": 99, "chat": {"id": 123, "type": "private"}},
        ) as mocked_call:
            result = client.send_reply(
                {
                    "message": {
                        "message_id": 9,
                        "chat": {"id": 123},
                        "text": "hello",
                    }
                },
                "answer",
            )

        self.assertEqual(result["message_id"], 99)
        method, payload = mocked_call.call_args.args
        self.assertEqual(method, "sendMessage")
        self.assertEqual(payload["chat_id"], 123)
        self.assertEqual(payload["text"], "answer")
        self.assertEqual(payload["reply_parameters"], {"message_id": 9})


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


class FakeTelegram:
    def __init__(self, events=None, fail_send_once=False):
        self.events = events if events is not None else []
        self.fail_send_once = fail_send_once
        self.sent_update_ids = []

    def send_reply(self, update, text):
        update_id = update["update_id"]
        self.events.append(f"send:{update_id}")
        if self.fail_send_once:
            self.fail_send_once = False
            raise receiver.ReceiverError("synthetic send failure")
        self.sent_update_ids.append(update_id)
        return {"message_id": 1000 + update_id}


class FakeConsumer:
    def __init__(self, events=None, fail_once_update_id=None):
        self.events = events if events is not None else []
        self.fail_once_update_id = fail_once_update_id
        self.processed_update_ids = []

    def process(self, event):
        update_id = int(event["event_id"])
        self.events.append(f"consumer:{update_id}")
        if self.fail_once_update_id == update_id:
            self.fail_once_update_id = None
            raise receiver.ReceiverError("synthetic consumer failure")
        self.processed_update_ids.append(update_id)
        return {
            "schema_version": 1,
            "event_id": str(update_id),
            "action": "reply",
            "text": f"answer:{update_id}",
        }


class FakeCheckpoint:
    def __init__(self, last_processed_update_id=None, events=None, fail_save_once=False):
        self.events = events if events is not None else []
        self.fail_save_once = fail_save_once
        self.saved = []
        self.data = {
            "schema_version": 1,
            "last_processed_update_id": last_processed_update_id,
            "last_action": None,
            "telegram_message_id": None,
            "updated_at": None,
        }

    def load(self):
        return dict(self.data)

    def save(self, *, update_id, action, telegram_message_id):
        self.events.append(f"checkpoint:{update_id}")
        if self.fail_save_once:
            self.fail_save_once = False
            raise receiver.ReceiverError("synthetic checkpoint failure")
        self.saved.append((update_id, action, telegram_message_id))
        self.data.update(
            {
                "last_processed_update_id": update_id,
                "last_action": action,
                "telegram_message_id": telegram_message_id,
            }
        )


def make_runtime(*, last_processed_update_id=None, fail_send_once=False, fail_checkpoint_once=False):
    events = []
    telegram = FakeTelegram(events=events, fail_send_once=fail_send_once)
    consumer = FakeConsumer(events=events)
    checkpoint = FakeCheckpoint(
        last_processed_update_id=last_processed_update_id,
        events=events,
        fail_save_once=fail_checkpoint_once,
    )
    runtime = receiver.Runtime(
        config={"retry_max_seconds": 1},
        telegram=telegram,
        consumer=consumer,
        checkpoint=checkpoint,
        allowed_chat_id=None,
        checkpoint_data=checkpoint.load(),
    )
    return runtime, telegram, consumer, checkpoint, events


class RuntimeBehaviorTests(unittest.TestCase):
    def test_initial_offset_restores_from_checkpoint(self):
        runtime, _, _, _, _ = make_runtime(last_processed_update_id=41)
        self.assertEqual(runtime.initial_offset(), 42)

    def test_fifo_sequence_is_processed_in_update_id_order(self):
        runtime, telegram, consumer, checkpoint, _ = make_runtime()
        last_id = None
        updates = [
            {"update_id": 3, "message": {"chat": {"id": 1}, "message_id": 30}},
            {"update_id": 1, "message": {"chat": {"id": 1}, "message_id": 10}},
            {"update_id": 2, "message": {"chat": {"id": 1}, "message_id": 20}},
        ]
        updates.sort(key=lambda item: item["update_id"])

        for update in updates:
            last_id, _, _ = runtime.handle_update(
                update,
                last_processed_update_id=last_id,
                retry_max=1,
            )

        self.assertEqual(consumer.processed_update_ids, [1, 2, 3])
        self.assertEqual(telegram.sent_update_ids, [1, 2, 3])
        self.assertEqual([item[0] for item in checkpoint.saved], [1, 2, 3])

    def test_completed_checkpoint_deduplicates_replayed_update(self):
        runtime, telegram, consumer, checkpoint, _ = make_runtime(last_processed_update_id=7)
        last_id, processed, filtered = runtime.handle_update(
            {"update_id": 7, "message": {"chat": {"id": 1}, "message_id": 70}},
            last_processed_update_id=7,
            retry_max=1,
        )
        self.assertEqual(last_id, 7)
        self.assertEqual(processed, 0)
        self.assertEqual(filtered, 0)
        self.assertEqual(consumer.processed_update_ids, [])
        self.assertEqual(telegram.sent_update_ids, [])
        self.assertEqual(checkpoint.saved, [])

    def test_failed_current_update_cannot_be_checkpointed_or_overtaken(self):
        runtime, telegram, consumer, checkpoint, _ = make_runtime(fail_send_once=True)
        first = {"update_id": 1, "message": {"chat": {"id": 1}, "message_id": 10}}
        second = {"update_id": 2, "message": {"chat": {"id": 1}, "message_id": 20}}

        with self.assertRaises(receiver.ReceiverError):
            runtime.handle_update(first, last_processed_update_id=None, retry_max=1)

        self.assertEqual(checkpoint.saved, [])
        self.assertEqual(telegram.sent_update_ids, [])

        last_id, _, _ = runtime.handle_update(first, last_processed_update_id=None, retry_max=1)
        last_id, _, _ = runtime.handle_update(second, last_processed_update_id=last_id, retry_max=1)

        self.assertEqual(last_id, 2)
        self.assertEqual(telegram.sent_update_ids, [1, 2])
        self.assertEqual([item[0] for item in checkpoint.saved], [1, 2])

    def test_checkpoint_is_after_send_and_retries_without_resending(self):
        runtime, telegram, _, checkpoint, events = make_runtime(fail_checkpoint_once=True)
        update = {"update_id": 5, "message": {"chat": {"id": 1}, "message_id": 50}}

        with patch("receiver.time.sleep", return_value=None):
            last_id, _, _ = runtime.handle_update(
                update,
                last_processed_update_id=None,
                retry_max=1,
            )

        self.assertEqual(last_id, 5)
        self.assertEqual(telegram.sent_update_ids, [5])
        self.assertEqual(events, ["consumer:5", "send:5", "checkpoint:5", "checkpoint:5"])
        self.assertEqual([item[0] for item in checkpoint.saved], [5])




class RuntimeEnvironmentTests(unittest.TestCase):
    def test_disabled_check_does_not_require_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"enabled": false}', encoding="utf-8")
            args = type("Args", (), {"config": str(path)})()
            self.assertEqual(receiver.command_check(args), 0)

    def test_runtime_requires_checkpoint_context(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            consumer_dir = Path(directory) / "consumer"
            consumer_dir.mkdir()
            (consumer_dir / "consumer.py").write_text("pass", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "consumer_image": "python:3.12-slim",
                        "consumer_script": "consumer.py",
                        "checkpoint_branch": "receiver-checkpoint",
                        "checkpoint_path": "state/checkpoint.json",
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "TELEGRAM_BOT_TOKEN": "bot-token",
                "TELEGRAM_CHAT_ID": "123",
                "RECEIVER_GITHUB_TOKEN": "runtime-token",
                "RECEIVER_REPOSITORY": "owner/repo",
                "CONSUMER_DIR": str(consumer_dir),
            }
            with patch.dict(os.environ, env, clear=True):
                runtime = receiver.Runtime.from_environment(str(config_path))
            self.assertEqual(runtime.allowed_chat_id, "123")
            self.assertEqual(runtime.checkpoint.branch, "receiver-checkpoint")
            self.assertEqual(runtime.checkpoint.path, "state/checkpoint.json")


if __name__ == "__main__":
    unittest.main()
