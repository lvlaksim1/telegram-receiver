# Project Goals

## Primary goal

Provide prompt two-way Telegram communication while preserving strict FIFO ordering and isolating consumer code from Telegram/GitHub credentials.

## Durable outcomes

- one persistent Receiver is the only `getUpdates` consumer;
- replies are produced without waiting for a later inbound message;
- a later update never overtakes an earlier one;
- GitHub persistence stays outside the user-visible reply hot path;
- recovery survives Receiver worker restarts through the post-reply checkpoint;
- health/diagnostic operations do not consume Telegram updates.
