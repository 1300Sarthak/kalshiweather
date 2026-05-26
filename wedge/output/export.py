"""CSV / JSON export of scan results."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from ..engine.scanner import EdgeResult

SCANS_DIR = Path("scans")

_FIELDS = [
    "signal", "side", "city", "date", "ticker", "contract_type", "threshold",
    "unit", "forecast_value", "model_prob", "market_price", "edge",
    "kelly_pct", "bet_size", "models_agree", "confidence", "volume",
]


def _row(r: EdgeResult) -> dict:
    c = r.contract
    return {
        "signal": r.signal,
        "side": r.side,
        "city": c.city,
        "date": c.date,
        "ticker": c.ticker,
        "contract_type": c.contract_type,
        "threshold": c.threshold,
        "unit": c.unit,
        "forecast_value": None if r.forecast_value is None else round(r.forecast_value, 2),
        "model_prob": round(r.model_prob, 4),
        "market_price": round(r.market_price, 4),
        "edge": round(r.edge, 4),
        "kelly_pct": round(r.kelly_pct, 4),
        "bet_size": r.bet_size,
        "models_agree": r.models_agree,
        "confidence": r.confidence,
        "volume": c.volume,
    }


def _timestamped_path(ext: str) -> Path:
    SCANS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return SCANS_DIR / f"scan_{ts}.{ext}"


def export_csv(results: list[EdgeResult]) -> Path:
    path = _timestamped_path("csv")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow(_row(r))
    return path


def export_json(results: list[EdgeResult]) -> Path:
    path = _timestamped_path("json")
    payload = {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(results),
        "results": [_row(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path
