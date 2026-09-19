# Architecture

## Purpose

`telegram-receiver` owns the Telegram transport boundary and serializes message processing.

```text
Telegram <-> Receiver <-> isolated consumer
```

GitHub Actions provides the long-lived worker runtime and control plane. GitHub repository storage is not part of the per-message hot path.

## Core invariants

1. Only Receiver has Telegram credentials.
2. Consumer code receives no Telegram or GitHub credentials.
3. One Telegram update never creates one GitHub Actions runner.
4. Updates are processed one at a time in increasing numeric `update_id` order.
5. Consumer N must finish before update N+1 is processed.
6. Receiver sends the consumer result only to the chat/message derived from the original Telegram update.
7. Raw message bodies are not written to ordinary operational logs.
8. No GitHub API read/write is required between receipt of an update and `sendMessage`.

## Event lifecycle

For update `N`:

```text
getUpdates
  ↓
validate/filter N
  ↓
run consumer N in isolated container
  ↓
validate consumer action
  ↓
Receiver calls sendMessage if requested
  ↓
advance local offset to N+1
  ↓
process the next update
```

The next `getUpdates(offset=N+1)` call confirms the processed update to Telegram.

## Why the previous queue was removed

An earlier design persisted every event to a dedicated `receiver-runtime` branch:

```text
inbox -> state -> consumer -> outbox -> sendMessage -> receipt
```

That design provided durable repository-side state but put multiple GitHub API reads and commits into every interactive message round-trip. Live testing showed undesirable delayed/trigger-like behavior.

On 2026-09-19 the runtime queue was removed from the hot path. The replacement is direct FIFO processing:

```text
getUpdates -> consumer -> sendMessage
```

Validation after the change:
- `TEST_D` received its reply immediately from the first update;
- a burst `1 2 3 4 5` produced replies in the same order.

The old `receiver-runtime` branch is historical evidence only and is not authoritative runtime state.

## Consumer isolation

The configured public consumer repository is cloned once per Receiver worker.

Consumer execution uses Docker with:
- no Receiver environment variables beyond the minimum container settings;
- no Telegram token;
- no GitHub token;
- no network;
- read-only filesystem;
- dropped Linux capabilities;
- `no-new-privileges`;
- unprivileged UID/GID.

The consumer reads one JSON event from stdin and writes one JSON action to stdout.

Supported actions:
- `reply`
- `no_reply`

Receiver validates the action and controls the Telegram destination.

## Telegram reply behavior

For a normal message, Receiver sends:

```text
chat_id
text
reply_parameters.message_id = original message_id
```

For topic/thread messages it additionally preserves `message_thread_id`.

The reply binding is presentation metadata only; ordering is enforced by the Receiver's sequential processing loop.

## Worker lifecycle

The Receiver uses serialized handover:

1. start;
2. preflight Telegram and consumer runtime;
3. queue one successor;
4. enter the long-poll loop;
5. run for about 5.5 hours;
6. exit;
7. queued successor starts.

GitHub Actions concurrency keeps only one Receiver worker executing at a time. A watchdog starts a new worker if the chain disappears.

## Failure model

| Failure | Behavior |
|---|---|
| consumer fails | current update is not advanced; Receiver retries after backoff |
| Telegram `sendMessage` fails | current update is not advanced; Receiver retries after backoff |
| worker dies before reply | Telegram can return the unconfirmed update to the next worker |
| worker dies after successful reply but before the next confirming `getUpdates` | the incoming update can be replayed and a duplicate reply is possible |
| worker chain disappears | watchdog requests another worker |

The duplicate window is deliberately documented rather than solved by reintroducing repository writes into the hot path.

## Deprecated architecture

The following are deprecated for message transport:
- per-update `repository_dispatch`;
- one consumer Actions run per message;
- `receiver-runtime/runtime/inbox`;
- `receiver-runtime/runtime/outbox`;
- `receiver-runtime/runtime/receipts`;
- `receiver-runtime/runtime/state.json`.

They remain relevant only as historical evidence of the investigation.
