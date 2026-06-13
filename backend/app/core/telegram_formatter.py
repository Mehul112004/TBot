import re
from datetime import datetime, timedelta
from app.models.db import ConfirmedSignal, PriceAlert

_MD_SPECIAL = re.compile(r'([_*\[\]()~>#+\-=|{}.!])')

def _escape_md(text: str) -> str:
    return _MD_SPECIAL.sub(r'\\\1', str(text))

def _get_market_info(obj) -> tuple:
    """Return (currency_symbol, exchange_label) from a signal/setup object."""
    mt = getattr(obj, 'market_type', 'CRYPTO')
    if mt == 'INDIAN':
        return ('₹', 'NSE')
    return ('$', 'CRYPTO')

def format_confirmed_signal(signal: ConfirmedSignal) -> str:
    """Format a confirmed trade signal into a structured Telegram message."""
    direction_badge = "🟢" if signal.direction == "LONG" else "🔴"
    currency, exchange = _get_market_info(signal)

    risk = abs(signal.entry - signal.sl)
    reward = abs(signal.tp1 - signal.entry) if risk > 0 else 0
    rr_ratio = reward / risk if risk > 0 else 0

    if signal.created_at:
        dt = signal.created_at
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        dt = dt + timedelta(hours=5, minutes=30)
        time_str = dt.strftime("%d %b %Y %H:%M IST")
    else:
        dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        time_str = dt.strftime("%d %b %Y %H:%M IST")

    reasoning = _escape_md(signal.reasoning_text.strip())

    exchange_line = f"\n*Exchange*  : {_escape_md(exchange)}" if exchange != 'CRYPTO' else ""

    msg = f"""
{direction_badge} CONFIRMED SIGNAL

*Pair*      : {_escape_md(signal.symbol)}
*Direction* : {_escape_md(signal.direction)}
*Timeframe* : {_escape_md(signal.timeframe)}{exchange_line}
*Entry*     : {currency}{_escape_md(f"{signal.entry:,.4f}")}
*SL*        : {currency}{_escape_md(f"{signal.sl:,.4f}")}
*TP1*       : {currency}{_escape_md(f"{signal.tp1:,.4f}")}
*TP2*       : {currency}{_escape_md(f"{signal.tp2:,.4f}")}
*R/R*       : 1 : {_escape_md(f"{rr_ratio:.1f}")}
*Strategy*  : {_escape_md(signal.strategy_name)}
*Confidence*: {_escape_md(f"{signal.confidence * 100:.0f}%")}

*Analysis*  :
{reasoning}

⏱ {_escape_md(time_str)}
"""
    return msg.strip()


def format_watching_signal(setup) -> str:
    """Format an unconfirmed watching setup into a structured Telegram message."""
    direction_badge = "👀 🟢" if setup.direction == "LONG" else "👀 🔴"
    currency, exchange = _get_market_info(setup)

    if setup.detected_at:
        dt = setup.detected_at
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        dt = dt + timedelta(hours=5, minutes=30)
        time_str = dt.strftime("%d %b %Y %H:%M IST")
    else:
        dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        time_str = dt.strftime("%d %b %Y %H:%M IST")

    notes = setup.notes.strip() if hasattr(setup, 'notes') and setup.notes else ""
    notes = _escape_md(notes)

    exchange_line = f"\n*Exchange*  : {_escape_md(exchange)}" if exchange != 'CRYPTO' else ""
    entry_line = f"\n*Entry*     : {currency}{_escape_md(f'{setup.entry:,.4f}')}" if hasattr(setup, 'entry') and setup.entry else ""
    sl_line = f"\n*SL*        : {currency}{_escape_md(f'{setup.sl:,.4f}')}" if hasattr(setup, 'sl') and setup.sl else ""

    msg = f"""
{direction_badge} WATCHING SCAN \\(Not Confirmed\\)

*Pair*      : {_escape_md(setup.symbol)}
*Direction* : {_escape_md(setup.direction)}
*Timeframe* : {_escape_md(setup.timeframe)}{exchange_line}{entry_line}{sl_line}
*Strategy*  : {_escape_md(setup.strategy_name)}
*Confidence*: {_escape_md(f"{setup.confidence * 100:.0f}%")}

*Notes*     :
{notes}

*Status*    : PENDING LLM CONFIRMATION\\.\\.\\.
⏱ {_escape_md(time_str)}
"""
    return msg.strip()


def format_outcome_update(signal: ConfirmedSignal, outcome: str) -> str:
    """Format a simple outcome follow-up message when TP1, TP2 or SL is hit."""
    currency, _ = _get_market_info(signal)

    if outcome == "HIT_TP1":
        icon = "✅"
        level = signal.tp1
        label = "TP1"
    elif outcome == "HIT_TP2":
        icon = "🚀"
        level = signal.tp2
        label = "TP2"
    elif outcome == "HIT_SL":
        icon = "❌"
        level = signal.sl
        label = "SL"
    elif outcome == "EXPIRED":
        icon = "⏳"
        return f"{icon} {_escape_md(signal.symbol)} {_escape_md(signal.direction)} — Setup EXPIRED without entry\\."
    else:
        icon = "ℹ️"
        level = 0.0
    return f"{icon} {_escape_md(signal.symbol)} {_escape_md(signal.direction)} — {label} hit at {currency}{_escape_md(f'{level:,.4f}')}"

def format_rejected_signal(setup, reasoning: str) -> str:
    """Format a rejected unconfirmed watching setup into a structured Telegram message."""
    currency, exchange = _get_market_info(setup)
    exchange_line = f"\n*Exchange*  : {_escape_md(exchange)}" if exchange != 'CRYPTO' else ""

    msg = f"""
🚫 *REJECTED*

*Pair*      : {_escape_md(setup.symbol)}{exchange_line}
*Reasoning* :
{_escape_md(reasoning)}
"""
    return msg.strip()


def format_price_alert(alert: PriceAlert, current_price: float) -> str:
    """Format a triggered price alert into a Telegram message."""
    direction_icon = "🔺" if alert.direction == "ABOVE" else "🔻"
    direction_text = "crossed ABOVE" if alert.direction == "ABOVE" else "crossed BELOW"
    currency, _ = _get_market_info(alert)

    dt = alert.triggered_at or alert.created_at
    if dt:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        dt = dt + timedelta(hours=5, minutes=30)
        time_str = dt.strftime("%d %b %Y %H:%M IST")
    else:
        dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        time_str = dt.strftime("%d %b %Y %H:%M IST")

    note_text = _escape_md(alert.note.strip()) if alert.note and alert.note.strip() else None

    msg = f"""
🔔 PRICE ALERT TRIGGERED

*Pair*      : {_escape_md(alert.symbol)}
*Alert*     : Price {direction_text} {currency}{_escape_md(f"{alert.target_price:,.4f}")}
*Current*   : {currency}{_escape_md(f"{current_price:,.4f}")}
*Type*      : {_escape_md(alert.alert_type)}{"  " + direction_icon}
{("*Note*      : " + note_text) if note_text else ""}
⏱ {_escape_md(time_str)}
"""
    return msg.strip()
