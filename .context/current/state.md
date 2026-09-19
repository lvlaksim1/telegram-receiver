# Current State

Updated: 2026-09-19

## Status

The Receiver is operational on the direct FIFO architecture.

Validated live before cleanup:
- single message `TEST_D` received an immediate reply without requiring a second inbound message;
- burst `1 2 3 4 5` produced replies in correct order.

## Current message path

```text
getUpdates -> filter/validate -> isolated consumer -> validate action -> sendMessage
```

No repository storage operation occurs between receiving an update and sending its reply.

## Security boundary

- Telegram secrets exist only in `telegram-receiver`.
- The consumer runs in Docker with no network, read-only filesystem, dropped capabilities, no-new-privileges and an unprivileged UID/GID.
- Consumer receives no Telegram token and no GitHub token.

## Worker lifecycle

- worker duration: approximately 5.5 hours;
- worker queues one successor;
- GitHub Actions concurrency serializes workers;
- watchdog recovers a missing worker chain.

## Known limitation

A narrow duplicate-reply window remains if:
1. Telegram accepts `sendMessage`;
2. the worker dies before the next `getUpdates(offset=...)` confirms the incoming update.

Do not solve this by restoring GitHub repository writes to the interactive hot path without a new design review.

## Deprecated runtime state

The `receiver-runtime` branch and its `runtime/inbox`, `outbox`, `receipts`, and `state.json` files are historical evidence. They are no longer authoritative runtime state.

## Cleanup status

Temporary direct Telegram diagnostic workflows were removed.
README and architecture documentation were updated for direct FIFO.
Telegram `reply_parameters` binding was restored after the ordering fix; unit coverage verifies the payload. Live post-cleanup verification is the next small check.
