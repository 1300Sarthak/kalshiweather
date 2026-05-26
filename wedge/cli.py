"""wedge CLI entrypoint."""

from __future__ import annotations

import asyncio

import click

from .config import CITIES, Config, resolve_city
from .http import client_session
from .kalshi import client as kalshi_client
from .kalshi.models import TYPE_ALIASES
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
def forecast(city: str | None, days: int | None) -> None:
    """Show multi-model weather forecasts."""
    cfg = Config()
    n_days = days or cfg.forecast_days
    cities = _select_cities(city)

    async def run():
        async with client_session() as client:
            return await open_meteo.fetch_all(client, cities, n_days)

    forecasts = asyncio.run(run())
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


if __name__ == "__main__":
    cli()
