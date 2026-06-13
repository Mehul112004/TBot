"""Provider registry — factory for market data providers."""

from typing import Optional

_PROVIDERS: dict[str, 'AbstractMarketProvider'] = {}


def register_provider(market_type: str, provider: 'AbstractMarketProvider'):
    _PROVIDERS[market_type.upper()] = provider


def get_provider(market_type: str) -> Optional['AbstractMarketProvider']:
    """Get a provider by market type. Returns None if not registered."""
    return _PROVIDERS.get(market_type.upper())


def list_providers() -> list[str]:
    return list(_PROVIDERS.keys())
