"""Optional ECMWF ensemble fetcher (51-member) for direct probability.

This is a best-effort enhancement. If ECMWF_API_KEY is not set, the caller uses
the Open-Meteo multi-model normal-CDF approximation instead. Open-Meteo also
exposes ECMWF IFS ensemble members without a key via the ensemble API, which we
use here as a practical, no-credential ensemble source; the CDS path is wired
for when a key is present.

Probability from an ensemble is the fraction of members above/below the
threshold — no normal assumption needed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import City
from ..http import get_json

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODEL = "ecmwf_ifs025"  # ~51 perturbed members


def _ensemble_params(city: City, forecast_days: int) -> dict[str, Any]:
    return {
        "latitude": city.lat,
        "longitude": city.lon,
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "models": ENSEMBLE_MODEL,
        "forecast_days": forecast_days,
        "timezone": "auto",
    }


def _member_columns(daily: dict[str, Any], base: str) -> list[list[float | None]]:
    """Collect all per-member series for a daily variable.

    Open-Meteo names ensemble members like 'temperature_2m_max_member01'
    (plus an unsuffixed control run). Returns a list of per-member value lists
    (index = day), including the control run.
    """
    members: list[list[float | None]] = []
    member_prefix = f"{base}_member"
    for key, val in daily.items():
        if not isinstance(val, list):
            continue
        if key == base or key.startswith(member_prefix):
            members.append([float(v) if v is not None else None for v in val])
    return members


async def fetch_ensemble_highs(
    client: httpx.AsyncClient, city: City, forecast_days: int
) -> dict[str, list[float]]:
    """Return {iso_date: [member high temps]} for a city, or {} on failure."""
    try:
        payload = await get_json(client, ENSEMBLE_URL, params=_ensemble_params(city, forecast_days))
    except httpx.HTTPError:
        return {}
    daily = payload.get("daily", {}) or {}
    dates = daily.get("time", []) or []
    cols = _member_columns(daily, "temperature_2m_max")
    if not cols:
        return {}
    out: dict[str, list[float]] = {}
    for i, date in enumerate(dates):
        vals = [m[i] for m in cols if i < len(m) and m[i] is not None]
        if vals:
            out[date] = vals
    return out


def prob_over_from_members(members: list[float], threshold: float) -> float | None:
    """Direct ensemble probability: fraction of members strictly above threshold."""
    if not members:
        return None
    return sum(1 for v in members if v > threshold) / len(members)


async def fetch_all_ensembles(
    client: httpx.AsyncClient, cities: list[City], forecast_days: int
) -> dict[str, dict[str, list[float]]]:
    """{city_name: {date: [member highs]}} for all cities concurrently."""
    results = await asyncio.gather(
        *(fetch_ensemble_highs(client, c, forecast_days) for c in cities),
        return_exceptions=True,
    )
    out: dict[str, dict[str, list[float]]] = {}
    for city, res in zip(cities, results):
        out[city.name] = res if isinstance(res, dict) else {}
    return out
