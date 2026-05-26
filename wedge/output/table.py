"""Rich table renderers for terminal output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ..weather.models import CityForecast

console = Console()


def _fmt(v: float | None, suffix: str = "", digits: int = 0) -> str:
    if v is None:
        return "-"
    return f"{v:.{digits}f}{suffix}"


def _model_high(cf: CityForecast, model: str, date: str) -> float | None:
    for d in cf.by_model.get(model, []):
        if d.date == date:
            return d.high_f
    return None


def render_forecast(forecasts: list[CityForecast], days: int) -> None:
    """Phase 1 forecast table: per-model highs, spread, precip, wind."""
    table = Table(title="Weather Forecast — Multi-Model Highs (°F)", header_style="bold cyan")
    table.add_column("City", style="bold")
    table.add_column("Date")
    table.add_column("ECMWF", justify="right")
    table.add_column("GFS", justify="right")
    table.add_column("ICON", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("Precip\"", justify="right")
    table.add_column("Wind", justify="right")

    for cf in forecasts:
        dates = cf.dates()[:days]
        if not dates:
            table.add_row(cf.city, "[dim]no data[/dim]", "-", "-", "-", "-", "-", "-")
            continue
        for i, date in enumerate(dates):
            ecmwf = _model_high(cf, "ecmwf_ifs025", date)
            gfs = _model_high(cf, "gfs_seamless", date)
            icon = _model_high(cf, "icon_seamless", date)
            highs = [h for h in (ecmwf, gfs, icon) if h is not None]
            spread = (max(highs) - min(highs)) if len(highs) > 1 else None
            cons = cf.consensus(date)

            spread_str = _fmt(spread, "°", 1)
            if spread is not None:
                color = "green" if spread < 2 else "yellow" if spread < 5 else "red"
                spread_str = f"[{color}]{spread_str}[/{color}]"

            table.add_row(
                cf.city if i == 0 else "",
                date,
                _fmt(ecmwf, "°", 1),
                _fmt(gfs, "°", 1),
                _fmt(icon, "°", 1),
                spread_str,
                _fmt(cons.precip_mean_in, "", 2),
                _fmt(cons.wind_mean, "", 0),
            )
        table.add_section()

    console.print(table)


def render_forecast_probs(forecasts: list[CityForecast], days: int, thresholds: list[float]) -> None:
    """Phase 3 forecast --probs table: consensus high, spread, P(>T)."""
    table = Table(title="Forecast Probabilities (consensus high)", header_style="bold cyan")
    table.add_column("City", style="bold")
    table.add_column("Date")
    table.add_column("Consensus", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("Conf", justify="center")
    for t in thresholds:
        table.add_column(f"P(>{t:g})", justify="right")

    for cf in forecasts:
        dates = cf.dates()[:days]
        if not dates:
            table.add_row(cf.city, "[dim]no data[/dim]", *(["-"] * (3 + len(thresholds))))
            continue
        for i, date in enumerate(dates):
            cons = cf.consensus(date)
            prob_cells = []
            for t in thresholds:
                p = cons.p_high_over(t)
                prob_cells.append("-" if p is None else f"{p*100:.0f}%")
            conf_color = {"high": "green", "medium": "yellow", "low": "red"}[cons.confidence]
            table.add_row(
                cf.city if i == 0 else "",
                date,
                _fmt(cons.high_mean, "°", 1),
                _fmt(cons.high_std, "°", 1),
                f"[{conf_color}]{cons.confidence}[/{conf_color}]",
                *prob_cells,
            )
        table.add_section()

    console.print(table)
