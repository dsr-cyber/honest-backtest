from pathlib import Path

import pandas as pd
import pytest

from honest_backtest.data import load_bars, make_sample_bars
from honest_backtest.engine import LONG, SHORT
from honest_backtest.strategy import OpeningRangeBreakout

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_bars.csv"


def day_bars(closes, start="2026-01-05 09:30"):
    ts = pd.date_range(start, periods=len(closes), freq="5min")
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "timestamp": ts,
        "open": closes.shift(fill_value=closes.iloc[0]),
        "high": closes + 0.1,
        "low": closes - 0.1,
        "close": closes,
    })


def test_orb_enters_on_next_bar_after_breakout():
    bars = day_bars([100, 100.5, 99.8, 100.2, 100.9, 101.0, 101.2])
    # Range of the first 3 bars: 99.7 to 100.6. Bar 4 closes at 100.9, so we buy bar 5's open.
    (e,) = OpeningRangeBreakout().entries(bars)
    assert e.side == LONG
    assert e.bar == 5
    assert e.stop_dist == pytest.approx(0.5 * (100.6 - 99.7))
    assert e.target_dist == 2 * e.stop_dist
    assert e.exit_bar == 6


def test_orb_short_and_one_trade_per_day():
    bars = day_bars([100, 100.5, 99.8, 99.5, 101.5, 98.0, 98.0])
    entries = OpeningRangeBreakout().entries(bars)
    assert [(e.side, e.bar) for e in entries] == [(SHORT, 4)]


def test_orb_respects_last_entry_time():
    bars = day_bars([100, 100.5, 99.8, 100.2, 100.9, 101.0], start="2026-01-05 14:40")
    assert OpeningRangeBreakout(last_entry="14:55").entries(bars) == []


def test_sample_data_is_deterministic():
    a = make_sample_bars(days=5)
    b = make_sample_bars(days=5)
    pd.testing.assert_frame_equal(a, b)
    assert (a["high"] >= a[["open", "close"]].max(axis=1)).all()
    assert (a["low"] <= a[["open", "close"]].min(axis=1)).all()


def test_bundled_csv_matches_generator():
    pd.testing.assert_frame_equal(load_bars(SAMPLE), make_sample_bars(), check_dtype=False)
