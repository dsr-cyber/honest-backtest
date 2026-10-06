"""Bar-by-bar exit simulation with an explicit fill model.

Strategies hand the engine a list of entries. The engine fills each entry at
the open of its bar and then walks forward bar by bar until the stop, the
target or the forced exit bar closes the trade. Everything that decides an
exit price lives in `resolve_bar`, so it can be tested on a single bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, NamedTuple, Protocol

import numpy as np
import pandas as pd

LONG = 1
SHORT = -1

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")


@dataclass(frozen=True)
class FillModel:
    # Long stop fills at min(stop, open) when the bar opens through it.
    honest_stops: bool = True
    # Stop and target both inside one bar: the stop is assumed to come first.
    stop_first: bool = True
    # Trailing stops move on the bar close and apply from the next bar.
    trail_on_close: bool = True

    @classmethod
    def honest(cls) -> "FillModel":
        return cls(True, True, True)

    @classmethod
    def naive(cls) -> "FillModel":
        return cls(False, False, False)


class CostModel(Protocol):
    def order(self, side: int, price: float, qty: float) -> float: ...


@dataclass(frozen=True)
class Entry:
    bar: int
    side: int
    stop_dist: float
    target_dist: float | None = None
    trail_dist: float | None = None
    exit_bar: int | None = None


@dataclass(frozen=True)
class Trade:
    side: int
    qty: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    reason: str
    gross: float
    costs: float
    gap_through: bool = False
    collision: bool = False

    @property
    def net(self) -> float:
        return self.gross - self.costs


class Exit(NamedTuple):
    kind: str  # "stop" or "target"
    price: float
    gap_through: bool = False
    collision: bool = False


def resolve_bar(
    side: int,
    o: float,
    h: float,
    l: float,
    stop: float,
    target: float | None,
    fills: FillModel,
    fine: np.ndarray | None = None,
    stop_at_open: float | None = None,
) -> Exit | None:
    """Decide whether this bar exits the trade, and at what price.

    `fine` is an optional (n, 3) array of open/high/low for finer bars inside
    this bar. It is only used to break a stop/target collision.
    `stop_at_open` is the stop that was resting when the bar opened, if an
    intrabar trail has since moved it. Only that one can be gapped through.
    """
    if side == SHORT:
        # A short is a long on the negated price series, with high and low swapped.
        neg_fine = None if fine is None else -fine[:, [0, 2, 1]]
        ex = resolve_bar(LONG, -o, -l, -h, -stop, _neg(target), fills, neg_fine, _neg(stop_at_open))
        return None if ex is None else ex._replace(price=-ex.price)

    if stop_at_open is None:
        stop_at_open = stop

    stop_hit = l <= stop
    target_hit = target is not None and h >= target
    if not (stop_hit or target_hit):
        return None

    # Flags are set in both modes, so a naive run can report how many of its
    # stop fills were at prices that never traded.
    def stop_exit(collision: bool = False) -> Exit:
        gapped = o < stop_at_open
        price = o if gapped and fills.honest_stops else stop
        return Exit("stop", price, gap_through=gapped, collision=collision)

    if not fills.stop_first:
        if target_hit:
            return Exit("target", target, collision=stop_hit)
        return stop_exit()

    # The open is the first traded price of the bar, so it settles the order
    # when it is already beyond either level.
    if o <= stop_at_open:
        return stop_exit()
    if target_hit and o >= target:
        return Exit("target", target)
    if stop_hit and target_hit:
        if fine is not None and len(fine):
            return _resolve_with_fine(stop, target, fine, fills)
        return stop_exit(collision=True)
    return stop_exit() if stop_hit else Exit("target", target)


def _neg(x: float | None) -> float | None:
    return None if x is None else -x


def _resolve_with_fine(stop: float, target: float, fine: np.ndarray, fills: FillModel) -> Exit:
    for fo, fh, fl in fine:
        ex = resolve_bar(LONG, fo, fh, fl, stop, target, fills)
        if ex is not None:
            return ex._replace(collision=True)
    # The fine bars never touched either level, so they don't match the coarse
    # bar. Fall back to the conservative answer.
    return Exit("stop", stop, collision=True)


def _tighten(side: int, stop: float, candidate: float) -> float:
    return max(stop, candidate) if side == LONG else min(stop, candidate)


def check_bars(bars: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"bars are missing columns: {', '.join(missing)}")
    if not bars["timestamp"].is_monotonic_increasing:
        raise ValueError("bars must be sorted by timestamp")


class Backtest:
    """Runs entries against one bar series.

    Timestamps label the start of each bar. If `fine` bars are given, the
    fine bars whose timestamps fall inside a coarse bar are used to decide
    stop/target collisions in that bar.
    """

    def __init__(
        self,
        bars: pd.DataFrame,
        fills: FillModel | None = None,
        costs: CostModel | None = None,
        qty: float = 1,
        fine: pd.DataFrame | None = None,
    ):
        check_bars(bars)
        self.fills = fills or FillModel.honest()
        self.costs = costs
        self.qty = qty
        self.ts = pd.to_datetime(bars["timestamp"]).to_numpy()
        self.o = bars["open"].to_numpy(float)
        self.h = bars["high"].to_numpy(float)
        self.l = bars["low"].to_numpy(float)
        self.c = bars["close"].to_numpy(float)
        self._fine = None
        if fine is not None:
            check_bars(fine)
            self._fine_ts = pd.to_datetime(fine["timestamp"]).to_numpy()
            self._fine = fine[["open", "high", "low"]].to_numpy(float)

    def __len__(self) -> int:
        return len(self.o)

    def fine_bars(self, j: int) -> np.ndarray | None:
        if self._fine is None:
            return None
        lo = np.searchsorted(self._fine_ts, self.ts[j], side="left")
        if j + 1 < len(self.ts):
            hi = np.searchsorted(self._fine_ts, self.ts[j + 1], side="left")
        else:
            hi = len(self._fine_ts)
        return self._fine[lo:hi]

    def run(self, entries: Iterable[Entry]) -> list[Trade]:
        trades: list[Trade] = []
        flat_after = -1
        for e in sorted(entries, key=lambda e: e.bar):
            if e.bar <= flat_after or e.bar >= len(self):
                continue
            trade, exit_bar = self._run_one(e)
            trades.append(trade)
            flat_after = exit_bar
        return trades

    def _run_one(self, e: Entry) -> tuple[Trade, int]:
        if e.side not in (LONG, SHORT):
            raise ValueError(f"side must be LONG or SHORT, got {e.side}")
        s, fills = e.side, self.fills
        last = len(self) - 1 if e.exit_bar is None else min(e.exit_bar, len(self) - 1)
        entry_px = self.o[e.bar]
        stop = initial_stop = entry_px - s * e.stop_dist
        target = None if e.target_dist is None else entry_px + s * e.target_dist

        ex: Exit | None = None
        j = e.bar
        for j in range(e.bar, last + 1):
            resting = stop
            if e.trail_dist is not None and not fills.trail_on_close:
                extreme = self.h[j] if s == LONG else self.l[j]
                stop = _tighten(s, stop, extreme - s * e.trail_dist)
            ex = resolve_bar(
                s, self.o[j], self.h[j], self.l[j], stop, target, fills, self.fine_bars(j), resting
            )
            if ex is not None:
                break
            if e.trail_dist is not None and fills.trail_on_close:
                stop = _tighten(s, stop, self.c[j] - s * e.trail_dist)

        if ex is None:
            exit_px, reason = self.c[last], "close"
        else:
            exit_px = ex.price
            reason = ex.kind
            if reason == "stop" and stop != initial_stop:
                reason = "trail"

        gross = s * (exit_px - entry_px) * self.qty
        costs = 0.0
        if self.costs is not None:
            costs = self.costs.order(s, entry_px, self.qty) + self.costs.order(-s, exit_px, self.qty)
        trade = Trade(
            side=s,
            qty=self.qty,
            entry_time=pd.Timestamp(self.ts[e.bar]),
            exit_time=pd.Timestamp(self.ts[j]),
            entry_price=float(entry_px),
            exit_price=float(exit_px),
            reason=reason,
            gross=float(gross),
            costs=float(costs),
            gap_through=bool(ex and ex.gap_through),
            collision=bool(ex and ex.collision),
        )
        return trade, j


def run(
    bars: pd.DataFrame,
    entries: Iterable[Entry],
    fills: FillModel | None = None,
    costs: CostModel | None = None,
    qty: float = 1,
    fine: pd.DataFrame | None = None,
) -> list[Trade]:
    return Backtest(bars, fills, costs, qty, fine).run(entries)


def trades_frame(trades: list[Trade]) -> pd.DataFrame:
    rows = [{**t.__dict__, "net": t.net} for t in trades]
    return pd.DataFrame(rows)
