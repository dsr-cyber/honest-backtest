from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .engine import LONG, SHORT, Entry


@dataclass(frozen=True)
class OpeningRangeBreakout:
    """Trade the first close outside the opening range, one trade a day.

    The signal bar's close is known only after the bar ends, so the entry
    fills at the next bar's open. The stop is a fraction of the range width
    away from the fill, the target a multiple of that risk, and the trail
    (if any) follows at a fixed distance. Anything still open is closed on
    the last bar of the session.
    """

    range_bars: int = 3
    stop_frac: float = 0.5
    target_r: float | None = 2.0
    trail_frac: float | None = None
    last_entry: str = "15:00"

    def entries(self, bars: pd.DataFrame) -> list[Entry]:
        ts = pd.to_datetime(bars["timestamp"])
        cutoff = pd.Timestamp(self.last_entry).time()
        out = []
        for _, idx in bars.groupby(ts.dt.date, sort=True).indices.items():
            if len(idx) <= self.range_bars + 1:
                continue
            day = bars.iloc[idx]
            hi = day["high"].iloc[: self.range_bars].max()
            lo = day["low"].iloc[: self.range_bars].min()
            width = hi - lo
            if width <= 0:
                continue
            closes = day["close"].to_numpy()
            times = ts.iloc[idx].dt.time.to_numpy()
            for k in range(self.range_bars, len(idx) - 1):
                if times[k + 1] > cutoff:
                    break
                side = LONG if closes[k] > hi else SHORT if closes[k] < lo else 0
                if side:
                    risk = self.stop_frac * width
                    out.append(Entry(
                        bar=int(idx[k + 1]),
                        side=side,
                        stop_dist=risk,
                        target_dist=None if self.target_r is None else self.target_r * risk,
                        trail_dist=None if self.trail_frac is None else self.trail_frac * width,
                        exit_bar=int(idx[-1]),
                    ))
                    break
        return out
