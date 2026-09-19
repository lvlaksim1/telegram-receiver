# telegram-receiver

GitHub-native Telegram gateway with a durable in-repository queue.

Only `telegram-receiver` talks to Telegram. Consumer code never receives `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID`.

## Data path

```text
Telegram
   ↕
Receiver worker
   ↓
receiver-runtime branch
   ├─ runtime/inbox/
   ├─ runtime/outbox/
   ├─ runtime/receipts/
   └─ runtime/state.json
   ↓
isolated consumer container
   ↓
Receiver worker
   ↓
Telegram
```

One Telegram update no longer creates one GitHub Actions run.

The already-running Receiver worker executes the configured consumer locally in an isolated Docker container and processes updates strictly in arrival order.

## Security boundary

Secrets exist only in `telegram-receiver`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The consumer receives no Telegram or GitHub credentials.

The consumer contract is stdin/stdout JSON:

```text
receiver event JSON -> consumer -> action JSON
```

For example:

```json
{
  "schema_version": 1,
  "event_id": "553795842",
  "action": "reply",
  "text": "ответ: 111"
}
```

The consumer cannot choose the Telegram destination. Receiver sends the result back to the chat/message from the original Telegram update.

## Durable queue

Runtime state lives in the dedicated `receiver-runtime` branch of this same repository.

For every accepted update Receiver stores:

- `runtime/inbox/<update_id>.json` — incoming Telegram update;
- `runtime/outbox/<update_id>.json` — validated consumer action;
- `runtime/receipts/<update_id>.json` — completed processing record.

`runtime/state.json` contains the ordered pending event IDs.

The queue is currently public because this repository is public. This is intentional for the current test stage and can be changed later.

## Ordering

Messages are processed strictly in increasing Telegram `update_id` order.

```text
111 -> consumer -> reply 111 -> receipt
222 -> consumer -> reply 222 -> receipt
333 -> consumer -> reply 333 -> receipt
```

A later update cannot obtain a separate runner and overtake an earlier update.

## Recovery

The runner-local filesystem is not authoritative.

If a Receiver worker dies:

1. the next worker reads `runtime/state.json`;
2. unfinished inbox events are resumed in order;
3. an existing outbox action is reused instead of running the consumer again;
4. an existing receipt prevents a completed event from being processed again.

There is one unavoidable narrow duplicate window: Telegram may accept `sendMessage` and the worker may die before the receipt is persisted.

## Continuous operation

A Receiver worker runs for about 5.5 hours.

It queues one successor before entering the long-poll loop. GitHub Actions concurrency allows only one Receiver worker to execute at a time. A watchdog requests a new worker if the chain disappears.

## Consumer

Current test consumer:

`lvlaksim1/telegram-receiver-test-consumer`

Configuration:

```json
{
  "enabled": false,
  "consumer_repository": "lvlaksim1/telegram-receiver-test-consumer",
  "runtime_branch": "receiver-runtime",
  "consumer_image": "python:3.12-slim",
  "consumer_script": "consumer.py",
  "consumer_timeout_seconds": 60,
  "max_runtime_seconds": 19800,
  "long_poll_timeout_seconds": 50,
  "retry_max_seconds": 30,
  "allowed_updates": null
}
```

The consumer repository is cloned once when a Receiver worker starts. Each event is executed inside a restricted Docker container with no network and no Receiver secrets.

## Control plane

Owner-only Issue commands:

- `[RECEIVER_START]`
- `[RECEIVER_STOP]`
- `[RECEIVER_STATUS]`
- `[RECEIVER_HEALTHCHECK]`

## Local tests

```bash
python3 -m unittest discover -s tests -v
```
