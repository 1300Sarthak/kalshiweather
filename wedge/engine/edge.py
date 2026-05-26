"""Edge computation: model probability vs market mid price."""

from __future__ import annotations


def compute_edge(model_prob: float, market_mid: float) -> float:
    """Edge = model probability - market mid price.

    Positive => model says YES is underpriced (buy YES).
    """
    return model_prob - market_mid


def edge_signal(edge: float) -> str:
    """Classify the magnitude of a (positive) edge."""
    if edge > 0.10:
        return "STRONG"
    if edge > 0.06:
        return "MODERATE"
    if edge > 0.03:
        return "WEAK"
    return "NONE"
