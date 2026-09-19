#!/usr/bin/env python3
"""GitHub-native Telegram receiver with durable in-repository queue.

Only this receiver talks to Telegram. Consumer code is executed in an isolated
container without Telegram or GitHub credentials and returns actions over
stdin/stdout JSON.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

API_VERSION = "2022-11-28"
DEFAULT_CONFIG_PATH = "receiver-config.json"
STATE_PATH = "runtime/state.json"


class ReceiverError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ReceiverError(f"Config file not found: {path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ReceiverError("Configuration root must be a JSON object")
    return data


def extract_chat_id(update: dict[str, Any]) -> Optional[str]:
    direct_chat_fields = (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "business_message",
        "edited_business_message",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
    )
    for field in direct_chat_fields:
        value = update.get(field)
        if isinstance(value, dict):
            chat = value.get("chat")
            if isinstance(chat, dict) and "id" in chat:
                return str(chat["id"])

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        message = callback.get("message")
        if isinstance(message, dict):
            chat = message.get("chat")
            if isinstance(chat, dict) and "id" in chat:
                return str(chat["id"])

    deleted = update.get("deleted_business_messages")
    if isinstance(deleted, dict):
        chat = deleted.get("chat")
        if isinstance(chat, dict) and "id" in chat:
            return str(chat["id"])

    return None


def extract_message_context(update: dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    message_fields = (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "business_message",
        "edited_business_message",
    )
    message: Optional[dict[str, Any]] = None
    for field in message_fields:
        value = update.get(field)
        if isinstance(value, dict):
            message = value
            break

    if message is None:
        callback = update.get("callback_query")
        if isinstance(callback, dict) and isinstance(callback.get("message"), dict):
            message = callback["message"]

    if message is None:
        return None, None, None

    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    message_id = message.get("message_id")
    thread_id = message.get("message_thread_id")

    return (
        chat_id if isinstance(chat_id, int) else None,
        message_id if isinstance(message_id, int) else None,
        thread_id if isinstance(thread_id, int) else None,
    )


def http_json(
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    body: Optional[dict[str, Any]] = None,
    timeout: int = 30,
    expected: tuple[int, ...] = (200,),
) -> tuple[int, Any]:
    request_headers = {"User-Agent": "telegram-receiver/0.2"}
    if headers:
        request_headers.update(headers)

    payload = None
    if body is not None:
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except urllib.error.URLError as exc:
        raise ReceiverError(f"Network error: {exc.reason}") from exc

    parsed: Any = None
    if raw:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = raw.decode("utf-8", errors="replace")

    if status not in expected:
        detail = parsed.get("message") if isinstance(parsed, dict) else str(parsed)
        raise ReceiverError(f"HTTP {status}: {detail}")

    return status, parsed


@dataclass
class TelegramClient:
    token: str

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def call(self, method: str, payload: Optional[dict[str, Any]] = None, timeout: int = 30) -> Any:
        _, response = http_json(
            "POST",
            f"{self.base_url}/{method}",
            body=payload or {},
            timeout=timeout,
            expected=(200,),
        )
        if not isinstance(response, dict) or response.get("ok") is not True:
            description = response.get("description") if isinstance(response, dict) else response
            raise ReceiverError(f"Telegram {method} failed: {description}")
        return response.get("result")

    def get_me(self) -> dict[str, Any]:
        result = self.call("getMe")
        if not isinstance(result, dict):
            raise ReceiverError("Telegram getMe returned an invalid result")
        return result

    def get_webhook_info(self) -> dict[str, Any]:
        result = self.call("getWebhookInfo")
        if not isinstance(result, dict):
            raise ReceiverError("Telegram getWebhookInfo returned an invalid result")
        return result

    def get_updates(
        self,
        *,
        offset: Optional[int],
        timeout: int,
        allowed_updates: Optional[list[str]],
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        result = self.call("getUpdates", payload, timeout=timeout + 15)
        if not isinstance(result, list):
            raise ReceiverError("Telegram getUpdates returned an invalid result")
        return [item for item in result if isinstance(item, dict)]

    def send_reply(self, update: dict[str, Any], text: str) -> dict[str, Any]:
        chat_id, message_id, thread_id = extract_message_context(update)
        if chat_id is None:
            raise ReceiverError("Cannot reply to update without a message chat")

        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if message_id is not None:
            payload["reply_parameters"] = {"message_id": message_id}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        result = self.call("sendMessage", payload)
        if not isinstance(result, dict):
            raise ReceiverError("Telegram sendMessage returned an invalid result")
        return result


@dataclass
class GitHubRuntimeStore:
    token: str
    repository: str
    branch: str

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def check_branch(self) -> None:
        branch = urllib.parse.quote(self.branch, safe="")
        http_json(
            "GET",
            f"https://api.github.com/repos/{self.repository}/branches/{branch}",
            headers=self.headers,
            expected=(200,),
        )

    def _contents_url(self, path: str) -> str:
        encoded = urllib.parse.quote(path, safe="/")
        return f"https://api.github.com/repos/{self.repository}/contents/{encoded}"

    def get_json(self, path: str) -> Optional[dict[str, Any]]:
        query = urllib.parse.urlencode({"ref": self.branch})
        status, response = http_json(
            "GET",
            f"{self._contents_url(path)}?{query}",
            headers=self.headers,
            expected=(200, 404),
        )
        if status == 404:
            return None
        if not isinstance(response, dict):
            raise ReceiverError(f"Invalid GitHub contents response for {path}")
        encoded = response.get("content")
        if not isinstance(encoded, str):
            raise ReceiverError(f"Missing content for {path}")
        try:
            raw = base64.b64decode(encoded).decode("utf-8")
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReceiverError(f"Invalid JSON runtime file: {path}") from exc
        if not isinstance(data, dict):
            raise ReceiverError(f"Runtime file must contain a JSON object: {path}")
        data["_github_sha"] = response.get("sha")
        return data

    def put_json(
        self,
        path: str,
        data: dict[str, Any],
        *,
        message: str,
        immutable: bool = False,
    ) -> bool:
        existing = self.get_json(path)
        existing_sha: Optional[str] = None
        if existing is not None:
            existing_sha = str(existing.pop("_github_sha", "") or "")
            if existing == data:
                return False
            if immutable:
                raise ReceiverError(f"Immutable runtime object already differs: {path}")

        content = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if existing_sha:
            body["sha"] = existing_sha

        http_json(
            "PUT",
            self._contents_url(path),
            headers=self.headers,
            body=body,
            expected=(200, 201),
        )
        return True

    def load_state(self) -> dict[str, Any]:
        state = self.get_json(STATE_PATH)
        if state is None:
            state = {"schema_version": 1, "pending": [], "updated_at": utc_now()}
            self.put_json(STATE_PATH, state, message="Initialize receiver runtime state")
            return state
        state.pop("_github_sha", None)
        pending = state.get("pending")
        if state.get("schema_version") != 1 or not isinstance(pending, list):
            raise ReceiverError("Invalid runtime state")
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        clean = dict(state)
        clean.pop("_github_sha", None)
        clean["updated_at"] = utc_now()
        self.put_json(STATE_PATH, clean, message="Update receiver runtime state")

    def enqueue(self, update: dict[str, Any]) -> str:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            raise ReceiverError("Telegram update is missing integer update_id")
        event_id = str(update_id)

        if self.get_json(f"runtime/receipts/{event_id}.json") is not None:
            return "completed"

        self.put_json(
            f"runtime/inbox/{event_id}.json",
            {
                "schema_version": 1,
                "event_id": event_id,
                "received_at": utc_now(),
                "update": update,
            },
            message=f"Queue Telegram update {event_id}",
            immutable=True,
        )

        state = self.load_state()
        pending = [str(item) for item in state["pending"]]
        if event_id not in pending:
            pending.append(event_id)
            pending.sort(key=int)
            state["pending"] = pending
            self.save_state(state)
        return "queued"

    def next_pending(self) -> Optional[str]:
        state = self.load_state()
        pending = [str(item) for item in state["pending"]]
        if not pending:
            return None
        pending.sort(key=int)
        return pending[0]

    def complete(self, event_id: str) -> None:
        state = self.load_state()
        pending = [str(item) for item in state["pending"] if str(item) != event_id]
        if pending != state["pending"]:
            state["pending"] = pending
            self.save_state(state)

    def get_inbox(self, event_id: str) -> dict[str, Any]:
        data = self.get_json(f"runtime/inbox/{event_id}.json")
        if data is None:
            raise ReceiverError(f"Missing inbox object for event {event_id}")
        data.pop("_github_sha", None)
        return data

    def get_outbox(self, event_id: str) -> Optional[dict[str, Any]]:
        data = self.get_json(f"runtime/outbox/{event_id}.json")
        if data is not None:
            data.pop("_github_sha", None)
        return data

    def get_receipt(self, event_id: str) -> Optional[dict[str, Any]]:
        data = self.get_json(f"runtime/receipts/{event_id}.json")
        if data is not None:
            data.pop("_github_sha", None)
        return data

    def save_outbox(self, event_id: str, action: dict[str, Any]) -> None:
        self.put_json(
            f"runtime/outbox/{event_id}.json",
            action,
            message=f"Store consumer action {event_id}",
            immutable=True,
        )

    def save_receipt(self, event_id: str, receipt: dict[str, Any]) -> None:
        self.put_json(
            f"runtime/receipts/{event_id}.json",
            receipt,
            message=f"Complete Telegram event {event_id}",
            immutable=True,
        )


@dataclass
class ConsumerRunner:
    directory: str
    image: str
    script: str
    timeout_seconds: int

    def check(self) -> None:
        script_path = Path(self.directory) / self.script
        if not script_path.is_file():
            raise ReceiverError(f"Consumer script not found: {script_path}")

        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReceiverError(f"Docker consumer runtime unavailable: {exc}") from exc
        if result.returncode != 0:
            raise ReceiverError(f"Consumer image is unavailable: {self.image}")

    def process(self, event: dict[str, Any]) -> dict[str, Any]:
        mount_dir = str(Path(self.directory).resolve())
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-i",
            "-v",
            f"{mount_dir}:/consumer:ro",
            self.image,
            "python",
            f"/consumer/{self.script}",
        ]
        payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)

        try:
            result = subprocess.run(
                command,
                input=payload,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReceiverError("Consumer timed out") from exc
        except OSError as exc:
            raise ReceiverError(f"Consumer failed to start: {exc}") from exc

        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no stderr"
            raise ReceiverError(f"Consumer failed with exit={result.returncode}: {detail[:300]}")

        try:
            action = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ReceiverError("Consumer stdout is not valid JSON") from exc
        if not isinstance(action, dict):
            raise ReceiverError("Consumer action must be a JSON object")
        return action


def validate_consumer_action(event_id: str, action: dict[str, Any]) -> dict[str, Any]:
    if action.get("schema_version") != 1:
        raise ReceiverError("Consumer action has invalid schema_version")
    if str(action.get("event_id") or "") != event_id:
        raise ReceiverError("Consumer action event_id mismatch")

    action_type = action.get("action")
    if action_type == "no_reply":
        return {"schema_version": 1, "event_id": event_id, "action": "no_reply"}

    if action_type == "reply":
        text = action.get("text")
        if not isinstance(text, str) or not text:
            raise ReceiverError("Consumer reply text must be a non-empty string")
        if len(text) > 4096:
            raise ReceiverError("Consumer reply text exceeds Telegram limit")
        return {
            "schema_version": 1,
            "event_id": event_id,
            "action": "reply",
            "text": text,
        }

    raise ReceiverError(f"Unsupported consumer action: {action_type}")


@dataclass
class Runtime:
    config: dict[str, Any]
    telegram: TelegramClient
    store: GitHubRuntimeStore
    consumer: ConsumerRunner
    allowed_chat_id: Optional[str]

    @classmethod
    def from_environment(cls, config_path: str) -> "Runtime":
        config = load_config(config_path)

        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        runtime_token = os.environ.get("RECEIVER_GITHUB_TOKEN", "").strip()
        repository = os.environ.get("RECEIVER_REPOSITORY", "").strip()
        allowed_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None
        consumer_dir = os.environ.get("CONSUMER_DIR", "").strip()

        runtime_branch = str(config.get("runtime_branch", "receiver-runtime")).strip()
        consumer_image = str(config.get("consumer_image", "python:3.12-slim")).strip()
        consumer_script = str(config.get("consumer_script", "consumer.py")).strip()
        consumer_timeout = int(config.get("consumer_timeout_seconds", 60))

        if not telegram_token:
            raise ReceiverError("TELEGRAM_BOT_TOKEN is not configured")
        if not runtime_token:
            raise ReceiverError("RECEIVER_GITHUB_TOKEN is not configured")
        if not repository or "/" not in repository:
            raise ReceiverError("RECEIVER_REPOSITORY is not configured")
        if not runtime_branch:
            raise ReceiverError("runtime_branch must not be empty")
        if not consumer_dir:
            raise ReceiverError("CONSUMER_DIR is not configured")
        if not consumer_image:
            raise ReceiverError("consumer_image must not be empty")
        if not consumer_script:
            raise ReceiverError("consumer_script must not be empty")

        return cls(
            config=config,
            telegram=TelegramClient(telegram_token),
            store=GitHubRuntimeStore(runtime_token, repository, runtime_branch),
            consumer=ConsumerRunner(
                directory=consumer_dir,
                image=consumer_image,
                script=consumer_script,
                timeout_seconds=consumer_timeout,
            ),
            allowed_chat_id=allowed_chat_id,
        )

    def preflight(self) -> None:
        self.telegram.get_me()
        webhook = self.telegram.get_webhook_info()
        if str(webhook.get("url") or ""):
            raise ReceiverError(
                "Telegram webhook is active. getUpdates cannot be used until the webhook is removed."
            )
        self.store.check_branch()
        self.store.load_state()
        self.consumer.check()
        print(
            f"preflight_ok runtime_branch={self.store.branch} consumer_isolated=true",
            flush=True,
        )

    def process_event(self, event_id: str) -> str:
        receipt = self.store.get_receipt(event_id)
        if receipt is not None:
            self.store.complete(event_id)
            print(f"event_already_completed update_id={event_id}", flush=True)
            return "already_completed"

        inbox = self.store.get_inbox(event_id)
        update = inbox.get("update")
        if not isinstance(update, dict):
            raise ReceiverError(f"Invalid inbox update for event {event_id}")

        action = self.store.get_outbox(event_id)
        if action is None:
            consumer_event = {
                "schema_version": 1,
                "event_id": event_id,
                "received_at": inbox.get("received_at"),
                "update": update,
            }
            action = validate_consumer_action(event_id, self.consumer.process(consumer_event))
            self.store.save_outbox(event_id, action)
        else:
            action = validate_consumer_action(event_id, action)

        action_type = action["action"]
        if action_type == "no_reply":
            self.store.save_receipt(
                event_id,
                {
                    "schema_version": 1,
                    "event_id": event_id,
                    "action": "no_reply",
                    "completed_at": utc_now(),
                },
            )
            self.store.complete(event_id)
            print(f"event_completed update_id={event_id} action=no_reply", flush=True)
            return "no_reply"

        sent = self.telegram.send_reply(update, action["text"])
        sent_message_id = sent.get("message_id")
        self.store.save_receipt(
            event_id,
            {
                "schema_version": 1,
                "event_id": event_id,
                "action": "reply",
                "telegram_message_id": sent_message_id,
                "completed_at": utc_now(),
            },
        )
        self.store.complete(event_id)
        print(
            f"event_completed update_id={event_id} action=reply message_id={sent_message_id}",
            flush=True,
        )
        return "reply"

    def drain_pending(self) -> int:
        processed = 0
        while True:
            event_id = self.store.next_pending()
            if event_id is None:
                return processed
            self.process_event(event_id)
            processed += 1

    def run(self) -> None:
        max_runtime = int(self.config.get("max_runtime_seconds", 19800))
        long_poll_timeout = int(self.config.get("long_poll_timeout_seconds", 50))
        retry_max = int(self.config.get("retry_max_seconds", 30))
        allowed_updates = self.config.get("allowed_updates")
        if allowed_updates is not None and not isinstance(allowed_updates, list):
            raise ReceiverError("allowed_updates must be an array or null")

        deadline = time.monotonic() + max_runtime
        offset: Optional[int] = None
        backoff = 1
        queued = 0
        processed = 0
        filtered = 0

        print(
            f"receiver_started runtime_branch={self.store.branch} max_runtime={max_runtime}s",
            flush=True,
        )

        while time.monotonic() < deadline:
            try:
                processed += self.drain_pending()

                updates = self.telegram.get_updates(
                    offset=offset,
                    timeout=long_poll_timeout,
                    allowed_updates=allowed_updates,
                )
                backoff = 1

                for update in updates:
                    update_id = update.get("update_id")
                    if not isinstance(update_id, int):
                        continue

                    chat_id = extract_chat_id(update)
                    if (
                        self.allowed_chat_id is not None
                        and chat_id is not None
                        and chat_id != self.allowed_chat_id
                    ):
                        filtered += 1
                        offset = update_id + 1
                        print(
                            f"update_filtered update_id={update_id} chat_match=false",
                            flush=True,
                        )
                        continue

                    status = self.store.enqueue(update)
                    offset = update_id + 1
                    if status == "queued":
                        queued += 1
                    processed += self.drain_pending()

            except ReceiverError as exc:
                print(f"receiver_retry error={exc} retry_in={backoff}s", file=sys.stderr, flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, retry_max)

        if offset is not None:
            try:
                self.telegram.get_updates(
                    offset=offset,
                    timeout=0,
                    allowed_updates=allowed_updates,
                    limit=1,
                )
            except ReceiverError as exc:
                print(f"final_confirmation_failed error={exc}", file=sys.stderr, flush=True)

        print(
            f"receiver_stopped queued={queued} processed={processed} filtered={filtered} next_offset={offset}",
            flush=True,
        )


def command_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if config.get("enabled") is not True:
        print("receiver_disabled")
        return 0
    runtime = Runtime.from_environment(args.config)
    runtime.preflight()
    return 0


def command_telegram_check(args: argparse.Namespace) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ReceiverError("TELEGRAM_BOT_TOKEN is not configured")
    client = TelegramClient(token)
    bot = client.get_me()
    webhook = client.get_webhook_info()
    print(
        "telegram_ok "
        f"bot={bot.get('username') or bot.get('id')} "
        f"webhook_active={bool(webhook.get('url'))}",
        flush=True,
    )
    return 0


def command_telegram_probe(args: argparse.Namespace) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ReceiverError("TELEGRAM_BOT_TOKEN is not configured")
    client = TelegramClient(token)
    webhook = client.get_webhook_info()
    if str(webhook.get("url") or ""):
        raise ReceiverError("Telegram webhook is active; getUpdates probe is unavailable")
    updates = client.get_updates(
        offset=None,
        timeout=1,
        allowed_updates=None,
        limit=1,
    )
    first_update_id = updates[0].get("update_id") if updates else None
    print(
        f"telegram_probe_ok pending_count={len(updates)} first_update_id={first_update_id}",
        flush=True,
    )
    return 0


def command_queue_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    runtime_token = os.environ.get("RECEIVER_GITHUB_TOKEN", "").strip()
    repository = os.environ.get("RECEIVER_REPOSITORY", "").strip()
    branch = str(config.get("runtime_branch", "receiver-runtime")).strip()
    if not runtime_token:
        raise ReceiverError("RECEIVER_GITHUB_TOKEN is not configured")
    if not repository or "/" not in repository:
        raise ReceiverError("RECEIVER_REPOSITORY is not configured")
    store = GitHubRuntimeStore(runtime_token, repository, branch)
    store.check_branch()
    state = store.load_state()
    print(f"queue_ok branch={branch} pending={len(state['pending'])}", flush=True)
    return 0


def command_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if config.get("enabled") is not True:
        print("receiver_disabled")
        return 0
    runtime = Runtime.from_environment(args.config)
    runtime.preflight()
    runtime.run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub-native Telegram receiver")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("telegram-check")
    sub.add_parser("telegram-probe")
    sub.add_parser("queue-check")
    sub.add_parser("run")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "check":
            return command_check(args)
        if args.command == "telegram-check":
            return command_telegram_check(args)
        if args.command == "telegram-probe":
            return command_telegram_probe(args)
        if args.command == "queue-check":
            return command_queue_check(args)
        if args.command == "run":
            return command_run(args)
        raise ReceiverError(f"Unknown command: {args.command}")
    except (ReceiverError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
