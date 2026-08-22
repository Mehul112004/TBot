# TBot file and method blueprint (redirect)

This entry point is retained for links from older plans. It was replaced on 2026-08-22 because its detailed map described files and components that no longer match the active repository.

For the maintained source map, see [Architecture and runtime — Source map for changes](../architecture.md#source-map-for-changes).

Quick navigation:

| Area | Current location |
| --- | --- |
| App composition and persistence | `backend/app/__init__.py`, `backend/app/models/db.py` |
| REST endpoints | `backend/app/blueprints/` |
| Scanner/strategy/LLM/notifications | `backend/app/core/` |
| Active strategies | `backend/app/strategies/` |
| Historical strategy and legacy SMC material | `backend/app/strategies/archive/` |
| React dashboard | `frontend/src/` |
| Tests | `backend/tests/` |

The active SMC v2 package is not a completed engine: `backend/app/core/smc/` contains its parameter registry and unimplemented public stubs. Chart SMC overlays use the archived `smc_v1` helpers through `/api/sr-zones/smc-zones`.
