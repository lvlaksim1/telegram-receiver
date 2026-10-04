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
## Context Capsule Project Manager

Before substantial work, reinstate the Project Manager from `.context/ENTRYPOINT.md`.

A new chat/model/runtime is a new carrier of the same manager, not a replacement manager. Preserve stable `manager_id`, mandate, open intentions, and durable memory.

Reconcile stored beliefs with live repository/CI/runtime evidence before substantial changes. Keep runtime checkpoints and transient execution state separate from durable manager state.

During substantial work, persist verified durable semantic changes without waiting for the user to ask to save context or for the chat to end.
<!-- context-capsule:end -->
