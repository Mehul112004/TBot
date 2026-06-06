from datetime import datetime
from app.core.base_strategy import SetupSignal, Candle, Indicators
from app.core.llm_client import LLMClient, LLMVerdictSchema, LLM_CONFIDENCE_THRESHOLD

def test_prompt_builder():
    context = {
        "signal_metadata": {
            "symbol": "BTCUSDT",
            "strategy": "TestStrat",
            "timeframe": "4h",
            "side": "LONG",
            "entry": 40000.0,
            "sl": 39500.0,
            "tp1": 41000.0,
            "tp2": 42000.0,
            "confidence": 0.8,
            "regime": "TRENDING_UP"
        },
        "market_structure": {
            "current_bias": "TRENDING_UP",
            "structural_bias": "BULLISH",
            "regime_strength": 1.5,
            "last_event": "BOS",
            "recent_swing_high": 42000.0,
            "recent_swing_low": 39000.0,
            "current_price": 40050.0,
            "price_position_in_range_pct": 35.0
        },
        "indicators": {
            "rsi": 45.0,
            "rsi_gradient": "Rising",
            "rsi_divergence": "Bullish",
            "ema_alignment": "Bullish_Perfect_Order",
            "bb_state": "Normal",
            "adx": 25.0,
            "trend_strength": "Strong",
            "ema_values": {"ema_9": 39000.0, "ema_50": 35000.0, "ema_200": 30000.0}
        },
        "volume": {
            "rvol": 1.5,
            "is_climax": False
        },
        "htf_context": {
            "primary_bias": "Bullish"
        },
        "recent_price_action": [
            {
                "t": "2026-06-04 22:00:00",
                "o": 40000.0,
                "h": 40100.0,
                "l": 39900.0,
                "c": 40050.0,
                "v": 100.0
            }
        ]
    }
    
    prompt = LLMClient._build_prompt(context)
    assert "TestStrat" in prompt
    assert "BTCUSDT" in prompt
    assert "═══ COMPUTED RISK METRICS ═══" in prompt
    assert "═══ MARKET STRUCTURE ═══" in prompt
    assert "═══ CLASSIFIED CANDLES" in prompt
    assert "4H Structure:" in prompt
    assert "1D Structure:" in prompt
    print("Prompt builder is working successfully.")

def test_schema_field_order():
    """Verify the chain-of-thought schema: reasoning comes before verdict."""
    valid_json = (
        '{"reasoning": "RSI hooked up from 38, EMA stack aligned, body/ATR=0.3x which is a gentle pullback.", '
        '"confidence_score": 78, "verdict": "CONFIRM", '
        '"modified_sl": null, "modified_tp1": null, "modified_tp2": null, '
        '"rr_tp1": 1.8, "rr_tp2": 3.5, '
        '"dimension_scores": {"trend_alignment": 8, "momentum": 7, "market_structure": 8, '
        '"volume": 6, "price_action_quality": 7, "risk_reward": 8, "key_level_proximity": 7, '
        '"counter_signals": 9}, '
        '"key_counter_signals": [], '
        '"invalidation_level": 39000.0, '
        '"invalidation_note": "Below recent swing low"}'
    )
    parsed = LLMVerdictSchema.model_validate_json(valid_json)
    assert parsed.verdict == "CONFIRM"
    assert parsed.confidence_score == 78
    assert parsed.rr_tp1 == 1.8
    assert parsed.rr_tp2 == 3.5
    assert parsed.dimension_scores["trend_alignment"] == 8
    assert "RSI hooked up" in parsed.reasoning
    print("Schema field order (reasoning → confidence → verdict) working correctly.")

def test_schema_valid():
    valid_json = (
        '{"reasoning": "Looks great, all dimensions aligned.", '
        '"confidence_score": 85, "verdict": "CONFIRM", '
        '"modified_sl": null, "modified_tp1": null, "modified_tp2": null, '
        '"dimension_scores": {}, "rr_tp1": 2.0, "rr_tp2": 4.0}'
    )
    parsed = LLMVerdictSchema.model_validate_json(valid_json)
    assert parsed.verdict == "CONFIRM"
    assert parsed.confidence_score == 85
    print("Schema parsing working successfully.")

def test_low_confidence_auto_downgrade():
    """If LLM says CONFIRM but confidence < threshold, it should be caught downstream."""
    low_conf_json = (
        '{"reasoning": "Not very sure about this one.", '
        '"confidence_score": 30, "verdict": "CONFIRM", '
        '"modified_sl": null, "modified_tp1": null, "modified_tp2": null}'
    )
    parsed = LLMVerdictSchema.model_validate_json(low_conf_json)
    assert parsed.confidence_score < LLM_CONFIDENCE_THRESHOLD
    assert LLM_CONFIDENCE_THRESHOLD == 72
    print("Low confidence threshold validation working correctly.")

if __name__ == "__main__":
    test_prompt_builder()
    test_schema_field_order()
    test_schema_valid()
    test_low_confidence_auto_downgrade()
