from pathlib import Path

import pandas as pd

from honest_backtest.cli import main

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_bars.csv"


def test_compare_prints_both_columns_and_steps(capsys):
    assert main(["compare", "--data", str(SAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "naive" in out and "honest" in out
    assert "profit factor" in out
    assert "+ costs" in out


def test_make_data(tmp_path):
    out = tmp_path / "bars.csv"
    assert main(["make-data", "--out", str(out), "--days", "3"]) == 0
    assert len(pd.read_csv(out)) == 3 * 78
