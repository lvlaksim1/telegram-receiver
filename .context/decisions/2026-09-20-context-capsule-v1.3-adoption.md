# DECISION — Adopt Context Capsule Core v1.3

Date: 2026-09-20
Status: active

The existing telegram-receiver Project Context Capsule is adopted into Context Capsule Core v1.3 without reinstalling or discarding its compact project-specific history.

The authoritative project branch remains `main`. The old `receiver-runtime` branch remains deprecated. Runtime recovery state remains the separate `receiver-checkpoint/state/checkpoint.json` checkpoint.

Legacy entrypoint/protocol are archived under `.context/history/`; existing project rules, decisions, dialogues, current state and handoff are preserved. Missing stable project semantics and compact blockers/next files are materialized from already verified repository context.

Core provenance: `1018129caa6aae0677741c1da62504cf2ae3904e`.
