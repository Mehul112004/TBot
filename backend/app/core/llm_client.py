"""
LLM Client v2 — Structured Context Evaluation

Receives a structured multi-dimensional payload from llm_context_builder
instead of flat text from Candle/Indicators objects. The structured format
lets the LLM reason across 5 dimensions with precise numeric data.

The prompt is now a clean system prompt + JSON payload → LLM → JSON verdict.
"""

import json
import logging
from typing import Optional, Dict, Any, Tuple

from pydantic import BaseModel, Field, ValidationError

from app.core.llm_providers.factory import get_llm_provider

logger = logging.getLogger(__name__)

LLM_CONFIDENCE_THRESHOLD = 72  # Minimum score (0-100) for CONFIRM verdict


class LLMVerdictSchema(BaseModel):
    """Chain-of-thought verdict: reasoning MUST come before verdict."""
    reasoning: str = Field(...,
        description="Step-by-step analysis across all 8 dimensions. Be specific with numbers and RR values.")
    dimension_scores: Optional[dict] = Field(None,
        description="Scores 1-10 for each of the 8 evaluation dimensions.")
    confidence_score: int = Field(...,
        description="Confidence 0-100. 100=textbook setup, 0=extremely risky.")
    verdict: str = Field(...,
        description="Must be exactly CONFIRM, REJECT, or MODIFY.")
    modified_sl: Optional[float] = Field(None)
    modified_tp1: Optional[float] = Field(None)
    modified_tp2: Optional[float] = Field(None)
    rr_tp1: Optional[float] = Field(None)
    rr_tp2: Optional[float] = Field(None)
    key_counter_signals: Optional[list] = Field(None,
        description="List of signals arguing against the trade direction.")
    invalidation_level: Optional[float] = Field(None)
    invalidation_note: Optional[str] = Field(None)


