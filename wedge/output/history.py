"""Render summaries of past scans saved under scans/."""

from __future__ import annotations

import json
from pathlib import Path

from rich.table import Table

from .export import SCANS_DIR
from .table import console


def _load_scans(last: int) -> list[tuple[Path, dict]]:
    """Load the most recent JSON scans (newest first)."""
    files = sorted(SCANS_DIR.glob("scan_*.json"), reverse=True)[:last]
    out: list[tuple[Path, dict]] = []
    for f in files:
        try:
            out.append((f, json.loads(f.read_text())))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def render_history(last: int) -> None:
    if not SCANS_DIR.exists():
        console.print("[dim]No scans yet. Run `wedge scan --export json` first.[/dim]")
        return
    scans = _load_scans(last)
    if not scans:
        console.print("[dim]No JSON scans found in scans/. Use `wedge scan --export json`.[/dim]")
        return

    table = Table(title=f"Scan History (last {len(scans)})", header_style="bold cyan")
    table.add_column("Scan", style="dim")
    table.add_column("When")
    table.add_column("Edges", justify="right")
    table.add_column("Strong", justify="right")
    table.add_column("Top edge", justify="right")
    table.add_column("Top contract")
    table.add_column("Exposure", justify="right")

    for path, data in scans:
        results = data.get("results", [])
        strong = sum(1 for r in results if r.get("signal") == "STRONG")
        exposure = sum(float(r.get("bet_size", 0) or 0) for r in results)
        top = max(results, key=lambda r: float(r.get("edge", 0) or 0), default=None)
        if top:
            top_edge = f"+{float(top['edge'])*100:.0f}¢"
            tc = f"{top['city']} {top['contract_type']}{top['threshold']:g}"
        else:
            top_edge, tc = "-", "-"
        table.add_row(
            path.stem.replace("scan_", ""),
            data.get("scanned_at", "?"),
            str(len(results)),
            str(strong),
            top_edge,
            tc,
            f"${exposure:,.0f}",
        )

    console.print(table)
