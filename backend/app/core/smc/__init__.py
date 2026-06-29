"""
SMC Engine v2.0 — multi-timeframe Smart Money Concepts.

Public API:
    run_smc_analysis(df_15m, htf_data, symbol) -> pd.DataFrame
    SMContext (frozen dataclass)
"""
from .engine import run_smc_analysis
from .context import SMContext

__all__ = ["run_smc_analysis", "SMContext"]