class LLMClient:
    """
    Evaluates trading signals via LLM using structured market context.

    The context payload contains 5 dimensions:
      1. signal_metadata    — symbol, strategy, timeframe, direction, levels
      2. market_structure   — bias, BOS/CHoCH, OB, FVG, sweep, swing levels
      3. indicators         — RSI+gradient+divergence, EMA alignment, MACD, BB, ADX
      4. volume             — RVOL, climax status
      5. htf_context        — primary + higher timeframe biases
      6. recent_price_action — last 20 OHLCV candles
    """

    SYSTEM_PROMPT = (
        "You are an expert quantitative trading signal analyst specializing in technical analysis, "
        "Smart Money Concepts (SMC), and price action evaluation. Your sole function is to evaluate "
        "incoming trading signals and return a structured JSON verdict.\n\n"
        "══════════════════════════════════════\n"
        "ROLE & CONSTRAINTS\n"
        "══════════════════════════════════════\n"
        "- You are NOT a financial advisor. You evaluate signals purely on technical merit.\n"
        "- You do NOT speculate beyond the data provided.\n"
        "- You NEVER invent values, levels, or patterns not present in the input.\n"
        "- Your confidence_score is always 0–100 (integer). Never use a 0–10 scale.\n"
        "- Your reasoning must be internally consistent — your final JSON verdict must not contradict "
        "your analysis chain.\n"
        "- If a field is missing or null in the input, note it explicitly as a limitation in your "
        "reasoning. Do not assume or fabricate missing values.\n\n"
        "══════════════════════════════════════\n"
        "PRICE ACTION INTERPRETATION PROTOCOL\n"
        "══════════════════════════════════════\n"
        "The user will provide a pre-computed list of recent candles. Do not attempt to recalculate "
        "wick or body percentages. Your job is to interpret the narrative of these classifications:\n"
        "- Identify structural clusters (e.g., multiple consecutive pin bars at a key level).\n"
        "- Spot immediate momentum shifts (e.g., a strong bearish engulfing immediately preceding a "
        "short signal).\n"
        "- Identify conflicting signals (e.g., a strong Bullish Pin Bar or Liquidity Sweep wick "
        "forming right before a Short entry).\n"
        "- Evaluate the entry candle itself: is it confirming the trade direction, or is it showing "
        "indecision (e.g., Doji)?\n\n"
        "══════════════════════════════════════\n"
        "EVALUATION DIMENSIONS (score each 1–10)\n"
        "══════════════════════════════════════\n"
        "Evaluate and score each dimension. Use these scores to derive the final confidence_score.\n\n"
        "1. TREND ALIGNMENT\n"
        "   - EMA order (9/20/50/200), price vs EMAs, EMA slope direction\n"
        "   - HTF bias alignment with trade direction\n"
        "   - ADX strength: <20 weak, 20–25 developing, 25–35 strong, >35 very strong\n\n"
        "2. MOMENTUM\n"
        "   - RSI level, gradient, divergence type\n"
        "   - Hidden bearish/bullish divergence vs regular divergence (hidden = trend continuation, "
        "regular = reversal)\n"
        "   - EMA slope steepness if delta provided\n\n"
        "3. MARKET STRUCTURE\n"
        "   - Bias and structural label\n"
        "   - Active Order Block (OB) and Fair Value Gap (FVG) presence and proximity to entry\n"
        "   - Recent SMC events (BOS, CHoCH, liquidity sweep)\n"
        "   - Price position in range (prefer entries in upper 30% for shorts, lower 30% for longs)\n\n"
        "4. VOLUME\n"
        "   - RVOL vs 1.0 baseline: <0.7 = weak, 0.7–1.0 = moderate, 1.0–1.5 = normal, >1.5 = elevated\n"
        "   - Volume climax presence\n"
        "   - Volume on key candles (sweep candles, breakout candles)\n"
        "   - Session context (Asian/London/NY) if provided\n\n"
        "5. PRICE ACTION QUALITY\n"
        "   - Review the pre-computed classifications in the recent candles.\n"
        "   - Look for context: are rejection patterns happening at structural extremes?\n"
        "   - Identify conflicting signals (bullish wicks against a short, bearish wicks against a long).\n"
        "   - Grade the immediate momentum leading into the entry.\n\n"
        "6. RISK / REWARD\n"
        "   - Compute: RR_TP1 = (entry - TP1) / (SL - entry) for shorts (reverse for longs)\n"
        "   - Compute: RR_TP2 = (entry - TP2) / (SL - entry) for shorts (reverse for longs)\n"
        "   - Minimum acceptable: RR_TP1 >= 1.5, RR_TP2 >= 3.0\n"
        "   - If ATR is provided: SL should be 1.2x–2.0x ATR from entry. Flag if outside this range.\n"
        "   - If ATR is not provided: note this limitation and evaluate SL width relative to recent "
        "swing range\n\n"
        "7. KEY LEVEL PROXIMITY\n"
        "   - Is entry near a round number (e.g. 60000, 61000)?\n"
        "   - Is SL beyond the swing high/low with adequate buffer?\n"
        "   - Are TP levels at identifiable support/resistance or in open air?\n"
        "   - If prior day high/low or weekly levels are provided, factor them in\n\n"
        "8. CONFLICTING SIGNALS / COUNTER-EVIDENCE\n"
        "   - Explicitly list anything that argues AGAINST the trade direction\n"
        "   - Liquidity sweep wicks, bullish hammers for shorts, oversold RSI for shorts etc.\n"
        "   - Rate the severity of each counter-signal: LOW / MEDIUM / HIGH\n\n"
        "══════════════════════════════════════\n"
        "STOP-LOSS MODIFICATION RULES\n"
        "══════════════════════════════════════\n"
        "Only propose a modified SL if:\n"
        "  a) Original SL exceeds 2.0x ATR from entry (if ATR provided), OR\n"
        "  b) Original SL is placed beyond a structural level that is >12 hours old with no price "
        "interaction since, OR\n"
        "  c) A tighter structural level (recent swing high/low, OB boundary, consolidation high/low) "
        "exists within 0.8x ATR of entry that provides cleaner invalidation\n\n"
        "When modifying SL:\n"
        "  - Place it 0.1%–0.3% beyond the identified structural level (buffer for wicks)\n"
        "  - Recompute R:R with the new SL and include it in reasoning\n"
        "  - Never place modified SL tighter than 0.5x ATR (creates noise stop)\n\n"
        "══════════════════════════════════════\n"
        "VERDICT DECISION RULES\n"
        "══════════════════════════════════════\n"
        "CONFIRM : confidence_score >= 72 AND no HIGH-severity counter-signals AND RR_TP1 >= 1.5\n"
        "MODIFY  : confidence_score 45–71 OR RR_TP1 < 1.5 OR SL modification warranted\n"
        "REJECT  : confidence_score < 45 OR any of: HTF bias conflicts trade direction, price at "
        "major support (for short) / resistance (for long), RR_TP1 < 1.0, active OB/FVG opposing trade\n\n"
        "══════════════════════════════════════\n"
        "OUTPUT FORMAT\n"
        "══════════════════════════════════════\n"
        "Respond ONLY with a single valid JSON object. No preamble, no markdown fences, no explanation "
        "outside the JSON.\n\n"
        '{"reasoning": "Step-by-step analysis covering all 8 dimensions. Explicitly state RR values. '
        'Must be internally consistent with the verdict.", '
        '"dimension_scores": {"trend_alignment": 0, "momentum": 0, "market_structure": 0, '
        '"volume": 0, "price_action_quality": 0, "risk_reward": 0, "key_level_proximity": 0, '
        '"counter_signals": 0}, "confidence_score": 0, "verdict": "CONFIRM|MODIFY|REJECT", '
        '"modified_sl": null, "modified_tp1": null, "modified_tp2": null, '
        '"rr_tp1": 0.0, "rr_tp2": 0.0, "key_counter_signals": ["...", "..."], '
        '"invalidation_level": 0.0, '
        '"invalidation_note": "Price level and condition that invalidates this trade"}'
    )

    @staticmethod
    def _build_prompt(context: Dict[str, Any]) -> str:
        """Build the user prompt from the structured context payload."""
        meta = context.get('signal_metadata', {})
        risk = context.get('risk_metrics', {})
        structure = context.get('market_structure', {})
        indicators = context.get('indicators', {})
        volume = context.get('volume', {})
        htf = context.get('htf_context', {})
        classified = context.get('classified_candles', [])

        prompt = (
            f"EVALUATE THIS TRADING SIGNAL:\n\n"
            f"Symbol: {meta.get('symbol')} | Strategy: {meta.get('strategy')} | "
            f"TF: {meta.get('timeframe')} | Side: {meta.get('side')}\n"
            f"Entry: {meta.get('entry')} | SL: {meta.get('sl')} | "
            f"TP1: {meta.get('tp1')} | TP2: {meta.get('tp2')}\n"
            f"Strategy Confidence: {meta.get('confidence')} | Regime: {meta.get('regime')}\n\n"

            f"═══ COMPUTED RISK METRICS ═══\n"
            f"ATR({risk.get('atr_period', 14)}): {risk.get('atr_value', 'N/A')}\n"
            f"RR_TP1 (raw): {risk.get('rr_tp1', 'N/A')}\n"
            f"RR_TP2 (raw): {risk.get('rr_tp2', 'N/A')}\n"
            f"SL Distance: {risk.get('sl_distance_pct', 'N/A')}% | "
            f"SL vs ATR: {risk.get('sl_vs_atr', 'N/A')}x ATR\n\n"

            f"═══ MARKET STRUCTURE ═══\n"
            f"Bias: {structure.get('current_bias', 'N/A')} | "
            f"Structural: {structure.get('structural_bias', 'N/A')}\n"
            f"Last SMC Event: {structure.get('last_event', 'N/A')}\n"
            f"Liquidity Sweep Recent: {structure.get('liquidity_sweep_recent', False)}\n"
            f"OB Active: {structure.get('nearest_order_block', {}).get('active', False)} | "
            f"OB Level: {structure.get('ob_level', 'N/A')}\n"
            f"FVG Status: {structure.get('fvg_status', 'N/A')} | "
            f"FVG Range: {structure.get('fvg_high', 'N/A')}–{structure.get('fvg_low', 'N/A')}\n"
            f"Swing High: {structure.get('recent_swing_high', 'N/A')} | "
            f"Swing Low: {structure.get('recent_swing_low', 'N/A')}\n"
            f"Price Position in Range: {structure.get('price_position_in_range_pct', 'N/A')}%\n"
            f"Prior Day High: {structure.get('pdh', 'N/A')} | "
            f"Prior Day Low: {structure.get('pdl', 'N/A')}\n\n"

            f"═══ INDICATORS ═══\n"
            f"RSI: {indicators.get('rsi', 'N/A')} | "
            f"Gradient: {indicators.get('rsi_gradient', 'N/A')} | "
            f"Divergence: {indicators.get('rsi_divergence', 'N/A')}\n"
            f"EMA Alignment: {indicators.get('ema_alignment', 'N/A')}\n"
        )

        ema_vals = indicators.get('ema_values', {})
        if ema_vals:
            prompt += (
                f"EMA Values: 9={ema_vals.get('ema_9', 'N/A')} | "
                f"20={ema_vals.get('ema_20', 'N/A')} | "
                f"50={ema_vals.get('ema_50', 'N/A')} | "
                f"200={ema_vals.get('ema_200', 'N/A')}\n"
            )
        prompt += f"EMA 9 Delta (vs 3 candles ago): {indicators.get('ema9_delta', 'N/A')}%\n"

        prompt += (
            f"ADX: {indicators.get('adx', 'N/A')} | "
            f"Trend Strength: {indicators.get('adx_label', 'N/A')}\n"
            f"BB State: {indicators.get('bb_state', 'N/A')}\n\n"

            f"═══ VOLUME ═══\n"
            f"RVOL: {volume.get('rvol', 'N/A')}x | "
            f"Volume Climax: {volume.get('is_climax', False)}\n"
            f"Session: {volume.get('session', 'N/A')}\n"
            f"Funding Rate: {volume.get('funding_rate', 'N/A')} | "
            f"Open Interest Change: {volume.get('oi_change', 'N/A')}\n\n"

            f"═══ HTF CONTEXT ═══\n"
            f"Primary Bias: {htf.get('primary_bias', 'N/A')}\n"
        )

        # Structured HTF summaries
        for tf in ('4h', '1d'):
            struct = htf.get(f'htf_{tf}_structure', 'N/A')
            if struct != 'N/A':
                prompt += f"{tf.upper()} Structure: {struct}\n"
            else:
                prompt += f"{tf.upper()} Structure: N/A\n"

        prompt += "\n═══ CLASSIFIED CANDLES (Pre-computed, newest last) ═══\n"
        if classified:
            for line in classified:
                prompt += f"{line}\n"
        else:
            prompt += "No classified candle data available.\n"

        prompt += (
            f"\nRespond with JSON only (0-100 confidence scale): "
            f"{{\"reasoning\": \"...\", \"dimension_scores\": {{...}}, \"confidence_score\": N, "
            f"\"verdict\": \"CONFIRM|REJECT|MODIFY\", \"modified_sl\": null, ...}}"
        )

        return prompt

    @staticmethod
    def evaluate_signal(context: Dict[str, Any]) -> Tuple[Optional[LLMVerdictSchema], str, str]:
        """
        Evaluate a trading signal using the structured context payload.

        Args:
            context: Dict from llm_context_builder.build_llm_context()

        Returns:
            Tuple: (parsed LLMVerdictSchema or None, prompt_text, raw_response_text)
        """
        prompt = LLMClient._build_prompt(context)

        try:
            provider = get_llm_provider()
            content, raw_response = provider.evaluate_prompt(
                LLMClient.SYSTEM_PROMPT, prompt
            )

            if not content:
                return None, prompt, raw_response

            logger.info(f"[LLMClient] Received response ({len(content)} chars)")

            return _parse_llm_response(content, prompt, raw_response)

        except Exception as e:
            logger.error(f"Unexpected error in LLM evaluate_signal: {e}")
            return None, prompt, f"ERROR: {e}"

    @staticmethod
    def ping_status() -> bool:
        provider = get_llm_provider()
        return provider.ping_status()


