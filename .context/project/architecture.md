# Project Architecture

## Accepted direct FIFO path

```text
Telegram getUpdates
  -> filter/validate
  -> isolated consumer
  -> validate action
  -> Telegram sendMessage
  -> persistent checkpoint
```

The user-visible hot path ends at `sendMessage`. The checkpoint is written afterward.

## Isolation

The consumer executes in a restricted Docker container with no network, read-only filesystem, dropped capabilities, no-new-privileges, unprivileged UID/GID, and no Telegram/GitHub credentials.

## Runtime/recovery state

- authoritative inbound queue: Telegram;
- persistent recovery checkpoint: `receiver-checkpoint/state/checkpoint.json`;
- worker succession/watchdog keeps a Receiver chain alive;
- GitHub Actions concurrency prevents parallel Receiver consumers;
- old `receiver-runtime` branch is deprecated historical evidence only.
