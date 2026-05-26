"""wedge CLI entrypoint."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import click

from .config import CITIES, Config, resolve_city
from .engine import scanner
from .http import client_session
from .kalshi import client as kalshi_client
from .kalshi.models import TYPE_ALIASES
from .output import export as out_export
from .output import history as out_history
from .output import table as out_table
from .weather import open_meteo


def _select_cities(city: str | None):
    if not city:
        return CITIES
    resolved = resolve_city(city)
    if resolved is None:
        raise click.BadParameter(
            f"unknown city {city!r}. Known: " + ", ".join(c.code for c in CITIES)
        )
    return [resolved]


@click.group()
@click.version_option(package_name="wedge")
def cli() -> None:
    """wedge — find edges between weather models and Kalshi markets."""


@cli.command()
@click.option("--city", default=None, help="City code (e.g. NYC) or name; default all.")
@click.option("--days", default=None, type=int, help="Forecast days to show (default 7).")
@click.option("--probs", is_flag=True, help="Show consensus high + P(>threshold) columns.")
@click.option("--threshold", default=None, type=float, help="Center threshold for --probs (default 90).")
def forecast(city: str | None, days: int | None, probs: bool, threshold: float | None) -> None:
    """Show multi-model weather forecasts."""
    cfg = Config()
    n_days = days or cfg.forecast_days
    cities = _select_cities(city)

    async def run():
        async with client_session() as client:
            return await open_meteo.fetch_all(client, cities, n_days)

    forecasts = asyncio.run(run())
    if probs:
        center = threshold if threshold is not None else 90.0
        thresholds = [center - 5, center, center + 5]
        out_table.render_forecast_probs(forecasts, n_days, thresholds)
    else:
        out_table.render_forecast(forecasts, n_days)


def _resolve_kinds(type_opt: str | None) -> set[str] | None:
    if not type_opt:
        return None
    kind = TYPE_ALIASES.get(type_opt.lower())
    if kind is None:
        raise click.BadParameter(
            f"unknown type {type_opt!r}. Choose from: " + ", ".join(sorted(TYPE_ALIASES))
        )
    return {kind}


@cli.command()
@click.option("--city", default=None, help="City code (e.g. NYC) or name; default all.")
@click.option("--type", "type_opt", default=None, help="Contract type: temp_high, temp_low, precip.")
def markets(city: str | None, type_opt: str | None) -> None:
    """List live Kalshi weather market contracts."""
    cities = _select_cities(city)
    kinds = _resolve_kinds(type_opt)

    async def run():
        async with client_session() as client:
            return await kalshi_client.get_weather_markets(client, cities, kinds)

    try:
        contracts = asyncio.run(run())
    except kalshi_client.KalshiUnavailable as exc:
        out_table.console.print(f"[yellow]Kalshi API unavailable: {exc}[/yellow]")
        return
    if not contracts:
        out_table.console.print("[yellow]No open weather contracts found.[/yellow]")
        return
    out_table.render_markets(contracts)


_CODE_BY_NAME = {c.name: c.code for c in CITIES}


def _render_results(results, cfg, verbose: bool, quiet: bool) -> None:
    """Render scan results in normal, verbose, or quiet mode."""
    if quiet:
        for r in results:
            click.echo(out_table.quiet_line(r, _CODE_BY_NAME.get(r.contract.city, r.contract.city)))
        return
    out_table.render_scan(results, cfg.min_edge, cfg.bankroll)
    if verbose:
        out_table.console.print()
        books = asyncio.run(scanner.fetch_orderbooks(results))
        out_table.render_scan_verbose(results, books)


@cli.command()
@click.option("--min-edge", default=None, type=float, help="Minimum edge to report (default 0.04).")
@click.option("--bankroll", default=None, type=float, help="Bankroll for Kelly sizing (default 500).")
@click.option("--city", default=None, help="City code (e.g. NYC) or name; default all.")
@click.option("--type", "type_opt", default=None, help="Contract type: temp_high, temp_low, precip.")
@click.option("--export", "export_fmt", type=click.Choice(["csv", "json"]), default=None,
              help="Export results to scans/.")
@click.option("--verbose", is_flag=True, help="Show per-model forecasts and orderbook depth.")
@click.option("--quiet", is_flag=True, help="One machine-readable edge per line.")
def scan(min_edge, bankroll, city, type_opt, export_fmt, verbose, quiet) -> None:
    """Scan for edges between weather models and Kalshi prices."""
    cfg = Config()
    if min_edge is not None:
        cfg.min_edge = min_edge
    if bankroll is not None:
        cfg.bankroll = bankroll
    cities = _select_cities(city)
    kinds = _resolve_kinds(type_opt)

    results, kalshi_ok = asyncio.run(scanner.scan(cfg, cities, kinds))
    if not kalshi_ok:
        if not quiet:
            out_table.console.print(
                "[yellow]Kalshi API unavailable — cannot scan for edges (weather-only mode).[/yellow]"
            )
        return
    if not results:
        if not quiet:
            out_table.console.print(
                f"[dim]No edges above {int(round(cfg.min_edge*100))}¢ — models and markets agree.[/dim]"
            )
        return

    _render_results(results, cfg, verbose, quiet)
    if export_fmt == "csv":
        path = out_export.export_csv(results)
        if not quiet:
            out_table.console.print(f"[dim]Exported to {path}[/dim]")
    elif export_fmt == "json":
        path = out_export.export_json(results)
        if not quiet:
            out_table.console.print(f"[dim]Exported to {path}[/dim]")


@cli.command()
@click.option("--interval", default=30, type=float, help="Minutes between scans (default 30).")
@click.option("--min-edge", default=None, type=float, help="Minimum edge to report (default 0.04).")
@click.option("--bankroll", default=None, type=float, help="Bankroll for Kelly sizing (default 500).")
@click.option("--city", default=None, help="City code (e.g. NYC) or name; default all.")
@click.option("--type", "type_opt", default=None, help="Contract type: temp_high, temp_low, precip.")
def watch(interval, min_edge, bankroll, city, type_opt) -> None:
    """Continuously re-scan, highlighting new edges and ringing on new STRONG ones."""
    cfg = Config()
    if min_edge is not None:
        cfg.min_edge = min_edge
    if bankroll is not None:
        cfg.bankroll = bankroll
    cities = _select_cities(city)
    kinds = _resolve_kinds(type_opt)

    seen: set[str] = set()
    try:
        while True:
            results, kalshi_ok = asyncio.run(scanner.scan(cfg, cities, kinds))
            out_table.console.clear()
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            out_table.console.print(f"[dim]wedge watch — {stamp} (every {interval:g} min, Ctrl-C to stop)[/dim]")
            if not kalshi_ok:
                out_table.console.print("[yellow]Kalshi API unavailable; retrying next cycle.[/yellow]")
            elif not results:
                out_table.console.print(f"[dim]No edges above {int(round(cfg.min_edge*100))}¢.[/dim]")
            else:
                current = {r.contract.ticker for r in results}
                new_tickers = current - seen
                new_strong = any(
                    r.signal == "STRONG" and r.contract.ticker in new_tickers for r in results
                )
                out_table.render_scan(results, cfg.min_edge, cfg.bankroll)
                if new_tickers:
                    fresh = ", ".join(sorted(new_tickers))
                    out_table.console.print(f"[bold green]NEW edges:[/bold green] {fresh}")
                if new_strong:
                    print("\a", end="", flush=True)  # bell on new STRONG edge
                seen = current
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        out_table.console.print("\n[dim]watch stopped.[/dim]")


@cli.command()
@click.option("--last", default=5, type=int, help="Number of recent scans to summarize.")
def history(last) -> None:
    """Summarize past scan results saved under scans/."""
    out_history.render_history(last)


if __name__ == "__main__":
    cli()
