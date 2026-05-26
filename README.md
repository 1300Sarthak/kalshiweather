# wedge — Weather Edge Scanner

`wedge` finds mispricings between professional multi-model weather forecasts and
[Kalshi](https://kalshi.com) prediction-market prices. It pulls daily forecasts from
Open-Meteo (ECMWF IFS, GFS, ICON), reads live Kalshi weather-market orderbooks, turns
the forecasts into contract-level probabilities via multi-model consensus, and ranks
contracts by **edge** (`model_probability − market_price`) with Kelly position sizing.
It's a terminal tool — scanner only, no order placement.

## Setup

Requires Python 3.11+. With [`uv`](https://docs.astral.sh/uv/):

```bash
uv venv
uv pip install -e .
```

Or with pip:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Environment variables

Kalshi market data (markets + orderbooks) is **public** — no credentials needed to scan.
Copy `.env.example` to `.env` to set optional values:

- `ECMWF_API_KEY` *(optional)* — if set, `wedge` uses the 51-member ECMWF ensemble for
  direct probabilities on temperature contracts. Unset, it falls back to the Open-Meteo
  multi-model normal-CDF approximation (the default; works with zero credentials).
- `WEDGE_BANKROLL`, `WEDGE_MIN_EDGE`, `WEDGE_MAX_KELLY`, `WEDGE_FORECAST_DAYS` — override
  defaults (500, 0.04, 0.25, 7). CLI flags take precedence.

## Usage

```bash
# Multi-model forecast table (ECMWF / GFS / ICON highs, spread, precip, wind)
wedge forecast --city NYC --days 5

# Forecast with consensus probabilities around a threshold
wedge forecast --city CHI --probs --threshold 90

# Live Kalshi weather contracts (bid/ask/mid/spread/volume)
wedge markets --city NYC --type temp_high

# The core product: ranked edges with Kelly sizing
wedge scan --min-edge 0.04 --bankroll 500 --city NYC

# Export results
wedge scan --export csv      # -> scans/scan_YYYYMMDD_HHMMSS.csv
wedge scan --export json     # -> scans/scan_YYYYMMDD_HHMMSS.json

# Detailed per-edge breakdown (per-model forecasts + orderbook depth)
wedge scan --city NYC --verbose

# Machine-readable output, one edge per line (pipe-friendly)
wedge scan --quiet
# STRONG,NYC,2026-05-26,high_over_77,0.94,0.21,+0.73,125.00

# Continuous scanning: re-scan, highlight new edges, ring the bell on new STRONG ones
wedge watch --interval 30 --city NYC

# Summarize recent exported scans
wedge history --last 5
```

Cities: `NYC, CHI, LA, MIA, DEN, PHX, SEA, HOU` (omit `--city` to scan all).
Types: `temp_high, temp_low, precip` (also `high, low, rain, wind`).

## How the edge is computed

1. **Forecasts** — fetch ECMWF IFS, GFS, and ICON daily forecasts from Open-Meteo per city.
2. **Probability** — for each Kalshi threshold, take the cross-model mean as the consensus
   and the cross-model standard deviation as uncertainty, then
   `P(high > T) = 1 − Φ((T − mean) / std)`. Precip uses an ECMWF-weighted model
   probability; single-model days fall back to fixed std (3°F highs, 4°F lows, 5 mph wind).
   With `ECMWF_API_KEY`, temperature probabilities come from the ensemble member count instead.
3. **Edge** — `edge = model_prob − market_mid`. A positive edge means the YES side looks
   underpriced (buy YES); a negative edge flips to the NO side. Signals: STRONG > 10¢,
   MODERATE > 6¢, WEAK > 3¢.
4. **Sizing** — full Kelly (`f* = (p·b − q)/b`) capped at 25% of bankroll. In practice you'd
   use half-Kelly; full Kelly is shown for clarity.

Untradeable penny / near-certain strikes (mid ≤ $0.02 or ≥ $0.98) are filtered out, since
their inflated "edges" come from effectively-settled markets rather than real mispricings.

## Disclaimer

For research and educational purposes only. Prediction markets carry real financial risk;
nothing here is financial advice. Forecasts and probabilities are estimates and can be wrong.
