# Decision — Post-reply persistent checkpoint

Date: 2026-09-20
Status: accepted

## Problem

The direct FIFO architecture fixed latency and ordering, but the worker kept its Telegram offset only in RAM.

On a normal restart, a new worker could therefore begin with `offset=None`. That left completed updates vulnerable to replay and duplicate processing.

A second defect was found in health diagnostics: the health workflow called `getUpdates`, creating a second Telegram update consumer alongside the live Receiver.

## Decision

Keep the interactive path unchanged:

```text
getUpdates -> isolated consumer -> sendMessage
```

After the update has completed, persist one lightweight checkpoint:

```text
sendMessage -> receiver-checkpoint/state/checkpoint.json
```

The checkpoint stores the last completed `update_id`, final action, Telegram message ID when applicable, and update time.

On startup, Receiver resumes from:

```text
last_processed_update_id + 1
```

## Failure behavior

A transient checkpoint write failure is retried **without** re-running the consumer and without re-sending the Telegram reply.

The checkpoint is deliberately after `sendMessage`, so GitHub persistence cannot delay the first visible reply to the user.

There remains one narrow unavoidable window: if the process dies after Telegram accepts `sendMessage` but before the checkpoint write succeeds, that update can be replayed after restart.

## Health rule

Health checks must never call `getUpdates`.

Health may check:
- Telegram credentials via `getMe`;
- webhook state via `getWebhookInfo`;
- persistent checkpoint readability;
- presence of a live or queued Receiver worker.

## Regression coverage

Automated tests must cover:
- checkpoint-to-offset restoration;
- FIFO processing;
- replay deduplication from checkpoint;
- failed current update cannot be overtaken;
- checkpoint retry does not resend the reply.
