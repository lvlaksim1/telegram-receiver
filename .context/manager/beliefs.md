# Manager beliefs

## Owner-authorized manager installation

The owner explicitly authorized installation of a persistent Project Manager into this repository,
which previously used standalone Context Capsule Core v1.3.1.

- source: repo-factory command `[UPGRADE_CONTEXT_CAPSULE_TO_PROJECT_MANAGER]`
- authority: owner-directive

## Preserved durable project context

The pre-existing project identity, goals, architecture, constraints, current working views, rules,
decisions, dialogues, history, and handoff state are preserved as repository evidence and must be
reconciled before consequential action.

- source: repository state at `26b8d80b37b9d1d2f1a26a5dc6156bfa4d5671a6` on `main`
- authority: verified-repository

## Product coordinates

The installed durable-context base is Context Capsule Core v1.3.1 at
`lvlaksim1/context-capsule@2ef41a5ed57ae514cc5980065560d7e55d5e4b9a`. The Project Manager implementation is
`lvlaksim1/context-capsule-project-manager@9d6a2f69d38d880c44ea59c9b3d31b406cc5bcf1`.

- source: `repo-factory/components.lock.json`
- authority: verified-repository

## Branch authority

Manager state authority is `main`; product baseline authority is
`main`. Changing either authority requires explicit reconciliation and must not
happen implicitly.

- source: preserved Context Capsule branch topology and explicit upgrade
- authority: verified-repository
