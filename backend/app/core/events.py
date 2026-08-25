"""Canonical import surface for temporal market events.

The implementations pre-date the v3 core package and still live in the SMC
archive.  Active strategies and tests import them from ``app.core.events``;
keeping this small facade makes that public contract explicit and prevents a
missing module from being silently swallowed by historical scans.
"""

from app.strategies.archive.smc_v1.events import (
    detect_choch,
    detect_liquidity_sweep,
    detect_volume_climax,
)

__all__ = [
    "detect_choch",
    "detect_liquidity_sweep",
    "detect_volume_climax",
]
