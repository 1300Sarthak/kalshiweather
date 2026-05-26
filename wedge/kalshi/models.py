"""Kalshi contract dataclass and ticker/market parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
# Ticker middle segment like "26MAY26" (YY MON DD) or "26MAY26T12" with hour.
_DATE_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})")

# Map a series "kind" (from catalog discovery) + strike direction -> contract_type.
_TYPE_GROUPS = {
    "high": ("high_over", "high_under"),
    "low": ("low_over", "low_under"),
    "rain": ("rain_over", "rain_under"),
    "wind": ("wind_over", "wind_under"),
}
# CLI --type aliases -> kind
TYPE_ALIASES = {
    "temp_high": "high", "high": "high",
    "temp_low": "low", "low": "low",
    "precip": "rain", "rain": "rain",
    "wind": "wind",
}


def parse_ticker_date(ticker: str) -> str | None:
    """Extract the settlement date (ISO 'YYYY-MM-DD') from a Kalshi ticker.

    e.g. 'KXHIGHNY-26MAY26-T84' -> '2026-05-26'.
    """
    parts = ticker.split("-")
    if len(parts) < 2:
        return None
    m = _DATE_RE.match(parts[1])
    if not m:
        return None
    yy, mon, dd = m.group(1), m.group(2), m.group(3)
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        return date(2000 + int(yy), month, int(dd)).isoformat()
    except ValueError:
        return None


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class KalshiContract:
    """A single Kalshi binary market mapped to a weather threshold.

    All prices are in dollars (0..1), matching Kalshi's *_dollars fields and the
    edge engine's probability scale.
    """

    ticker: str
    city: str
    date: str
    contract_type: str   # e.g. "high_over", "low_under", "rain_over"
    threshold: float
    unit: str            # "°F" or "in"
    yes_bid: float | None
    yes_ask: float | None
    mid_price: float | None
    spread: float | None
    volume: int
    open_interest: int
    title: str = ""
    close_time: str | None = None

    @property
    def kind(self) -> str:
        return self.contract_type.split("_")[0]

    @property
    def direction(self) -> str:
        return self.contract_type.split("_")[1]


def contract_from_market(market: dict[str, Any], city_name: str, kind: str) -> KalshiContract | None:
    """Build a KalshiContract from a Kalshi market object + its series kind.

    Returns None for markets we can't interpret (e.g. no parseable date/strike).
    """
    ticker = market.get("ticker")
    if not ticker:
        return None
    iso = parse_ticker_date(ticker)
    if iso is None:
        return None

    floor_strike = _f(market.get("floor_strike"))
    cap_strike = _f(market.get("cap_strike"))
    strike_type = (market.get("strike_type") or "").lower()

    # Direction + threshold from strike. "greater"/floor => over; "less"/cap => under.
    if strike_type == "greater" or (floor_strike is not None and cap_strike is None):
        direction = "over"
        threshold = floor_strike
    elif strike_type == "less" or (cap_strike is not None and floor_strike is None):
        direction = "under"
        threshold = cap_strike
    else:
        # Range/between or unknown: use floor as lower bound, treat as "over".
        direction = "over"
        threshold = floor_strike if floor_strike is not None else cap_strike
    if threshold is None:
        return None

    over_t, under_t = _TYPE_GROUPS.get(kind, (f"{kind}_over", f"{kind}_under"))
    contract_type = over_t if direction == "over" else under_t
    unit = "in" if kind == "rain" else "°F"

    yes_bid = _f(market.get("yes_bid_dollars"))
    yes_ask = _f(market.get("yes_ask_dollars"))
    # Fallback: derive yes_ask from the no side (yes_ask = 1 - best_no_bid).
    if yes_ask is None:
        no_bid = _f(market.get("no_bid_dollars"))
        if no_bid is not None:
            yes_ask = round(1.0 - no_bid, 4)

    mid = None
    spread = None
    if yes_bid is not None and yes_ask is not None:
        mid = round((yes_bid + yes_ask) / 2, 4)
        spread = round(yes_ask - yes_bid, 4)
    elif yes_bid is not None:
        mid = yes_bid
    elif yes_ask is not None:
        mid = yes_ask

    volume = int(_f(market.get("volume_fp")) or 0)
    oi = int(_f(market.get("open_interest_fp")) or 0)

    return KalshiContract(
        ticker=ticker,
        city=city_name,
        date=iso,
        contract_type=contract_type,
        threshold=threshold,
        unit=unit,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        mid_price=mid,
        spread=spread,
        volume=volume,
        open_interest=oi,
        title=market.get("title", "") or "",
        close_time=market.get("close_time"),
    )
