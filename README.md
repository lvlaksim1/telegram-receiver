# telegram-receiver

GitHub-native Telegram receiver with one persistent worker and strict sequential processing.

Only `telegram-receiver` talks to Telegram. Consumer code never receives `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID`.

## Current data path

```text
Telegram getUpdates
      ↓
persistent Receiver worker
      ↓
isolated consumer container
      ↓
Receiver sendMessage
      ↓
Telegram
```

There is no per-message `repository_dispatch`, no per-message GitHub Actions runner, and no GitHub Contents/API queue in the hot path.

## Ordering

Updates returned by Telegram are sorted by numeric `update_id` and processed one at a time.

```text
update N
  ↓
consumer N
  ↓
send reply N
  ↓
update N+1
```

A later message cannot overtake an earlier message inside the Receiver.

This direct FIFO path was validated on 2026-09-19 with:
- one-message test `TEST_D`: reply arrived immediately without a second trigger message;
- burst test `1 2 3 4 5`: all replies arrived in the correct order.

## Consumer isolation

The configured consumer repository is cloned once when a Receiver worker starts.

Each event is executed inside a restricted Docker container with:
- no network;
- read-only filesystem;
- dropped Linux capabilities;
- `no-new-privileges`;
- unprivileged UID/GID;
- no Telegram token;
- no GitHub token.

The consumer contract is stdin/stdout JSON:

```text
receiver event JSON -> consumer -> action JSON
```

Supported actions:
- `reply`
- `no_reply`

Receiver validates the action and derives the Telegram destination from the original update. For ordinary messages it uses Telegram `reply_parameters` so the answer is visibly bound to the source message.

## Continuous operation

A Receiver worker runs for about 5.5 hours.

Before entering the polling loop it queues one successor run. GitHub Actions concurrency allows only one Receiver worker to execute at a time. A watchdog periodically verifies that a live or queued Receiver run exists.

## Recovery model

Telegram remains the authoritative inbound queue, while a lightweight persistent checkpoint is stored in the dedicated `receiver-checkpoint` branch:

```text
state/checkpoint.json
```

The checkpoint contains the last completed Telegram `update_id` and is loaded when a worker starts. The next worker therefore starts from `last_processed_update_id + 1` instead of `offset=None`.

The checkpoint write happens only **after** consumer processing and Telegram `sendMessage` have completed:

```text
getUpdates -> consumer -> sendMessage -> checkpoint
```

If a checkpoint write temporarily fails, Receiver retries the checkpoint without running the consumer or sending the Telegram reply again. This keeps GitHub persistence out of the reply hot path.

A narrow crash window still exists if the process dies after Telegram accepts `sendMessage` but before the checkpoint is persisted. Telegram Bot API does not provide a Receiver-controlled idempotency key for `sendMessage`, so this residual duplicate window is documented rather than hidden.

## Current consumer

`lvlaksim1/telegram-receiver-test-consumer`

Current configuration:

```json
{
  "enabled": true,
  "consumer_repository": "lvlaksim1/telegram-receiver-test-consumer",
  "consumer_image": "python:3.12-slim",
  "consumer_script": "consumer.py",
  "consumer_timeout_seconds": 60,
  "checkpoint_branch": "receiver-checkpoint",
  "checkpoint_path": "state/checkpoint.json",
  "max_runtime_seconds": 19800,
  "long_poll_timeout_seconds": 50,
  "retry_max_seconds": 30,
  "allowed_updates": null
}
```

## Control plane

Owner-only Issue commands:
- `[RECEIVER_START]`
- `[RECEIVER_STOP]`
- `[RECEIVER_STATUS]`
- `[RECEIVER_HEALTHCHECK]`

The health check never calls `getUpdates`. It checks Telegram credentials/webhook state, the persistent checkpoint and the presence of a live or queued Receiver worker, so it cannot compete with the Receiver for updates.

## Project context

For a new chat or handoff, start with:

1. `.context/ENTRYPOINT.md`
2. `.context/handoffs/latest.md`

These files are the Project Context Capsule and describe the authoritative architecture, current state, key decisions, known limitations and next work point.

## Local tests

```bash
python3 -m unittest discover -s tests -v
```
