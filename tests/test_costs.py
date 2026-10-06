import math

import numpy as np
import pandas as pd
import pytest

from honest_backtest.costs import (
    BUY,
    SELL,
    PRESETS,
    IndiaIndexOptionCosts,
    SimpleCosts,
    USEquityCosts,
)
from honest_backtest.engine import LONG, Entry, FillModel, run
from honest_backtest.metrics import max_drawdown, profit_factor, summarize


def test_simple_costs():
    c = SimpleCosts(commission_per_order=1.0, slippage_per_unit=0.02, pct_on_buy=0.001, pct_on_sell=0.002)
    assert c.order(BUY, 50.0, 100) == pytest.approx(1.0 + 2.0 + 5.0)
    assert c.order(SELL, 50.0, 100) == pytest.approx(1.0 + 2.0 + 10.0)


def test_us_equity_fees_only_on_sells():
    c = USEquityCosts(slippage_per_unit=0.0)
    assert c.order(BUY, 50.0, 100) == 0.0
    sec = 5000 * 27.80 / 1e6
    taf = 100 * 0.000166
    assert c.order(SELL, 50.0, 100) == pytest.approx(sec + taf)


def test_finra_taf_is_capped():
    c = USEquityCosts(slippage_per_unit=0.0, sec_fee_per_million=0.0)
    assert c.order(SELL, 10.0, 100_000) == pytest.approx(8.30)


def test_india_buy_side():
    c = IndiaIndexOptionCosts()
    # 75 units at 100: premium 7,500
    exchange, sebi = 7500 * 0.0003503, 7500 * 0.000001
    expected = 20 + exchange + sebi + 0.18 * (20 + exchange + sebi) + 7500 * 0.00003 + 0.5 * 75
    assert c.order(BUY, 100.0, 75) == pytest.approx(expected)
    assert expected == pytest.approx(64.434005)


def test_india_stt_on_sell_premium_only():
    c = IndiaIndexOptionCosts(brokerage_per_order=0.0, slippage_per_unit=0.0)
    premium = 120.0 * 75
    diff = c.order(SELL, 120.0, 75) - c.order(BUY, 120.0, 75)
    assert diff == pytest.approx(premium * 0.0015 - premium * 0.00003)


def test_presets_exist():
    assert set(PRESETS) == {"none", "us-equity", "india-options"}
    assert PRESETS["none"].order(BUY, 100.0, 10) == 0.0


def test_engine_charges_both_legs():
    ts = pd.date_range("2026-01-05 09:30", periods=3, freq="5min")
    bars = pd.DataFrame({
        "timestamp": ts,
        "open": [50.0, 50.5, 51.0],
        "high": [50.6, 51.2, 51.5],
        "low": [49.9, 50.4, 50.9],
        "close": [50.5, 51.0, 51.2],
    })
    costs = SimpleCosts(commission_per_order=1.0, slippage_per_unit=0.01)
    t = run(bars, [Entry(0, LONG, stop_dist=2.0, exit_bar=2)], FillModel.honest(), costs, qty=100)[0]
    assert t.gross == pytest.approx(120.0)
    assert t.costs == pytest.approx(2 * (1.0 + 1.0))
    assert t.net == pytest.approx(116.0)


def test_profit_factor_and_drawdown():
    pnl = np.array([10.0, -5.0, -5.0, 20.0, -15.0])
    assert profit_factor(pnl) == pytest.approx(30 / 25)
    assert max_drawdown(pnl) == pytest.approx(-15.0)
    assert max_drawdown(np.array([-3.0, 1.0])) == pytest.approx(-3.0)
    assert math.isinf(profit_factor(np.array([1.0, 2.0])))


def test_summarize_empty():
    s = summarize([])
    assert s["trades"] == 0 and s["net"] == 0.0
    assert math.isnan(s["win_rate"])
