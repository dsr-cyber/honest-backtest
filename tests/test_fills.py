import numpy as np
import pandas as pd
import pytest

from honest_backtest.engine import (
    LONG,
    SHORT,
    Backtest,
    Entry,
    FillModel,
    resolve_bar,
    run,
)

HONEST = FillModel.honest()
NAIVE = FillModel.naive()


def make_bars(rows, start="2026-01-05 09:30", freq="5min"):
    ts = pd.date_range(start, periods=len(rows), freq=freq)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"]).assign(timestamp=ts)


# gap-through


def test_long_stop_gapped_through_fills_at_open():
    ex = resolve_bar(LONG, o=95.0, h=96.0, l=94.0, stop=98.0, target=None, fills=HONEST)
    assert ex.kind == "stop"
    assert ex.price == 95.0
    assert ex.gap_through


def test_long_stop_inside_bar_fills_at_stop():
    ex = resolve_bar(LONG, o=99.0, h=99.5, l=97.0, stop=98.0, target=None, fills=HONEST)
    assert ex.price == 98.0
    assert not ex.gap_through


def test_short_stop_gapped_through_fills_at_open():
    ex = resolve_bar(SHORT, o=105.0, h=106.0, l=104.5, stop=102.0, target=None, fills=HONEST)
    assert ex.price == 105.0
    assert ex.gap_through


def test_naive_credits_the_stop_price_on_a_gap():
    ex = resolve_bar(LONG, o=95.0, h=96.0, l=94.0, stop=98.0, target=None, fills=NAIVE)
    assert ex.price == 98.0


def test_gap_through_in_a_full_run():
    bars = make_bars([
        (100.0, 100.5, 99.6, 100.2),
        (100.2, 100.4, 99.8, 100.0),
        (96.0, 97.0, 95.5, 96.5),  # opens 2 points under the 98 stop
    ])
    entry = Entry(bar=0, side=LONG, stop_dist=2.0)
    honest = run(bars, [entry], HONEST)[0]
    naive = run(bars, [entry], NAIVE)[0]
    assert honest.exit_price == 96.0 and honest.gross == -4.0
    assert naive.exit_price == 98.0 and naive.gross == -2.0


# collision


def test_collision_goes_to_stop_when_honest():
    ex = resolve_bar(LONG, o=100.0, h=103.0, l=97.0, stop=98.0, target=102.0, fills=HONEST)
    assert ex.kind == "stop"
    assert ex.price == 98.0
    assert ex.collision


def test_collision_goes_to_target_when_naive():
    ex = resolve_bar(LONG, o=100.0, h=103.0, l=97.0, stop=98.0, target=102.0, fills=NAIVE)
    assert ex.kind == "target"
    assert ex.price == 102.0


def test_open_beyond_target_is_not_a_collision():
    ex = resolve_bar(LONG, o=102.5, h=103.0, l=97.0, stop=98.0, target=102.0, fills=HONEST)
    assert ex.kind == "target"
    assert not ex.collision


def test_short_collision_goes_to_stop():
    ex = resolve_bar(SHORT, o=100.0, h=103.0, l=97.0, stop=102.0, target=98.0, fills=HONEST)
    assert ex.kind == "stop"
    assert ex.price == 102.0


def test_fine_bars_settle_a_collision():
    # The 1-minute bars show the target traded first.
    fine = np.array([
        [100.0, 102.5, 99.5],
        [102.4, 102.6, 97.5],
    ])
    ex = resolve_bar(LONG, o=100.0, h=102.6, l=97.5, stop=98.0, target=102.0, fills=HONEST, fine=fine)
    assert ex.kind == "target"
    assert ex.collision


def test_fine_bars_wired_through_backtest():
    bars = make_bars([
        (100.0, 100.4, 99.8, 100.1),
        (100.1, 102.6, 97.5, 99.0),
    ])
    fine = make_bars(
        [
            (100.1, 100.3, 97.6, 97.9),  # stop at 98 first
            (97.9, 102.6, 97.5, 99.0),
        ],
        start="2026-01-05 09:35",
        freq="1min",
    )
    entry = Entry(bar=0, side=LONG, stop_dist=2.0, target_dist=2.0)
    t = Backtest(bars, HONEST, fine=fine).run([entry])[0]
    assert t.reason == "stop" and t.exit_price == 98.0

    fine.loc[0, ["high", "low"]] = [102.2, 99.9]  # now the target trades first
    t = Backtest(bars, HONEST, fine=fine).run([entry])[0]
    assert t.reason == "target" and t.exit_price == 102.0


# trailing


def trail_bars():
    return make_bars([
        (100.0, 100.5, 99.8, 100.4),
        (100.4, 104.0, 100.3, 100.6),  # spikes to 104 and closes back near entry
        (100.6, 100.9, 100.0, 100.2),
        (100.2, 100.3, 99.0, 99.2),
    ])


def test_naive_trails_off_the_same_bars_high():
    entry = Entry(bar=0, side=LONG, stop_dist=1.5, trail_dist=1.5)
    t = run(trail_bars(), [entry], NAIVE)[0]
    # The stop jumps to 104 - 1.5 = 102.5 inside the spike bar and is "hit" in the same bar.
    assert t.reason == "trail"
    assert t.exit_price == 102.5
    assert t.exit_time == pd.Timestamp("2026-01-05 09:35")


def test_honest_trails_on_close_only():
    entry = Entry(bar=0, side=LONG, stop_dist=1.5, trail_dist=1.5)
    t = run(trail_bars(), [entry], HONEST)[0]
    # Closes 100.4, 100.6, 100.2 lift the stop to 99.1, which bar 3 hits.
    assert t.reason == "trail"
    assert t.exit_price == pytest.approx(99.1)
    assert t.exit_time == pd.Timestamp("2026-01-05 09:45")


def test_trail_never_loosens():
    entry = Entry(bar=0, side=SHORT, stop_dist=1.0, trail_dist=1.0)
    bars = make_bars([
        (100.0, 100.2, 99.0, 99.1),
        (99.1, 99.5, 98.9, 99.4),
        (99.4, 100.2, 99.3, 100.0),
    ])
    t = run(bars, [entry], HONEST)[0]
    # Stop: 101 -> 100.1 after bar 0, stays 100.1 after bar 1 (close 99.4 would give 100.4).
    assert t.exit_price == pytest.approx(100.1)


# bookkeeping


def test_forced_exit_at_close_of_exit_bar():
    bars = make_bars([(100, 101, 99.5, 100.5)] * 4)
    t = run(bars, [Entry(bar=0, side=LONG, stop_dist=5.0, exit_bar=2)], HONEST)[0]
    assert t.reason == "close"
    assert t.exit_time == pd.Timestamp("2026-01-05 09:40")


def test_overlapping_entries_are_skipped():
    bars = make_bars([(100, 101, 99.5, 100.5)] * 6)
    entries = [
        Entry(bar=0, side=LONG, stop_dist=5.0, exit_bar=3),
        Entry(bar=2, side=LONG, stop_dist=5.0, exit_bar=4),
        Entry(bar=4, side=SHORT, stop_dist=5.0, exit_bar=5),
    ]
    trades = run(bars, entries, HONEST)
    assert [t.side for t in trades] == [LONG, SHORT]


def test_bad_side_raises():
    bars = make_bars([(100, 101, 99, 100)])
    with pytest.raises(ValueError):
        run(bars, [Entry(bar=0, side=0, stop_dist=1.0)])


def test_missing_columns_raise():
    with pytest.raises(ValueError, match="close"):
        Backtest(pd.DataFrame({"timestamp": [], "open": [], "high": [], "low": []}))
