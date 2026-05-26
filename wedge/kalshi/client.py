"""Kalshi public market-data client.

Market listing and orderbook endpoints are PUBLIC — no authentication needed.
Base URL: https://api.elections.kalshi.com/trade-api/v2
"""

from __future__ import annotations

import asyncio
import re

import httpx

from ..config import City
from ..http import get_json
from .models import KalshiContract, contract_from_market

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
WEATHER_CATEGORY = "Climate and Weather"
BATCH_PAUSE = 0.12  # seconds between request batches (~8 req/s, under Kalshi's limit)

# City display name -> title tokens used to match weather series in the catalog.
CITY_TOKENS: dict[str, list[str]] = {
    "New York": ["new york", "nyc"],
    "Chicago": ["chicago"],
    "Los Angeles": ["los angeles"],
    "Miami": ["miami"],
    "Denver": ["denver"],
    "Phoenix": ["phoenix"],
    "Seattle": ["seattle"],
    "Houston": ["houston"],
}


class KalshiUnavailable(Exception):
    """Raised when the Kalshi API can't be reached — callers fall back gracefully."""


def _series_kind(title: str) -> str | None:
    """Classify a series title into 'high' | 'low' | 'rain', or None to skip.

    Excludes hourly/monthly/range aggregate series — we only want daily temps/rain.
    """
    t = title.lower()
    if any(x in t for x in ("hourly", "month", "range", "snow")):
        return None
    if "temp" in t and re.search(r"high|max", t):
        return "high"
    if "temp" in t and re.search(r"low|min", t):
        return "low"
    if "rain" in t or "precip" in t:
        return "rain"
    return None


async def discover_weather_series(
    client: httpx.AsyncClient, cities: list[City]
) -> dict[str, list[tuple[str, str]]]:
    """Return {city_name: [(series_ticker, kind), ...]} from the weather catalog."""
    try:
        payload = await get_json(
            client, f"{BASE_URL}/series", params={"category": WEATHER_CATEGORY}
        )
    except (httpx.HTTPError, httpx.TransportError) as exc:
        raise KalshiUnavailable(str(exc)) from exc

    catalog = payload.get("series", []) or []
    wanted = {c.name: CITY_TOKENS.get(c.name, [c.name.lower()]) for c in cities}
    out: dict[str, list[tuple[str, str]]] = {c.name: [] for c in cities}
    for s in catalog:
        title = s.get("title", "") or ""
        ticker = s.get("ticker")
        kind = _series_kind(title)
        if not ticker or kind is None:
            continue
        tl = title.lower()
        for city_name, tokens in wanted.items():
            if any(tok in tl for tok in tokens):
                out[city_name].append((ticker, kind))
    return out


async def _markets_for_series(
    client: httpx.AsyncClient, series_ticker: str, city_name: str, kind: str
) -> list[KalshiContract]:
    try:
        payload = await get_json(
            client,
            f"{BASE_URL}/markets",
            params={"series_ticker": series_ticker, "status": "open", "limit": 200},
        )
    except httpx.HTTPError:
        return []
    contracts: list[KalshiContract] = []
    for m in payload.get("markets", []) or []:
        c = contract_from_market(m, city_name, kind)
        if c is not None:
            contracts.append(c)
    return contracts


async def get_weather_markets(
    client: httpx.AsyncClient,
    cities: list[City],
    kinds: set[str] | None = None,
) -> list[KalshiContract]:
    """Fetch all open weather contracts for the given cities.

    Discovers series from the catalog, then fetches open markets per series in
    paced batches. Deduplicates by ticker (legacy/alias series can overlap).
    """
    series_map = await discover_weather_series(client, cities)

    jobs: list[tuple[str, str, str]] = []  # (series_ticker, city_name, kind)
    for city_name, series in series_map.items():
        for series_ticker, kind in series:
            if kinds and kind not in kinds:
                continue
            jobs.append((series_ticker, city_name, kind))

    by_ticker: dict[str, KalshiContract] = {}
    # Process in small concurrent batches with a short pause to respect rate limits.
    batch_size = 6
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        results = await asyncio.gather(
            *(_markets_for_series(client, st, cn, k) for st, cn, k in batch)
        )
        for contracts in results:
            for c in contracts:
                # Prefer the contract that actually has a price quote.
                existing = by_ticker.get(c.ticker)
                if existing is None or (existing.mid_price is None and c.mid_price is not None):
                    by_ticker[c.ticker] = c
        if i + batch_size < len(jobs):
            await asyncio.sleep(BATCH_PAUSE)

    return list(by_ticker.values())


async def get_market_orderbook(client: httpx.AsyncClient, ticker: str) -> dict:
    """Fetch an orderbook and derive bid/ask/mid/spread (dollars) + raw depth.

    Kalshi returns bids only; yes_ask = 1 - best_no_bid.
    """
    payload = await get_json(client, f"{BASE_URL}/markets/{ticker}/orderbook")
    ob = payload.get("orderbook_fp") or payload.get("orderbook") or {}
    yes = ob.get("yes_dollars") or ob.get("yes") or []
    no = ob.get("no_dollars") or ob.get("no") or []

    def best(levels) -> float | None:
        prices = [float(p) for p, _ in levels] if levels else []
        return max(prices) if prices else None

    yes_bid = best(yes)
    best_no = best(no)
    yes_ask = round(1.0 - best_no, 4) if best_no is not None else None
    mid = spread = None
    if yes_bid is not None and yes_ask is not None:
        mid = round((yes_bid + yes_ask) / 2, 4)
        spread = round(yes_ask - yes_bid, 4)
    return {
        "ticker": ticker,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "mid": mid,
        "spread": spread,
        "yes_depth": yes,
        "no_depth": no,
    }


async def get_market_details(client: httpx.AsyncClient, ticker: str) -> dict:
    """Full market metadata (settlement source, close time, etc.)."""
    payload = await get_json(client, f"{BASE_URL}/markets/{ticker}")
    return payload.get("market", payload)
