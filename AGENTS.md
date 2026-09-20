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

<!-- context-capsule:begin -->
## Context Capsule

Before substantial work, restore project context from `.context/ENTRYPOINT.md`.

Follow `.context/manifest.json` for actual project-context paths. Reconcile stored context with live repository/CI/runtime evidence before making substantial changes.

Do not send project context to Context Capsule Core.

During substantial work, persist significant durable project changes when verified meaning changes. Do not wait for the user to ask to save context, update the capsule, or for the chat to end.
<!-- context-capsule:end -->
