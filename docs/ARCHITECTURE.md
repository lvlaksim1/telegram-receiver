# Architecture

## Purpose

`telegram-receiver` owns the complete Telegram transport boundary.

```text
Telegram <-> Receiver <-> durable queue <-> isolated consumer
```

The durable queue is stored in the `receiver-runtime` branch of this repository.

## Core invariants

1. Only Receiver has Telegram credentials.
2. Consumer code receives no Telegram or GitHub credentials.
3. One Telegram update never creates one GitHub Actions runner.
4. Updates are processed in strict increasing `update_id` order.
5. Every accepted update is persisted before Telegram is allowed to confirm it.
6. Runner-local state is never authoritative.
7. Existing receipts suppress processing of already completed updates.
8. Raw message bodies are not written to operational logs.
9. Runtime queue data is currently public by explicit design choice for the test stage.

## Event lifecycle

For update `N`:

```text
getUpdates
  ↓
persist runtime/inbox/N.json
  ↓
append N to runtime/state.json
  ↓
run consumer in isolated container
  ↓
persist runtime/outbox/N.json
  ↓
Receiver calls Telegram sendMessage if requested
  ↓
persist runtime/receipts/N.json
  ↓
remove N from pending state
  ↓
only then continue with N+1
```

If processing fails, Receiver retries the oldest pending event before polling for newer Telegram updates.

## Consumer isolation

The configured public consumer repository is cloned once per Receiver worker.

Consumer execution uses Docker with:

- no Receiver environment variables;
- no Telegram token;
- no GitHub token;
- no network;
- read-only filesystem;
- dropped Linux capabilities;
- no-new-privileges;
- unprivileged UID/GID.

The consumer reads one JSON event from stdin and writes one JSON action to stdout.

Supported actions currently:

- `reply`
- `no_reply`

Receiver validates the action and controls the Telegram destination.

## Runtime branch

`receiver-runtime` is runtime storage and is never merged into `main`.

Paths:

```text
runtime/state.json
runtime/inbox/<update_id>.json
runtime/outbox/<update_id>.json
runtime/receipts/<update_id>.json
```

Only the Receiver worker writes these objects.

## Worker lifecycle

The Receiver uses a serialized handover:

1. start;
2. preflight Telegram, runtime branch and consumer runtime;
3. queue one successor;
4. run for about 5.5 hours;
5. exit;
6. queued successor starts.

A watchdog recreates the chain if no active or queued Receiver run exists.

## Failure model

| Failure | Recovery |
|---|---|
| runner dies before inbox persistence | Telegram can redeliver the update |
| runner dies after inbox persistence | next worker resumes from pending state |
| consumer fails | oldest pending event retries; newer events do not overtake it |
| runner dies after outbox persistence | next worker reuses the existing action |
| Telegram send fails | same pending event retries |
| runner dies after Telegram accepts reply but before receipt | reply may be duplicated |
| worker chain disappears | watchdog requests another worker |

The last case is the only remaining unavoidable duplicate window because Telegram `sendMessage` has no Receiver-controlled idempotency key.

## Security model

The test consumer repository intentionally has no `TELEGRAM_BOT_TOKEN` and no `TELEGRAM_CHAT_ID`.

The high-privilege `REPO_FACTORY_TOKEN` remains confined to `repo-factory`.

The old per-update `CONSUMER_DISPATCH_TOKEN` transport is no longer part of the message path.
