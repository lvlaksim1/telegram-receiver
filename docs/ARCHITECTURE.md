# Architecture

## Purpose

`telegram-receiver` is a receive-only transport gateway:

```text
Telegram Bot API -> GitHub Actions receiver -> repository_dispatch -> consumer repository
```

It deliberately contains no application commands, AI logic, reply generation or Telegram send operations.

## Core invariants

1. **Only one active `getUpdates` consumer.**  
   Receiver workflow runs share one GitHub Actions concurrency group.

2. **Dispatch before confirmation.**  
   An update is forwarded to the consumer before the receiver advances the Telegram offset past that update.

3. **Prefer duplicates over loss.**  
   A crash after GitHub accepts the event but before Telegram confirmation can cause redelivery. Consumers deduplicate by `update_id`.

4. **No runner-local state is authoritative.**  
   A GitHub-hosted runner may disappear at any time. Correctness must not depend on files, SQLite, RAM or caches on that runner.

5. **Telegram remains the inbound queue.**  
   Unconfirmed updates remain at Telegram. The receiver does not copy message bodies into the public repository.

6. **Webhook configuration is never changed automatically.**  
   If a webhook exists, preflight fails instead of deleting it.

7. **No message body in operational logs.**  
   Logs may include `update_id`, chat ID and counters, but not Telegram message text or the raw update object.

8. **Transport boundary is GitHub event acceptance.**  
   HTTP 204 from `repository_dispatch` means the receiver considers the update delivered to GitHub. Successful execution of the consumer workflow is a separate responsibility.

## Worker lifecycle

GitHub-hosted jobs have a finite execution window. A receiver worker therefore runs for approximately 5.5 hours.

On startup:

1. checkout current default branch;
2. verify `enabled=true`;
3. validate required secrets/configuration;
4. verify the Telegram bot and ensure no webhook is active;
5. verify access to the consumer repository;
6. queue exactly one successor run;
7. enter Telegram long polling.

The successor is held by the shared concurrency group while the current worker runs. When the current worker exits, the queued successor becomes eligible to start.

A separate watchdog checks every 15 minutes. If the receiver is enabled but neither an active nor queued receiver run exists, it requests a new worker.

## Telegram offset rule

For update `N`:

```text
getUpdates -> receive N
repository_dispatch(N) -> must return 204
next offset becomes N + 1
next getUpdates(offset=N+1) -> confirms N at Telegram
```

If dispatch fails, offset is not advanced past that update.

If the runner dies after dispatch succeeds but before confirmation, Telegram can redeliver `N`. This is intentional at-least-once behavior.

## Failure model

| Failure | Receiver behavior | Consequence |
|---|---|---|
| Runner dies before dispatch | Telegram update stays unconfirmed | successor retries |
| GitHub dispatch API fails | offset is not advanced | same update retries with backoff |
| Runner dies after dispatch but before confirmation | Telegram can redeliver | possible duplicate |
| Consumer workflow fails after dispatch was accepted | receiver does not know | consumer owns retry/idempotency |
| Worker chain disappears | watchdog requests a worker | temporary latency |
| Telegram webhook exists | preflight fails | no destructive webhook change |
| GitHub/receiver unavailable for more than Telegram retention window | Telegram may discard old updates | possible loss |

Telegram documents that pending updates are retained for no longer than 24 hours. Therefore GitHub-only operation cannot guarantee recovery from an outage longer than that without adding a separate durable inbox.

## Security model

Secrets:

- `TELEGRAM_BOT_TOKEN` — Telegram credential.
- `TELEGRAM_CHAT_ID` — optional/standard chat allow-list value.
- `CONSUMER_DISPATCH_TOKEN` — dedicated GitHub credential for dispatching to the consumer repository.

The high-privilege `REPO_FACTORY_TOKEN` must never be copied into this repository.

The consumer dispatch credential should have only the GitHub permissions needed for `POST /repos/{owner}/{repo}/dispatches`.

## Public repository considerations

The repository can remain public because:

- secret values are stored only as GitHub Actions secrets;
- raw Telegram updates are not committed;
- receiver logs do not print raw update bodies;
- runtime state is operational metadata only.

A consumer may still handle sensitive Telegram content, so its own visibility and logging policy must be chosen separately.

## Current known boundary

The current design guarantees at-least-once delivery **to GitHub's repository-dispatch endpoint**, not successful business processing by the consumer. End-to-end acknowledgement would require a return credential/channel from the consumer and is intentionally outside the receive-only transport MVP.
