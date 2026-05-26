"""Scan orchestrator: fetch weather + markets, match, compute edges, rank."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..config import City, Config
from ..http import client_session
from ..kalshi import client as kalshi_client
from ..kalshi.models import KalshiContract
from ..weather import ecmwf as ecmwf_mod
from ..weather import open_meteo
from ..weather.models import CityForecast, ConsensusDay
from .edge import compute_edge, edge_signal
from .kelly import kelly_fraction


@dataclass
class EdgeResult:
    contract: KalshiContract
    side: str               # "YES" or "NO" — the side worth buying
    model_prob: float       # model probability that the bet side wins
    market_price: float     # price of the bet side (dollars, 0..1)
    edge: float             # positive actionable edge
    signal: str
    kelly_pct: float        # fraction of bankroll (0..max_kelly)
    bet_size: float         # dollars
    forecast_value: float | None  # consensus high/low/precip used
    models_agree: bool
    confidence: str
    model_values: dict[str, float]  # per-model forecast value (for --verbose)
    model_spread: float             # cross-model spread for this contract's metric


def _model_prob_yes(cons: ConsensusDay, c: KalshiContract) -> tuple[float | None, float | None]:
    """Probability the YES outcome happens, plus the forecast value shown."""
    t = c.threshold
    ct = c.contract_type
    if ct == "high_over":
        return cons.p_high_over(t), cons.high_mean
    if ct == "high_under":
        return cons.p_high_under(t), cons.high_mean
    if ct == "low_over":
        return cons.p_low_over(t), cons.low_mean
    if ct == "low_under":
        return cons.p_low_under(t), cons.low_mean
    if ct == "rain_over":
        return cons.p_precip_over(t), cons.precip_mean_in
    if ct == "rain_under":
        p = cons.p_precip_over(t)
        return (None if p is None else 1.0 - p), cons.precip_mean_in
    if ct == "wind_over":
        return cons.p_wind_over(t), cons.wind_mean
    if ct == "wind_under":
        p = cons.p_wind_over(t)
        return (None if p is None else 1.0 - p), cons.wind_mean
    return None, None


def _models_agree(cf: CityForecast, c: KalshiContract) -> bool:
    """True if all available models fall on the same side of the threshold."""
    days = cf.day_across_models(c.date)
    if c.kind == "high":
        vals = [d.high_f for d in days if d.high_f is not None]
    elif c.kind == "low":
        vals = [d.low_f for d in days if d.low_f is not None]
    elif c.kind == "wind":
        vals = [d.wind_max_mph for d in days if d.wind_max_mph is not None]
    else:
        return True
    if len(vals) < 2:
        return True
    over = [v > c.threshold for v in vals]
    return all(over) or not any(over)


def _model_breakdown(cf: CityForecast, c: KalshiContract) -> tuple[dict[str, float], float]:
    """Per-model forecast values for this contract's metric + their spread."""
    days = cf.day_across_models(c.date)
    attr = {"high": "high_f", "low": "low_f", "wind": "wind_max_mph", "rain": "precip_inches"}.get(
        c.kind, "high_f"
    )
    vals: dict[str, float] = {}
    for d in days:
        v = getattr(d, attr)
        if v is not None:
            vals[d.model_label] = round(float(v), 1)
    spread = (max(vals.values()) - min(vals.values())) if len(vals) > 1 else 0.0
    return vals, round(spread, 1)


def build_results(
    forecasts: list[CityForecast],
    contracts: list[KalshiContract],
    cfg: Config,
    ensembles: dict[str, dict[str, list[float]]] | None = None,
) -> list[EdgeResult]:
    """Match contracts to forecasts and compute ranked EdgeResults."""
    by_city = {cf.city: cf for cf in forecasts}
    results: list[EdgeResult] = []

    for c in contracts:
        if c.mid_price is None:
            continue
        # Skip untradeable penny/near-certain strikes — their huge "edges" are
        # noise from effectively-settled markets, not actionable mispricings.
        if c.mid_price < 0.02 or c.mid_price > 0.98:
            continue
        cf = by_city.get(c.city)
        if cf is None:
            continue
        cons = cf.consensus(c.date)
        prob_yes, fval = _model_prob_yes(cons, c)

        # Ensemble override for high-temp contracts when available.
        if ensembles and c.kind == "high":
            members = ensembles.get(c.city, {}).get(c.date)
            if members:
                p_over = ecmwf_mod.prob_over_from_members(members, c.threshold)
                if p_over is not None:
                    prob_yes = p_over if c.direction == "over" else 1.0 - p_over

        if prob_yes is None:
            continue

        mid = c.mid_price
        yes_edge = compute_edge(prob_yes, mid)
        if yes_edge >= 0:
            side, edge, prob, price = "YES", yes_edge, prob_yes, mid
        else:
            side, edge, prob, price = "NO", -yes_edge, 1.0 - prob_yes, round(1.0 - mid, 4)

        if edge < cfg.min_edge:
            continue

        kpct = kelly_fraction(edge, price, cfg.max_kelly)
        mvals, mspread = _model_breakdown(cf, c)
        results.append(
            EdgeResult(
                contract=c,
                side=side,
                model_prob=prob,
                market_price=price,
                edge=edge,
                signal=edge_signal(edge),
                kelly_pct=kpct,
                bet_size=round(kpct * cfg.bankroll, 2),
                forecast_value=fval,
                models_agree=_models_agree(cf, c),
                confidence=cons.confidence,
                model_values=mvals,
                model_spread=mspread,
            )
        )

    results.sort(key=lambda r: r.edge, reverse=True)
    return results


async def scan(
    cfg: Config,
    cities: list[City],
    kinds: set[str] | None = None,
) -> tuple[list[EdgeResult], bool]:
    """Run a full scan. Returns (results, kalshi_ok).

    If Kalshi is unavailable, returns ([], False) so callers can report
    weather-only mode rather than crashing.
    """
    async with client_session() as client:
        coros = [
            open_meteo.fetch_all(client, cities, cfg.forecast_days),
            kalshi_client.get_weather_markets(client, cities, kinds),
        ]
        if cfg.has_ecmwf:
            coros.append(ecmwf_mod.fetch_all_ensembles(client, cities, cfg.forecast_days))

        gathered = await asyncio.gather(*coros, return_exceptions=True)

    forecasts = gathered[0] if not isinstance(gathered[0], Exception) else []
    markets_res = gathered[1]
    ensembles = gathered[2] if len(gathered) > 2 and not isinstance(gathered[2], Exception) else None

    if isinstance(markets_res, Exception):
        # Kalshi unavailable (or any market-fetch error) — weather-only mode.
        return [], False

    return build_results(forecasts, markets_res, cfg, ensembles), True


async def fetch_orderbooks(results: list[EdgeResult]) -> dict[str, dict]:
    """Fetch orderbook depth for the given results (used by --verbose)."""
    if not results:
        return {}
    async with client_session() as client:
        tickers = [r.contract.ticker for r in results]
        books = await asyncio.gather(
            *(kalshi_client.get_market_orderbook(client, t) for t in tickers),
            return_exceptions=True,
        )
    return {t: b for t, b in zip(tickers, books) if not isinstance(b, Exception)}
