# Agent Instructions

Before changing this repository, restore project context from:

1. `.context/ENTRYPOINT.md`
2. `.context/handoffs/latest.md`

The current accepted Telegram message path is direct FIFO:

```text
getUpdates -> isolated consumer -> sendMessage
```

Do not reintroduce per-message GitHub Actions runs or GitHub repository writes into the interactive hot path.

Recovery state belongs only in the post-reply `receiver-checkpoint/state/checkpoint.json` checkpoint. Health/diagnostic code must never call `getUpdates`.
