# Planning backlog

**Status: planning material, reviewed 2026-08-22.** This is not a current feature inventory or delivery schedule. The current implementation is documented in [the documentation index](README.md); a proposed item becomes a product change only after its design, validation, implementation, tests, and current docs are updated.

## Candidate future research areas

| Area | Idea | Current relationship to the application |
| --- | --- | --- |
| Volume-profile levels | Add volume-at-price / high-volume-node analysis as an additional level source | Not part of the persisted S/R engine, which currently uses swings and psychological levels |
| SMC v2 | Build the planned multi-timeframe SMC engine with validations | Design material is in `docs/SMC-Engine/`; public context/engine APIs are not implemented |
| Feature/confluence research | Test spatial, temporal, and regime features in a disciplined scoring framework | Earlier proposal is in `docs/confluence_plans/`; not a live generic confluence engine |
| Strategy IDE/settings | Add a browser workflow for custom strategies or richer configuration | Historical Phase 8/9 documents describe this as planned; no current frontend IDE exists |
| Research validation | Add systematic walk-forward/regime/held-out experiment tooling | Current backtester is a deterministic simulator; see [backtesting guidance](backtesting.md) |

## How to promote a backlog item

1. State the hypothesis, user/operational value, and intended source boundary.
2. Define data requirements, testable contract, risks, and documentation changes.
3. Build it on a branch with focused tests and a reproducible research manifest if it changes signal logic.
4. Validate it on data separated from the development/tuning sample where appropriate.
5. After integration, move its description into the current architecture/strategy/API/operations docs and record any remaining work here.

The detailed prose previously held in this file has been retained conceptually as planning ideas, but it referred to earlier proposed modules. Consult the historical plan directly only when deliberately resuming that proposal.
