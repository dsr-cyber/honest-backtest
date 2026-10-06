FEES = 0.5


def exit_long(bars, entry, sl, tp):
    for bar in bars:
        if bar.high >= tp:
            return tp - entry - FEES
        elif bar.low <= sl:
            return sl - entry - FEES
    return bars[-1].close - entry - FEES


def exit_long_loop(highs, lows, entry, stop_loss, take_profit):
    pnl = 0.0
    for i in range(len(highs)):
        if highs[i] >= take_profit:
            pnl = take_profit - entry
            break
        if lows[i] <= stop_loss:
            pnl = stop_loss - entry
            break
    return pnl - FEES


def exit_with_tie_break(bar, entry, stop, target):
    if bar.low <= stop and bar.high >= target:
        exit_price = target
    elif bar.low <= stop:
        exit_price = min(stop, bar.open)
    else:
        exit_price = None
    return exit_price
