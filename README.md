# telegram-receiver

GitHub-native receive-only Telegram gateway.

The service long-polls Telegram and forwards each accepted update to another GitHub repository using `repository_dispatch`. It does not send messages to Telegram and contains no application/business logic.

## Current status

The receiver core, CI, worker handover and watchdog are implemented.

The service is intentionally **disabled** in `receiver-config.json` until a consumer repository and its dispatch credential are configured. This prevents Telegram updates from being consumed before there is somewhere reliable to deliver them.

## Data path

```text
Telegram
   |
   | getUpdates long polling
   v
telegram-receiver
   |
   | repository_dispatch: telegram_update
   v
consumer repository
```

The consumer receives:

```json
{
  "schema_version": 1,
  "source": "telegram",
  "update_id": 123456789,
  "received_at": "2026-09-19T18:00:00Z",
  "chat_id": "123456789",
  "update": {
    "...": "raw Telegram Update object"
  }
}
```

## Delivery semantics

Delivery is **at least once**.

The receiver advances the Telegram offset only after GitHub accepts the corresponding `repository_dispatch`. If a runner dies after GitHub accepts the event but before Telegram receives the next offset, Telegram can return the same update again.

Consumers must therefore treat `update_id` as the idempotency key.

This choice prefers duplicates over message loss.

## Continuous operation on GitHub Actions

GitHub-hosted jobs have a finite execution limit, so the receiver uses serialized worker handover:

1. a worker starts and passes preflight;
2. it immediately queues its successor;
3. GitHub Actions concurrency allows only one receiver worker to execute at a time;
4. the current worker long-polls for about 5.5 hours and exits cleanly;
5. the already queued successor starts;
6. a watchdog runs every 15 minutes and requests a new worker if the chain disappears.

This avoids simultaneous Telegram `getUpdates` consumers while maintaining a warm successor.

## Required secrets

Already provisioned through `repo-factory`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Still required before activation:

- `CONSUMER_DISPATCH_TOKEN`

`CONSUMER_DISPATCH_TOKEN` should be a dedicated fine-grained GitHub token with only the access required to create `repository_dispatch` events in the selected consumer repository. Do not reuse the high-privilege `REPO_FACTORY_TOKEN`.

No secret values are stored in this public repository.

## Configuration

`receiver-config.json`:

```json
{
  "enabled": false,
  "consumer_repository": "",
  "event_type": "telegram_update",
  "max_runtime_seconds": 19800,
  "long_poll_timeout_seconds": 50,
  "retry_max_seconds": 30,
  "allowed_updates": null
}
```

Before activation:

1. set `consumer_repository` to `owner/repository`;
2. add `CONSUMER_DISPATCH_TOKEN`;
3. keep the target consumer workflow listening for `repository_dispatch.types: [telegram_update]`;
4. change `enabled` to `true`.

An example consumer workflow is in `examples/consumer-workflow.yml`.

## Chat filtering

When `TELEGRAM_CHAT_ID` is configured, updates associated with another chat are acknowledged and discarded rather than forwarded.

The raw message body is never printed by the receiver. Runtime logs contain only operational metadata such as `update_id` and `chat_id`.

## Telegram webhook safety

The receiver refuses to start if the bot already has a Telegram webhook configured. Telegram does not allow `getUpdates` and webhook delivery to be used simultaneously.

The receiver does not automatically delete an existing webhook.

## Local tests

```bash
python3 -m unittest discover -s tests -v
```

No third-party Python packages are required.
