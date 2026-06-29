"""
SMC engine parameter registry.

Every numeric knob in the engine is declared here. The 5-free-param
budget (per sharp_edges.md#curve-fitting-excuses) is enforced at
import time: more than 5 entries with kind='tunable' raises.
"""
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Param:
    name: str
    value: float
    kind: Literal["tunable", "constant"]
    doc: str

PARAMS = [
    Param("swing_pivot_bars",          10,  "tunable", "HTF-degree pivot window (swings.py)"),
    Param("internal_pivot_bars",        3,  "tunable", "LTF-degree pivot window (swings.py)"),
    Param("atr_displacement_mult",    1.5,  "tunable", "OB impulse ATR gate (order_blocks.py)"),
    Param("equal_hl_tolerance_pct", 0.001,  "tunable", "EH/EL cluster tolerance (liquidity.py)"),
    Param("fvg_min_distance_atr",    0.25,  "tunable", "Min FVG size to be tradeable (fvgs.py)"),
]

# Constants — not part of the 5-budget. These are *fixed by design* and
# must not be tuned. Adding them here makes it explicit they're locked.
CONSTANTS = [
    Param("equilibrium_pct",           0.5, "constant", "Premium/Discount equilibrium = 50%"),
    Param("bos_confirmation",          0,  "constant", "BOS rule = body-close (0 = body, 1 = wick)"),
    Param("fvg_fill_rule",             0,  "constant", "FVG fill = wick pierce"),
    Param("ob_mitigation_rule",        0,  "constant", "OB mitigation = body close through boundary"),
]

def _check_budget() -> None:
    tunables = [p for p in PARAMS if p.kind == "tunable"]
    if len(tunables) > 5:
        raise RuntimeError(
            f"Rule of 5 violated: {len(tunables)} tunable params. "
            f"Got: {[p.name for p in tunables]}. "
            f"Either lock a param to constant or merge two params."
        )

_check_budget()