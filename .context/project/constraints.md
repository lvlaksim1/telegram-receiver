# Project Constraints

- Preserve strict numeric-`update_id` FIFO processing.
- Do not restore per-update `repository_dispatch` or per-message GitHub Actions jobs.
- Do not insert GitHub repository reads/writes between `getUpdates` and `sendMessage`.
- Health and diagnostics must never call `getUpdates`.
- Only `telegram-receiver` may hold Telegram credentials; consumer repositories receive neither Telegram nor GitHub credentials.
- Checkpoint persistence occurs only after consumer processing and Telegram send complete.
- A transient checkpoint write failure retries persistence without re-running consumer logic or re-sending the reply.
- When inbound delivery is already proven prompt, diagnose Receiver processing/orchestration before blaming Telegram or the client.
