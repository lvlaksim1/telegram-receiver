# Decision — Direct FIFO hot path

Date: 2026-09-19
Status: accepted; supersedes per-update dispatch and repository-runtime-queue message paths.

## Problem

Two successive designs introduced avoidable orchestration into the interactive message path.

### Superseded design A: per-update GitHub Actions

```text
Telegram -> Receiver -> repository_dispatch -> separate consumer Actions run -> Telegram
```

Observed failure:
- later update runs could start before earlier update runs;
- replies could therefore appear out of order;
- an earlier reply could appear only after a later user message had already been sent.

This violated strict conversation ordering.

### Superseded design B: durable GitHub runtime queue

```text
getUpdates -> GitHub inbox/state -> consumer -> GitHub outbox -> sendMessage -> GitHub receipt
```

This removed independent per-message runners but inserted multiple GitHub API reads/commits into every interactive round-trip.

During live testing, the user still observed delayed/trigger-like reply behavior.

## Decision

Use Telegram as the inbound queue and keep the hot path synchronous:

```text
getUpdates -> consumer -> sendMessage
```

Within each returned batch:
1. sort by numeric `update_id`;
2. process exactly one update at a time;
3. do not move to the next update until the current consumer action and Telegram send complete.

## Evidence

After deployment:
- `TEST_D` received its reply immediately on the first message;
- `1 2 3 4 5` received replies in the same order.

The behavioral defect disappeared when the GitHub runtime queue was removed from the hot path.

## Guardrail

Do not reintroduce repository writes, per-message workflow dispatch, or parallel consumer runs between `getUpdates` and `sendMessage`.

Durability/recovery improvements must preserve the direct interactive path.
