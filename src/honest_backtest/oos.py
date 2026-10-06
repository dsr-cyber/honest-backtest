"""Two quick checks before believing a parameter set.

Out of sample: tune on the first part of the data, look at the rest once.
Neighbours: nudge each parameter one step either way. A real edge degrades
gently; a fitted one falls off a cliff next to the chosen value.
"""

from __future__ import annotations

from dataclasses import fields, replace

import pandas as pd

from .engine import FillModel, run
from .metrics import summarize


def split_by_day(bars: pd.DataFrame, in_sample: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 < in_sample < 1:
        raise ValueError("in_sample must be between 0 and 1")
    days = pd.to_datetime(bars["timestamp"]).dt.normalize()
    unique = days.unique()
    cut = unique[int(len(unique) * in_sample)]
    first = bars[days < cut].reset_index(drop=True)
    rest = bars[days >= cut].reset_index(drop=True)
    return first, rest


def neighbours(strategy, steps: dict[str, float]) -> list[tuple[str, object]]:
    out = [("base", strategy)]
    for name, step in steps.items():
        base = getattr(strategy, name)
        if base is None:
            continue
        for sign in (-1, 1):
            value = base + sign * step
            if isinstance(base, int):
                value = int(value)
            if value <= 0:
                continue
            out.append((f"{name}={value:g}", replace(strategy, **{name: value})))
    return out


def oos_table(
    bars: pd.DataFrame,
    strategy,
    steps: dict[str, float],
    costs=None,
    qty: float = 1,
    in_sample: float = 0.6,
    fills: FillModel | None = None,
) -> pd.DataFrame:
    known = {f.name for f in fields(strategy)}
    unknown = set(steps) - known
    if unknown:
        raise ValueError(f"unknown parameters: {', '.join(sorted(unknown))}")
    first, rest = split_by_day(bars, in_sample)
    rows = []
    for label, strat in neighbours(strategy, steps):
        a = summarize(run(first, strat.entries(first), fills, costs, qty))
        b = summarize(run(rest, strat.entries(rest), fills, costs, qty))
        rows.append({
            "params": label,
            "is_net": a["net"],
            "is_trades": a["trades"],
            "oos_net": b["net"],
            "oos_trades": b["trades"],
            "oos_pf": b["profit_factor"],
        })
    return pd.DataFrame(rows)
