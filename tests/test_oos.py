import pandas as pd
import pytest

from honest_backtest.cli import main
from honest_backtest.costs import PRESETS
from honest_backtest.data import make_sample_bars
from honest_backtest.oos import neighbours, oos_table, split_by_day
from honest_backtest.strategy import OpeningRangeBreakout


@pytest.fixture(scope="module")
def bars():
    return make_sample_bars(days=20)


def test_split_keeps_whole_days(bars):
    first, rest = split_by_day(bars, 0.6)
    assert len(first) + len(rest) == len(bars)
    assert first["timestamp"].dt.date.nunique() == 12
    assert first["timestamp"].iloc[-1] < rest["timestamp"].iloc[0]
    assert first["timestamp"].iloc[-1].date() != rest["timestamp"].iloc[0].date()


def test_split_rejects_bad_fraction(bars):
    with pytest.raises(ValueError):
        split_by_day(bars, 1.0)


def test_neighbours():
    labels = [label for label, _ in neighbours(OpeningRangeBreakout(), {"range_bars": 1, "stop_frac": 0.1})]
    assert labels == ["base", "range_bars=2", "range_bars=4", "stop_frac=0.4", "stop_frac=0.6"]


def test_neighbours_skip_unset_and_nonpositive():
    strat = OpeningRangeBreakout(range_bars=1, trail_frac=None)
    labels = [label for label, _ in neighbours(strat, {"range_bars": 1, "trail_frac": 0.1})]
    assert labels == ["base", "range_bars=2"]


def test_table(bars):
    table = oos_table(bars, OpeningRangeBreakout(), {"target_r": 0.5}, PRESETS["us-equity"], qty=100)
    assert list(table["params"]) == ["base", "target_r=1.5", "target_r=2.5"]
    assert (table["is_trades"] > 0).all()


def test_table_rejects_unknown_param(bars):
    with pytest.raises(ValueError, match="nope"):
        oos_table(bars, OpeningRangeBreakout(), {"nope": 1})


def test_oos_cli(capsys, tmp_path):
    path = tmp_path / "bars.csv"
    make_sample_bars(days=10).to_csv(path, index=False)
    assert main(["oos", "--data", str(path)]) == 0
    assert "OOS net" in capsys.readouterr().out
