# Current Blockers and Open Risks

## OPEN — residual duplicate-reply window

A narrow duplicate window remains if Telegram accepts `sendMessage` and the Receiver process dies before the post-reply checkpoint is persisted.

This is a documented limitation, not a reason to move GitHub persistence back into the reply hot path without a new design review.

## OPEN — exact hardened-build smoke proof

The hardened build still needs one ordinary Telegram message to prove immediate reply, correct reply binding, and checkpoint advancement together on the exact current build.
