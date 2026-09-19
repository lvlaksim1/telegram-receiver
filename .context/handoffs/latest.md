# Latest Handoff

Date: 2026-09-19
Project: `lvlaksim1/telegram-receiver`
Branch: `main`

## What was fixed

The core Telegram dialogue defect was traced back to Receiver architecture, not inbound Telegram reception.

Incoming user updates were reaching the Receiver/GitHub side promptly. The broken behavior was created after receipt:
- the original per-update `repository_dispatch` architecture allowed independent GitHub Actions runs to overtake one another;
- the subsequent durable `receiver-runtime` design eliminated that race but put GitHub API persistence directly in the message hot path.

The hot path was simplified to:

```text
getUpdates -> isolated consumer -> sendMessage
```

Updates are processed sequentially in numeric `update_id` order.

## Live verification

Confirmed by the user:
- `TEST_D` reply arrived immediately;
- replies for `1 2 3 4 5` arrived in correct order.

This is the current accepted baseline.

## Cleanup completed

- removed temporary `direct-telegram-diagnostic.yml`;
- removed temporary `direct-pair-diagnostic.yml`;
- removed GitHub runtime queue code/config/tests from the active implementation;
- updated README and `docs/ARCHITECTURE.md`;
- restored Telegram `reply_parameters` on top of the fixed direct FIFO path;
- created the Project Context Capsule.

## Important exclusions

Do not:
- restore one GitHub Actions run per Telegram update;
- put GitHub Contents/API commits back between inbound update and outbound reply;
- treat `receiver-runtime` as current state;
- move Telegram credentials into the consumer repository.

## Known limitation

If the worker dies after a successful reply but before Telegram receives the next confirming offset, that update can be replayed and a duplicate reply is possible.

## Next check

After worker restart on the cleanup commit, perform one ordinary Telegram message and verify:
1. immediate response;
2. visible reply binding to the original message;
3. no second trigger message required.

If that passes, continue from this architecture rather than reopening the discarded queue designs.
