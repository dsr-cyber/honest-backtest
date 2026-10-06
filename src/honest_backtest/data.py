"""Loading bars, and the synthetic sample series used by `compare`.

The sample series is made up. It is a random walk with fat-tailed returns,
a U-shaped intraday volatility profile, overnight gaps and the occasional
jump between two 5-minute bars. It has no edge to find, which is the point:
any profit a backtest reports on it comes from the fill model, not the market.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .engine import check_bars

SAMPLE_SEED = 20260105
SESSION_MINUTES = 390  # 09:30 to 16:00


def load_bars(path: str | Path) -> pd.DataFrame:
    bars = pd.read_csv(path, parse_dates=["timestamp"])
    check_bars(bars)
    return bars


def _fat_tails(rng: np.random.Generator, df: float, size) -> np.ndarray:
    # Student t scaled to unit variance.
    return rng.standard_t(df, size) / np.sqrt(df / (df - 2))


def make_sample_bars(
    days: int = 250,
    seed: int = SAMPLE_SEED,
    start: str = "2025-01-02",
    bar_minutes: int = 5,
    start_price: float = 50.0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=days)
    n_bars = SESSION_MINUTES // bar_minutes

    minute = np.arange(SESSION_MINUTES)
    profile = 1 + 1.5 * np.exp(-minute / 30) + 0.8 * np.exp(-(SESSION_MINUTES - 1 - minute) / 30)
    profile /= np.sqrt((profile**2).mean())

    rows = []
    price = start_price
    for day in dates:
        day_vol = 0.016 * rng.lognormal(0.0, 0.35)
        price *= np.exp(0.45 * day_vol * _fat_tails(rng, 3, None))

        rets = day_vol / np.sqrt(SESSION_MINUTES) * profile * _fat_tails(rng, 4, SESSION_MINUTES)
        path = price * np.exp(np.cumsum(rets))
        wick = np.abs(rng.normal(0, 0.5, SESSION_MINUTES)) * day_vol / np.sqrt(SESSION_MINUTES) * path

        # Rare jumps land between bars, so the next bar opens away from the last close.
        jumps = np.zeros(n_bars)
        hit = rng.random(n_bars) < 0.004
        hit[0] = False
        jumps[hit] = 0.6 * day_vol * _fat_tails(rng, 3, hit.sum())
        path *= np.repeat(np.exp(np.cumsum(jumps)), bar_minutes)

        prev_close = price
        times = day + pd.Timedelta(hours=9, minutes=30) + pd.to_timedelta(np.arange(n_bars) * bar_minutes, "min")
        for b in range(n_bars):
            seg = slice(b * bar_minutes, (b + 1) * bar_minutes)
            closes = path[seg]
            o = prev_close * np.exp(jumps[b]) if b else prev_close
            hi = max(o, (closes + wick[seg]).max())
            lo = min(o, (closes - wick[seg]).min())
            rows.append((times[b], o, hi, lo, closes[-1]))
            prev_close = closes[-1]
        price = prev_close

    bars = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    px = bars[["open", "high", "low", "close"]].round(2)
    px["high"] = px.max(axis=1)
    px["low"] = px.min(axis=1)
    bars[["open", "high", "low", "close"]] = px
    vol_profile = np.tile(profile.reshape(n_bars, bar_minutes).mean(axis=1), days)
    bars["volume"] = (rng.lognormal(9.5, 0.4, len(bars)) * vol_profile).round().astype(int)
    return bars


def write_sample_bars(path: str | Path, **kwargs) -> pd.DataFrame:
    bars = make_sample_bars(**kwargs)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    bars.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M", lineterminator="\n")
    return bars
