# Receiver runtime state

This branch stores durable runtime queue state for `telegram-receiver`.

- `inbox/` — accepted Telegram updates.
- `outbox/` — consumer responses.
- `receipts/` — completed delivery records.
- `state.json` — ordered pending event IDs.

The branch is runtime storage and is never merged into `main`.
