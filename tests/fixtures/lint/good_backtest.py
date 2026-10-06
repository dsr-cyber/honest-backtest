from dataclasses import dataclass


@dataclass
class Costs:
    commission: float = 0.0
    slippage: float = 0.01


def simulate(bars, entry_bar, stop_dist, target_dist, trail_dist, qty, costs: Costs):
    entry = bars[entry_bar]["open"]
    stop = entry - stop_dist
    target = entry + target_dist
    exit_price = None
    for bar in bars[entry_bar:]:
        # Stop first: the open settles it if it is already through, otherwise
        # a bar that touches both levels is scored as a stop.
        if bar["low"] <= stop:
            exit_price = min(stop, bar["open"])
            break
        if bar["high"] >= target:
            exit_price = max(target, bar["open"])
            break
        # The trail moves on the close and applies from the next bar.
        stop = max(stop, bar["close"] - trail_dist)
    if exit_price is None:
        exit_price = bars[-1]["close"]
    gross = (exit_price - entry) * qty
    pnl = gross - 2 * (costs.commission + costs.slippage * qty)
    return pnl


def trail_from_closed_bar(highs, lows, i, stop, dist):
    stop = max(stop, highs[i - 1] - dist)
    if lows[i] <= stop:
        return stop
    return None


def trail_after_check(bar, stop, dist):
    if bar["low"] <= stop:
        return None
    stop = max(stop, bar["high"] - dist)
    return stop