def _parse_llm_response(
    content: str, prompt: str, raw_response: str
) -> Tuple[Optional[LLMVerdictSchema], str, str]:
    """Parse the LLM's JSON response, handling common formatting issues."""

    # Strip markdown code blocks
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    # Strip <think>...</think> tags (some models)
    if "<think>" in content:
        think_end = content.find("</think>")
        if think_end != -1:
            content = content[think_end + 8:].strip()

    # Find JSON object boundaries
    if not content.startswith("{"):
        json_start = content.find("{")
        if json_start != -1:
            content = content[json_start:]
    if not content.endswith("}"):
        json_end = content.rfind("}")
        if json_end != -1:
            content = content[:json_end + 1]

    try:
        raw_dict = json.loads(content, strict=False)

        # Coerce confidence_score from float to int (LLMs sometimes return 7.5 instead of 7)
        raw_dict['confidence_score'] = int(float(raw_dict.get('confidence_score', 0)))

        parsed = LLMVerdictSchema.model_validate(raw_dict)

        if parsed.verdict not in ('CONFIRM', 'REJECT', 'MODIFY'):
            logger.error(f"LLM produced invalid verdict: {parsed.verdict}")
            return None, prompt, raw_response

        parsed.confidence_score = max(0, min(100, parsed.confidence_score))

        # Auto-downgrade low-confidence CONFIRMs
        if parsed.verdict == 'CONFIRM' and parsed.confidence_score < LLM_CONFIDENCE_THRESHOLD:
            logger.warning(
                f"[LLMClient] Auto-downgrade: CONFIRM but confidence={parsed.confidence_score} "
                f"< {LLM_CONFIDENCE_THRESHOLD}. Overriding to REJECT."
            )
            parsed.verdict = 'REJECT'
            parsed.reasoning += (
                f" [AUTO-REJECTED: confidence {parsed.confidence_score}/100 "
                f"below threshold {LLM_CONFIDENCE_THRESHOLD}]"
            )

        return parsed, prompt, raw_response

    except json.JSONDecodeError as e:
        logger.error(f"LLM JSON decode error: {e}\nContent: {content[:200]}")
        return None, prompt, f"JSONDecodeError: {e}"
    except ValidationError as e:
        logger.error(f"LLM schema validation error: {e}")
        return None, prompt, f"ValidationError: {e}"

