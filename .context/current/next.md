# Next Actions

1. Send one ordinary Telegram message through the current hardened Receiver.
2. Verify the reply arrives immediately without requiring another inbound message.
3. Verify reply binding points to the originating Telegram message.
4. Verify `receiver-checkpoint/state/checkpoint.json` advances to the completed `update_id`.
5. If all four checks pass, record the hardened recovery build as live-verified; otherwise diagnose the Receiver path first.
