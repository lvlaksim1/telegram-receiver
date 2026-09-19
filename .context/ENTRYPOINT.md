# Project Context Capsule — telegram-receiver

## Authority

- Repository: `lvlaksim1/telegram-receiver`
- Authoritative branch: `main`
- Runtime history branch `receiver-runtime`: **deprecated historical evidence only**
- Current consumer: `lvlaksim1/telegram-receiver-test-consumer`

## Restore order

When continuing this project in a new chat:

1. read this file;
2. read `.context/handoffs/latest.md`;
3. read `.context/current/state.md`;
4. read relevant records in `.context/decisions/`;
5. verify current `main`, active Receiver workflow and CI before editing.

## Current architecture

The authoritative interactive path is:

```text
Telegram getUpdates
      ↓
one persistent Receiver worker
      ↓
one isolated consumer invocation
      ↓
Telegram sendMessage
```

Rules:
- one Receiver worker processes messages sequentially;
- updates are ordered by numeric `update_id`;
- no per-message GitHub Actions run;
- no per-message `repository_dispatch`;
- no GitHub Contents/API queue in the hot path;
- consumer receives neither Telegram nor GitHub credentials;
- Receiver owns destination selection and Telegram reply binding.

## Context semantics

Record significant project facts, decisions, requirements, rejected approaches, blockers and handoff state. Do not erase old decisions when architecture changes; mark them superseded/deprecated and point to the replacement.

See `.context/decisions/2026-09-19-direct-fifo.md` for the decisive architecture correction.
