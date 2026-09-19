# Latest Handoff

Date: 2026-09-20
Project: `lvlaksim1/telegram-receiver`
Branch: `main`

## Accepted baseline

The active Telegram transport architecture is:

```text
getUpdates -> isolated consumer -> sendMessage -> persistent checkpoint
```

The first three stages are the realtime hot path. The checkpoint is post-reply recovery state and must remain outside the user-visible response path.

## What is proven

Live validation before the recovery hardening confirmed:
- `TEST_D` replied immediately without a second trigger message;
- replies for `1 2 3 4 5` arrived in correct order.

The direct FIFO fix is therefore the accepted realtime/order baseline.

## Reliability hardening completed

A project audit found three remaining gaps and corrected them:

1. **Persistent offset/dedup**  
   Added branch `receiver-checkpoint` with `state/checkpoint.json`. Worker startup resumes from `last_processed_update_id + 1`.

2. **Competing health consumer**  
   Removed `getUpdates` from health diagnostics. Health now checks `getMe`, webhook state, checkpoint readability and active Receiver workflow state.

3. **Regression coverage**  
   Added tests for FIFO, restart offset, replay deduplication, failed-current-update ordering and checkpoint retry without resend.

Checkpoint writes occur only after the consumer/send stage. If a checkpoint write fails transiently, Receiver retries the checkpoint in place and does not run consumer/send again.

## Important exclusions

Do not:
- restore one GitHub Actions run per Telegram update;
- put GitHub repository reads/writes between `getUpdates` and `sendMessage`;
- let health or diagnostics call `getUpdates`;
- treat the old `receiver-runtime` branch as current state;
- move Telegram credentials into the consumer repository.

## Known limitation

A narrow duplicate window remains if the process dies after successful Telegram `sendMessage` but before the post-reply checkpoint succeeds. This is explicitly documented.

## Current recovery state

- branch: `receiver-checkpoint`
- path: `state/checkpoint.json`

## Next verification

After the worker is restarted on this hardened baseline:
1. run `[RECEIVER_HEALTHCHECK]`;
2. send one ordinary Telegram message and confirm immediate reply + reply binding;
3. optionally send a short burst and confirm order remains unchanged.

If these pass, continue development from this baseline.
