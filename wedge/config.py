"""Configuration: city definitions, thresholds, and environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class City:
    """A scannable city: location plus its Kalshi market code."""

    name: str          # display name, e.g. "New York"
    code: str          # short CLI alias, e.g. "NYC"
    lat: float
    lon: float
    kalshi_code: str   # Kalshi ticker suffix, e.g. "NY" -> KXHIGHNY


# Kalshi weather series use city codes embedded in the series ticker, e.g.
# KXHIGHNY (New York high temp), KXHIGHCHI (Chicago high temp). Codes below
# match Kalshi's known weather-series naming; cities without markets simply
# return no contracts (weather is still fetched and displayed).
CITIES: list[City] = [
    City("New York", "NYC", 40.7790, -73.9692, "NY"),    # Central Park
    City("Chicago", "CHI", 41.9803, -87.9090, "CHI"),     # O'Hare
    City("Los Angeles", "LA", 33.9382, -118.3886, "LAX"),
    City("Miami", "MIA", 25.7906, -80.3164, "MIA"),
    City("Denver", "DEN", 39.8466, -104.6562, "DEN"),
    City("Phoenix", "PHX", 33.4278, -112.0037, "PHIL"),   # verified at runtime
    City("Seattle", "SEA", 47.4444, -122.3139, "SEA"),
    City("Houston", "HOU", 29.9902, -95.3368, "HOU"),
]

_BY_CODE = {c.code.upper(): c for c in CITIES}
_BY_NAME = {c.name.lower(): c for c in CITIES}


def resolve_city(token: str) -> City | None:
    """Resolve a CLI token (code or name, case-insensitive) to a City."""
    if not token:
        return None
    t = token.strip()
    return _BY_CODE.get(t.upper()) or _BY_NAME.get(t.lower())


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    """Runtime configuration for a scan, overridable via env or CLI flags."""

    min_edge: float = field(default_factory=lambda: _env_float("WEDGE_MIN_EDGE", 0.04))
    max_kelly: float = field(default_factory=lambda: _env_float("WEDGE_MAX_KELLY", 0.25))
    bankroll: float = field(default_factory=lambda: _env_float("WEDGE_BANKROLL", 500.0))
    forecast_days: int = field(default_factory=lambda: _env_int("WEDGE_FORECAST_DAYS", 7))
    ecmwf_api_key: str | None = field(default_factory=lambda: os.getenv("ECMWF_API_KEY") or None)

    @property
    def has_ecmwf(self) -> bool:
        return bool(self.ecmwf_api_key)
