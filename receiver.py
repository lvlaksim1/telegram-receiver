#!/usr/bin/env python3
"""GitHub-native Telegram long-poll receiver.

The receiver intentionally provides at-least-once delivery. A Telegram update is
only confirmed after GitHub accepts its repository_dispatch request. If the
worker dies between dispatch and confirmation, the same update can be delivered
again; consumers must deduplicate by update_id.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

API_VERSION = "2022-11-28"
DEFAULT_CONFIG_PATH = "receiver-config.json"
MAX_DISPATCH_PAYLOAD_BYTES = 60 * 1024


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


def http_json(
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    body: Optional[dict[str, Any]] = None,
    timeout: int = 30,
    expected: tuple[int, ...] = (200,),
) -> tuple[int, Any]:
    request_headers = {"User-Agent": "telegram-receiver/0.1"}
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


@dataclass
class GitHubDispatchClient:
    token: str
    repository: str
    event_type: str

    def check_repository(self) -> None:
        http_json(
            "GET",
            f"https://api.github.com/repos/{self.repository}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
            },
            expected=(200,),
        )

    def dispatch(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            raise ReceiverError("Telegram update is missing integer update_id")

        envelope = {
            "schema_version": 1,
            "source": "telegram",
            "update_id": update_id,
            "received_at": utc_now(),
            "chat_id": extract_chat_id(update),
            "update": update,
        }
        body = {"event_type": self.event_type, "client_payload": envelope}
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) >= MAX_DISPATCH_PAYLOAD_BYTES:
            raise ReceiverError(
                f"repository_dispatch payload too large for update_id={update_id}: {len(encoded)} bytes"
            )

        http_json(
            "POST",
            f"https://api.github.com/repos/{self.repository}/dispatches",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
            },
            body=body,
            expected=(204,),
        )


@dataclass
class Runtime:
    config: dict[str, Any]
    telegram: TelegramClient
    dispatch: GitHubDispatchClient
    allowed_chat_id: Optional[str]

    @classmethod
    def from_environment(cls, config_path: str) -> "Runtime":
        config = load_config(config_path)

        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        dispatch_token = os.environ.get("CONSUMER_DISPATCH_TOKEN", "").strip()
        allowed_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None
        repository = str(config.get("consumer_repository", "")).strip()
        event_type = str(config.get("event_type", "telegram_update")).strip()

        if not telegram_token:
            raise ReceiverError("TELEGRAM_BOT_TOKEN is not configured")
        if not dispatch_token:
            raise ReceiverError("CONSUMER_DISPATCH_TOKEN is not configured")
        if not repository or "/" not in repository:
            raise ReceiverError("consumer_repository is not configured")
        if not event_type:
            raise ReceiverError("event_type must not be empty")

        return cls(
            config=config,
            telegram=TelegramClient(telegram_token),
            dispatch=GitHubDispatchClient(dispatch_token, repository, event_type),
            allowed_chat_id=allowed_chat_id,
        )

    def preflight(self) -> None:
        bot = self.telegram.get_me()
        webhook = self.telegram.get_webhook_info()
        webhook_url = str(webhook.get("url") or "")
        if webhook_url:
            raise ReceiverError(
                "Telegram webhook is active. getUpdates cannot be used until the webhook is removed."
            )
        self.dispatch.check_repository()
        username = bot.get("username") or bot.get("id") or "unknown"
        print(f"preflight_ok bot={username} consumer={self.dispatch.repository}", flush=True)

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
        delivered = 0
        filtered = 0

        print(
            f"receiver_started consumer={self.dispatch.repository} max_runtime={max_runtime}s",
            flush=True,
        )

        while time.monotonic() < deadline:
            try:
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
                    if self.allowed_chat_id is not None and chat_id != self.allowed_chat_id:
                        filtered += 1
                        offset = update_id + 1
                        print(
                            f"update_filtered update_id={update_id} chat_match=false",
                            flush=True,
                        )
                        continue

                    self.dispatch.dispatch(update)
                    delivered += 1
                    offset = update_id + 1
                    print(
                        f"update_dispatched update_id={update_id} chat_id={chat_id or 'none'}",
                        flush=True,
                    )

            except ReceiverError as exc:
                print(f"receiver_retry error={exc} retry_in={backoff}s", file=sys.stderr, flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, retry_max)

        if offset is not None:
            try:
                # Confirms all successfully handled updates below offset without
                # confirming any newly returned update at or above offset.
                self.telegram.get_updates(
                    offset=offset,
                    timeout=0,
                    allowed_updates=allowed_updates,
                    limit=1,
                )
            except ReceiverError as exc:
                print(f"final_confirmation_failed error={exc}", file=sys.stderr, flush=True)

        print(
            f"receiver_stopped delivered={delivered} filtered={filtered} next_offset={offset}",
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
        if args.command == "run":
            return command_run(args)
        raise ReceiverError(f"Unknown command: {args.command}")
    except (ReceiverError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
