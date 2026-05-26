"""Kelly criterion position sizing (full Kelly, capped)."""

from __future__ import annotations


def kelly_fraction(edge: float, market_price: float, max_kelly: float = 0.25) -> float:
    """Full Kelly fraction of bankroll to bet, capped at max_kelly.

    For a binary contract priced at `market_price` (the cost of YES, 0..1), a win
    pays $1, so net odds b = (1/price) - 1. The model's win probability is
    p = market_price + edge. Kelly fraction f* = (p*b - q) / b.
    """
    if edge <= 0 or market_price <= 0 or market_price >= 1:
        return 0.0
    b = (1.0 / market_price) - 1.0
    p = market_price + edge
    q = 1.0 - p
    f = (p * b - q) / b
    return max(0.0, min(f, max_kelly))
