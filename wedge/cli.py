"""wedge CLI entrypoint."""

from __future__ import annotations

import asyncio

import click

from .config import CITIES, Config, resolve_city
from .http import client_session
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


if __name__ == "__main__":
    cli()
