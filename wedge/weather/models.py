"""Weather forecast dataclasses and (Phase 3) probability computation."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist, fmean, stdev

# Model display names and precip-skill weights (ECMWF best, ICON least).
MODEL_DISPLAY = {
    "ecmwf_ifs025": "ECMWF",
    "gfs_seamless": "GFS",
    "icon_seamless": "ICON",
}
PRECIP_WEIGHTS = {"ecmwf_ifs025": 0.5, "gfs_seamless": 0.3, "icon_seamless": 0.2}

# Single-model fallback standard deviations when models disagree can't be measured.
FALLBACK_STD = {"high": 3.0, "low": 4.0, "wind": 5.0}


@dataclass
class DayForecast:
    """One model's forecast for one city on one day."""

    date: str            # ISO date "YYYY-MM-DD"
    high_f: float | None
    low_f: float | None
    precip_inches: float | None
    precip_prob: float | None   # 0..100 (percent)
    wind_max_mph: float | None
    model_name: str             # raw Open-Meteo model id, e.g. "ecmwf_ifs025"

    @property
    def model_label(self) -> str:
        return MODEL_DISPLAY.get(self.model_name, self.model_name)


@dataclass
class CityForecast:
    """All model forecasts for a single city, keyed by model."""

    city: str
    lat: float
    lon: float
    # model id -> list of DayForecast (one per day, in date order)
    by_model: dict[str, list[DayForecast]] = field(default_factory=dict)

    def dates(self) -> list[str]:
        """Union of forecast dates across models, sorted ascending."""
        seen: set[str] = set()
        for days in self.by_model.values():
            seen.update(d.date for d in days)
        return sorted(seen)

    def day_across_models(self, date: str) -> list[DayForecast]:
        """All models' forecasts for a given date."""
        out: list[DayForecast] = []
        for days in self.by_model.values():
            for d in days:
                if d.date == date:
                    out.append(d)
        return out

    def consensus(self, date: str) -> "ConsensusDay":
        return ConsensusDay.from_models(self.city, date, self.day_across_models(date))


def _values(items: list[float | None]) -> list[float]:
    return [v for v in items if v is not None]


@dataclass
class ConsensusDay:
    """Multi-model consensus for one city/day, with probability helpers."""

    city: str
    date: str
    high_mean: float | None
    high_std: float          # model disagreement; >=0
    low_mean: float | None
    low_std: float
    wind_mean: float | None
    wind_std: float
    precip_prob: float | None  # weighted, 0..1
    precip_mean_in: float | None
    n_models: int

    @classmethod
    def from_models(cls, city: str, date: str, days: list[DayForecast]) -> "ConsensusDay":
        highs = _values([d.high_f for d in days])
        lows = _values([d.low_f for d in days])
        winds = _values([d.wind_max_mph for d in days])
        precip_amt = _values([d.precip_inches for d in days])

        high_mean = fmean(highs) if highs else None
        low_mean = fmean(lows) if lows else None
        wind_mean = fmean(winds) if winds else None

        high_std = stdev(highs) if len(highs) > 1 else FALLBACK_STD["high"]
        low_std = stdev(lows) if len(lows) > 1 else FALLBACK_STD["low"]
        wind_std = stdev(winds) if len(winds) > 1 else FALLBACK_STD["wind"]

        # Weighted precip probability across available models (normalize weights).
        num = 0.0
        den = 0.0
        for d in days:
            if d.precip_prob is None:
                continue
            w = PRECIP_WEIGHTS.get(d.model_name, 0.2)
            num += w * (d.precip_prob / 100.0)
            den += w
        precip_prob = (num / den) if den > 0 else None
        precip_mean = fmean(precip_amt) if precip_amt else None

        return cls(
            city=city,
            date=date,
            high_mean=high_mean,
            high_std=max(high_std, 0.1),
            low_mean=low_mean,
            low_std=max(low_std, 0.1),
            wind_mean=wind_mean,
            wind_std=max(wind_std, 0.1),
            precip_prob=precip_prob,
            precip_mean_in=precip_mean,
            n_models=len(days),
        )

    # --- probability helpers (Phase 3) ---

    @staticmethod
    def _p_over(mean: float | None, std: float, threshold: float) -> float | None:
        """P(value > threshold) under a normal model."""
        if mean is None:
            return None
        z = (threshold - mean) / std
        return 1.0 - NormalDist().cdf(z)

    def p_high_over(self, threshold: float) -> float | None:
        return self._p_over(self.high_mean, self.high_std, threshold)

    def p_high_under(self, threshold: float) -> float | None:
        p = self.p_high_over(threshold)
        return None if p is None else 1.0 - p

    def p_low_over(self, threshold: float) -> float | None:
        return self._p_over(self.low_mean, self.low_std, threshold)

    def p_low_under(self, threshold: float) -> float | None:
        p = self.p_low_over(threshold)
        return None if p is None else 1.0 - p

    def p_wind_over(self, threshold: float) -> float | None:
        return self._p_over(self.wind_mean, self.wind_std, threshold)

    def p_precip_over(self, threshold: float) -> float | None:
        """For precip, use the weighted model precip probability directly.

        threshold is the rain amount (inches); we treat any measurable-rain
        probability as P(precip > threshold) when threshold is small (<=0.1"),
        and scale down for larger thresholds using the mean amount as a guide.
        """
        if self.precip_prob is None:
            return None
        if threshold <= 0.1:
            return self.precip_prob
        # Larger thresholds: dampen by how far the mean amount falls short.
        if self.precip_mean_in is None or self.precip_mean_in <= 0:
            return self.precip_prob * 0.5
        ratio = min(1.0, self.precip_mean_in / threshold)
        return self.precip_prob * ratio

    @property
    def confidence(self) -> str:
        """Confidence from high-temp model spread: high <2°F, medium <5, low >5."""
        s = self.high_std
        if s < 2.0:
            return "high"
        if s < 5.0:
            return "medium"
        return "low"
