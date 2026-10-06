import pandas as pd

COMMISSION = 1.0


def backtest(df: pd.DataFrame, stop_pts: float, qty: int) -> list[float]:
    results = []
    in_trade = False
    for row in df.itertuples():
        if not in_trade and row.signal:
            entry = row.open
            stop = entry - stop_pts
            in_trade = True
            continue
        if in_trade and row.low <= stop:
            exit_price = stop
            results.append((exit_price - entry) * qty - 2 * COMMISSION)
            in_trade = False
    return results


def close_trade(trade, price):
    trade["exit"] = price


def on_bar(trade, bar):
    if bar["low"] <= trade["sl"]:
        close_trade(trade, price=trade["sl"])
        pnl = (trade["sl"] - trade["entry"]) * trade["qty"] - COMMISSION
        return pnl
