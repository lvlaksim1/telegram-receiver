# Current State

Updated: 2026-09-20

## Status

The Receiver uses the accepted direct FIFO architecture with a lightweight persistent post-reply checkpoint.

Validated live before the reliability hardening:
- single message `TEST_D` received an immediate reply without requiring a second inbound message;
- burst `1 2 3 4 5` produced replies in correct order.

## Current message path

```text
getUpdates
  -> filter/validate
  -> isolated consumer
  -> validate action
  -> sendMessage
  -> persistent checkpoint
```

The user-visible reply path ends at `sendMessage`. GitHub checkpoint persistence occurs only afterward.

## Persistent recovery state

Authoritative recovery checkpoint:
- branch: `receiver-checkpoint`
- file: `state/checkpoint.json`

It stores the last completed Telegram `update_id` and is loaded at worker startup. Receiver resumes from `last_processed_update_id + 1`.

If checkpoint persistence temporarily fails, Receiver retries the checkpoint without re-running the consumer or re-sending the Telegram reply.

## Health behavior

The health workflow does **not** call `getUpdates`.

It checks:
- Telegram credentials and webhook state;
- checkpoint readability;
- presence of a live or queued Receiver workflow run.

The persistent Receiver remains the only Telegram update consumer.

## Security boundary

- Telegram secrets exist only in `telegram-receiver`.
- The consumer runs in Docker with no network, read-only filesystem, dropped capabilities, no-new-privileges and an unprivileged UID/GID.
- Consumer receives no Telegram token and no GitHub token.

## Worker lifecycle

- worker duration: approximately 5.5 hours;
- worker queues one successor;
- GitHub Actions concurrency serializes workers;
- watchdog recovers a missing worker chain.

## Regression coverage

CI covers:
- checkpoint-to-offset restoration;
- FIFO processing;
- replay deduplication from checkpoint;
- failed current update cannot be overtaken;
- checkpoint retry does not resend the Telegram reply;
- consumer contract and Telegram reply binding.

## Known limitation

A narrow duplicate-reply window remains only if:
1. Telegram accepts `sendMessage`;
2. the process dies before the post-reply checkpoint is persisted.

Do not solve this by moving GitHub persistence back in front of `sendMessage` without a new design review.

## Deprecated runtime state

The old `receiver-runtime` branch and its inbox/outbox/receipts/state files are historical evidence only. They are not authoritative runtime state.

## Live operational verification

After the hardened restart:
- Receiver run #12 entered the processing loop successfully;
- successor run #13 is queued;
- health check returned: Telegram credentials accepted, webhook inactive, checkpoint readable, active Receiver chain present;
- health completed without invoking `getUpdates`.

The checkpoint file is initialized and readable. Its first real `last_processed_update_id` will be written after the next completed Telegram update.

## Active baseline

- direct FIFO hot path;
- post-reply persistent checkpoint;
- non-consuming health check;
- one active Receiver update consumer;
- isolated consumer repository.
