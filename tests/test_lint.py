from pathlib import Path

import pytest

from honest_backtest.cli import main as cli_main
from honest_backtest.lint import lint_source

FIXTURES = Path(__file__).parent / "fixtures" / "lint"


def found(name):
    path = FIXTURES / name
    return {(f.line, f.rule) for f in lint_source(path.read_text(encoding="utf-8"), str(path))}


def test_gap_fill():
    assert found("bad_gap_fill.py") == {(16, "HB001"), (28, "HB001"), (29, "HB001")}


def test_target_first():
    assert found("bad_target_first.py") == {
        (6, "HB002"),   # if / elif
        (16, "HB002"),  # two sibling ifs that both break
        (20, "HB001"),  # pnl from the stop level
        (26, "HB002"),  # tie-break that takes the target
    }


def test_intrabar_trail():
    assert found("bad_intrabar_trail.py") == {(11, "HB003")}


def test_no_costs():
    assert found("bad_no_costs.py") == {(10, "HB004")}


def test_lookahead():
    assert found("bad_lookahead.py") == {(6, "HB005"), (8, "HB005")}


def test_good_script_is_clean():
    assert found("good_backtest.py") == set()


def test_honest_stop_fill_passes():
    src = "fee = 1\nfor b in bars:\n    if b.low <= stop:\n        exit_price = min(stop, b.open)\n"
    assert lint_source(src) == []


def test_noqa():
    src = "fee = 1\nexit_price = stop  # noqa: HB001\nfill = stop_loss  # noqa\nexit_px = sl  # noqa: HB002\n"
    assert [(f.line, f.rule) for f in lint_source(src)] == [(4, "HB001")]


def test_short_side_names():
    src = "fees = 0\nif bar['High'] >= stopLoss:\n    coverPrice = stopLoss\n"
    assert [f.rule for f in lint_source(src)] == ["HB001"]


def test_cli_exit_codes(tmp_path, capsys):
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n")
    assert cli_main(["lint", str(clean)]) == 0
    assert cli_main(["lint", str(FIXTURES)]) == 1
    out = capsys.readouterr().out
    assert "bad_gap_fill.py:16:13: HB001" in out.replace("\\", "/")
    broken = tmp_path / "broken.py"
    broken.write_text("def oops(:\n")
    assert cli_main(["lint", str(broken)]) == 2
