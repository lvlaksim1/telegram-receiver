# Project Rules

## REQUIREMENT — strict dialogue order

A later Telegram update must never overtake an earlier update in the Receiver's processing path.

## REQUIREMENT — direct hot path

The interactive path must stay:

```text
getUpdates -> consumer -> sendMessage
```

Do not insert GitHub repository writes or separate GitHub Actions runs between these stages.

## REQUIREMENT — credential boundary

Only `telegram-receiver` may receive Telegram credentials. Consumer repositories must not receive Telegram or GitHub credentials from the Receiver.

## REQUIREMENT — isolated consumer

Consumer execution remains network-disabled, read-only, capability-dropped, no-new-privileges and unprivileged.

## REQUIREMENT — one active Receiver

GitHub Actions concurrency must serialize Receiver workers. Worker succession/watchdog behavior must not create parallel Telegram consumers.

Health checks and diagnostics must never call `getUpdates` while the Receiver architecture uses long polling.

## REQUIREMENT — recovery checkpoint

Persist recovery state only after the current event has completed. The active checkpoint is `receiver-checkpoint/state/checkpoint.json`.

A transient checkpoint failure must retry checkpoint persistence without re-running consumer logic or re-sending the Telegram reply.

## REQUIREMENT — diagnose our path first

When an inbound update is already proven to have reached Receiver promptly, investigate Receiver processing and orchestration before attributing the symptom to Telegram delivery or the user's client.

## DEPRECATED

Do not restore:
- per-update `repository_dispatch`;
- per-message consumer Actions jobs;
- the `receiver-runtime` branch as the active message queue.
