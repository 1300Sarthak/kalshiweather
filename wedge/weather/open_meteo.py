"""Open-Meteo multi-model forecast fetcher (ECMWF IFS, GFS, ICON)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import City
from ..http import get_json
from .models import CityForecast, DayForecast

BASE_URL = "https://api.open-meteo.com/v1/forecast"
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
]


def _params(city: City, forecast_days: int) -> dict[str, Any]:
    return {
        "latitude": city.lat,
        "longitude": city.lon,
        "daily": ",".join(DAILY_VARS),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "models": ",".join(MODELS),
        "forecast_days": forecast_days,
        "timezone": "auto",
    }


def _get_list(daily: dict[str, Any], key: str) -> list[Any]:
    val = daily.get(key)
    return val if isinstance(val, list) else []


def _parse(city: City, payload: dict[str, Any]) -> CityForecast:
    """Parse Open-Meteo multi-model response into a CityForecast.

    With multiple models requested, Open-Meteo suffixes each daily variable with
    the model id, e.g. ``temperature_2m_max_ecmwf_ifs025``. Some single-model
    responses omit the suffix; we handle both.
    """
    daily = payload.get("daily", {}) or {}
    dates = _get_list(daily, "time")
    cf = CityForecast(city=city.name, lat=city.lat, lon=city.lon)

    for model in MODELS:
        def col(base: str) -> list[Any]:
            suffixed = _get_list(daily, f"{base}_{model}")
            return suffixed if suffixed else _get_list(daily, base)

        highs = col("temperature_2m_max")
        lows = col("temperature_2m_min")
        precip = col("precipitation_sum")
        pprob = col("precipitation_probability_max")
        wind = col("wind_speed_10m_max")

        # Skip a model that returned no data at all.
        if not any([highs, lows, precip, pprob, wind]):
            continue

        days: list[DayForecast] = []
        for i, date in enumerate(dates):
            def at(arr: list[Any]) -> float | None:
                if i < len(arr) and arr[i] is not None:
                    try:
                        return float(arr[i])
                    except (TypeError, ValueError):
                        return None
                return None

            days.append(
                DayForecast(
                    date=date,
                    high_f=at(highs),
                    low_f=at(lows),
                    precip_inches=at(precip),
                    precip_prob=at(pprob),
                    wind_max_mph=at(wind),
                    model_name=model,
                )
            )
        cf.by_model[model] = days
    return cf


async def fetch_city(client: httpx.AsyncClient, city: City, forecast_days: int) -> CityForecast:
    payload = await get_json(client, BASE_URL, params=_params(city, forecast_days))
    return _parse(city, payload)


async def fetch_all(
    client: httpx.AsyncClient, cities: list[City], forecast_days: int
) -> list[CityForecast]:
    """Fetch all cities concurrently. Failed cities yield empty forecasts."""
    results = await asyncio.gather(
        *(fetch_city(client, c, forecast_days) for c in cities),
        return_exceptions=True,
    )
    out: list[CityForecast] = []
    for city, res in zip(cities, results):
        if isinstance(res, Exception):
            out.append(CityForecast(city=city.name, lat=city.lat, lon=city.lon))
        else:
            out.append(res)
    return out
