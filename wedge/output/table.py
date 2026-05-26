"""Rich table renderers for terminal output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ..kalshi.models import KalshiContract
from ..weather.models import CityForecast

console = Console()


def _price(v: float | None) -> str:
    return "-" if v is None else f"${v:.2f}"


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


_TYPE_LABEL = {
    "high_over": "High >", "high_under": "High <",
    "low_over": "Low >", "low_under": "Low <",
    "rain_over": "Rain >", "rain_under": "Rain <",
    "wind_over": "Wind >", "wind_under": "Wind <",
}


def contract_label(c: KalshiContract) -> str:
    """Human label like 'High >90°F' or 'Rain >0.1in'."""
    base = _TYPE_LABEL.get(c.contract_type, c.contract_type)
    thr = f"{c.threshold:g}{c.unit}"
    return f"{base}{thr}"


def render_markets(contracts: list[KalshiContract]) -> None:
    """Phase 2 markets table."""
    table = Table(title="Kalshi Weather Markets", header_style="bold cyan")
    table.add_column("Ticker", style="dim")
    table.add_column("City", style="bold")
    table.add_column("Date")
    table.add_column("Type")
    table.add_column("Thr", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Mid", justify="right")
    table.add_column("Spr", justify="right")
    table.add_column("Vol", justify="right")

    contracts = sorted(contracts, key=lambda c: (c.city, c.date, c.contract_type, c.threshold))
    for c in contracts:
        table.add_row(
            c.ticker,
            c.city,
            c.date,
            _TYPE_LABEL.get(c.contract_type, c.contract_type).strip(),
            f"{c.threshold:g}{c.unit}",
            _price(c.yes_bid),
            _price(c.yes_ask),
            _price(c.mid_price),
            _price(c.spread),
            f"{c.volume:,}",
        )
    console.print(table)
    console.print(f"[dim]{len(contracts)} open weather contracts[/dim]")


_SIGNAL_STYLE = {
    "STRONG": "bold green",
    "MODERATE": "yellow",
    "WEAK": "dim cyan",
    "NONE": "dim",
}


def _short_date(iso: str) -> str:
    try:
        from datetime import date
        d = date.fromisoformat(iso)
        return d.strftime("%b %d")
    except ValueError:
        return iso


def render_scan(results, min_edge: float, bankroll: float) -> None:
    """Phase 4 scan table: ranked edges with Kelly sizing."""
    table = Table(title="Weather Edge Scan", header_style="bold cyan")
    table.add_column("SIGNAL")
    table.add_column("SIDE", justify="center")
    table.add_column("CITY", style="bold")
    table.add_column("DATE")
    table.add_column("CONTRACT")
    table.add_column("FCST", justify="right")
    table.add_column("MODEL P", justify="right")
    table.add_column("MKT $", justify="right")
    table.add_column("EDGE", justify="right")
    table.add_column("KELLY %", justify="right")
    table.add_column("SIZE", justify="right")

    total = 0.0
    for r in results:
        c = r.contract
        style = _SIGNAL_STYLE.get(r.signal, "")
        fval = "-" if r.forecast_value is None else (
            f"{r.forecast_value:.2f}{c.unit}" if c.kind == "rain" else f"{r.forecast_value:.1f}{c.unit}"
        )
        total += r.bet_size
        table.add_row(
            f"[{style}]{r.signal}[/{style}]",
            "[green]YES[/green]" if r.side == "YES" else "[red]NO[/red]",
            c.city,
            _short_date(c.date),
            contract_label(c),
            fval,
            f"{r.model_prob*100:.0f}%",
            f"${r.market_price:.2f}",
            f"+{r.edge*100:.0f}¢",
            f"{r.kelly_pct*100:.1f}%",
            f"${r.bet_size:.0f}",
        )

    console.print(table)
    cents = int(round(min_edge * 100))
    console.print(
        f"[bold]Found {len(results)} edges above {cents}¢ threshold[/bold] | "
        f"Total suggested exposure: ${total:,.0f} / ${bankroll:,.0f} bankroll"
    )


def render_scan_verbose(results, orderbooks: dict | None = None) -> None:
    """Per-edge detail: model breakdown, spread/confidence, orderbook depth."""
    orderbooks = orderbooks or {}
    for r in results:
        c = r.contract
        models = "  ".join(f"{m}={v:g}" for m, v in r.model_values.items()) or "single-model"
        console.print(
            f"[bold]{r.signal}[/bold] {r.side} [cyan]{c.city}[/cyan] {c.date} "
            f"{contract_label(c)}  edge=+{r.edge*100:.0f}¢  kelly={r.kelly_pct*100:.1f}%  ${r.bet_size:.0f}"
        )
        agree = "[green]agree[/green]" if r.models_agree else "[red]disagree[/red]"
        console.print(
            f"    models: {models} | spread={r.model_spread:g}{c.unit} | "
            f"confidence={r.confidence} | {agree} | model P={r.model_prob*100:.0f}% vs mkt ${r.market_price:.2f}"
        )
        ob = orderbooks.get(c.ticker)
        if ob:
            yd = ob.get("yes_depth") or []
            nd = ob.get("no_depth") or []
            top_yes = ", ".join(f"${float(p):.2f}x{float(s):g}" for p, s in yd[-3:][::-1]) or "-"
            top_no = ", ".join(f"${float(p):.2f}x{float(s):g}" for p, s in nd[-3:][::-1]) or "-"
            console.print(f"    book: yes[{top_yes}]  no[{top_no}]")
        console.print()


def quiet_line(r, city_code: str) -> str:
    """Machine-readable one-line edge: signal,city,date,type_thr,p,mkt,edge,size."""
    c = r.contract
    edge_signed = f"+{r.edge:.2f}" if r.side == "YES" else f"-{r.edge:.2f}"
    type_thr = f"{c.contract_type}_{c.threshold:g}"
    return (
        f"{r.signal},{city_code},{c.date},{type_thr},"
        f"{r.model_prob:.2f},{r.market_price:.2f},{edge_signed},{r.bet_size:.2f}"
    )


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
