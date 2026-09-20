# Context Capsule Protocol

## Purpose

The capsule preserves the project meaning needed to continue work safely in a new chat without reconstructing decisions from old workflow runs.

## Read order

1. `.context/ENTRYPOINT.md`
2. `.context/handoffs/latest.md`
3. `.context/current/state.md`
4. applicable `.context/rules/*`
5. relevant `.context/decisions/*`
6. dialogue records only when historical detail is needed

## Record types

Use the following semantics:
- **FACT** — verified observation;
- **DECISION** — accepted architecture or implementation choice;
- **REQUIREMENT** — behavior that must hold;
- **PREFERENCE** — user preference that affects implementation;
- **HYPOTHESIS** — unverified explanation;
- **BLOCKER** — condition preventing progress;
- **OPEN** — unresolved work;
- **DEPRECATED** — old approach retained only for history.

## Update rules

- Record significant changes, not every conversational message.
- Never silently rewrite history when a design changes.
- Mark old approaches as deprecated/superseded and link to the replacement decision.
- Keep secrets, tokens and unnecessary personal data out of the capsule.
- Before handoff, update current state and `handoffs/latest.md`.
- Git/code is the source of implementation facts; the capsule explains why the implementation is that way and where work should resume.
