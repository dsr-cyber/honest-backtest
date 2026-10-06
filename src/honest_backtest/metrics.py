from __future__ import annotations

import math

import numpy as np

from .engine import Trade


def profit_factor(pnl: np.ndarray) -> float:
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    if losses == 0:
        return math.inf if wins > 0 else math.nan
    return float(wins / losses)


def max_drawdown(pnl: np.ndarray) -> float:
    """Largest peak-to-trough fall of the cumulative P&L, starting from zero."""
    equity = np.concatenate([[0.0], np.cumsum(pnl)])
    return float((equity - np.maximum.accumulate(equity)).min())


def summarize(trades: list[Trade]) -> dict:
    net = np.array([t.net for t in trades], dtype=float)
    return {
        "trades": len(trades),
        "win_rate": float((net > 0).mean()) if len(net) else math.nan,
        "gross": float(sum(t.gross for t in trades)),
        "costs": float(sum(t.costs for t in trades)),
        "net": float(net.sum()),
        "profit_factor": profit_factor(net),
        "max_drawdown": max_drawdown(net),
        "gap_throughs": sum(t.gap_through for t in trades),
        "collisions": sum(t.collision for t in trades),
    }
