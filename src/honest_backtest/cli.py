from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from . import lint
from .costs import PRESETS, NoCosts
from .data import SAMPLE_SEED, load_bars, make_sample_bars, write_sample_bars
from .engine import FillModel, run
from .metrics import summarize
from .strategy import OpeningRangeBreakout

DEFAULT_DATA = Path("data/sample_bars.csv")

# Each step turns on one more rule. The order matters a little, because the
# rules interact (a trail that moves intrabar changes which bars collide).
STEPS = [
    ("naive", FillModel(False, False, False), False),
    ("+ stops fill at the open on a gap", FillModel(True, False, False), False),
    ("+ stop first when both are hit", FillModel(True, True, False), False),
    ("+ trail moves on the bar close", FillModel(True, True, True), False),
    ("+ costs", FillModel(True, True, True), True),
]


def _money(x: float) -> str:
    return f"{x:,.2f}"


def _ratio(x: float) -> str:
    return "n/a" if math.isnan(x) else "inf" if math.isinf(x) else f"{x:.2f}"


def _pct(x: float) -> str:
    return "n/a" if math.isnan(x) else f"{x:.1%}"


def _load(path: Path | None):
    if path is not None:
        return load_bars(path), str(path)
    if DEFAULT_DATA.exists():
        return load_bars(DEFAULT_DATA), f"{DEFAULT_DATA} (synthetic)"
    print(f"{DEFAULT_DATA} not found, generating the same synthetic series in memory", file=sys.stderr)
    return make_sample_bars(), "synthetic sample bars"


def _strategy(args) -> OpeningRangeBreakout:
    return OpeningRangeBreakout(
        range_bars=args.range_bars,
        stop_frac=args.stop_frac,
        target_r=args.target_r,
        trail_frac=args.trail,
    )


def _add_strategy_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data", type=Path, help="CSV with timestamp,open,high,low,close (default: bundled sample)")
    p.add_argument("--costs", choices=sorted(PRESETS), default="us-equity")
    p.add_argument("--qty", type=float, default=100)
    p.add_argument("--range-bars", type=int, default=3, help="bars in the opening range")
    p.add_argument("--stop-frac", type=float, default=0.5, help="stop distance as a fraction of the range")
    p.add_argument("--target-r", type=float, default=2.0, help="target as a multiple of the stop distance")
    p.add_argument("--trail", type=float, default=None, help="trail distance as a fraction of the range")


def cmd_compare(args) -> int:
    bars, source = _load(args.data)
    fine = load_bars(args.fine) if args.fine else None
    strat = _strategy(args)
    entries = strat.entries(bars)
    costs = PRESETS[args.costs]

    naive = summarize(run(bars, entries, FillModel.naive(), NoCosts(), args.qty, fine))
    honest = summarize(run(bars, entries, FillModel.honest(), costs, args.qty, fine))

    days = bars["timestamp"].dt.normalize().nunique()
    trail = "none" if args.trail is None else f"{args.trail} x range"
    print(f"Opening range breakout on {source}, {days} days")
    print(
        f"range {strat.range_bars} bars, stop {strat.stop_frac} x range, target {strat.target_r}R, "
        f"trail {trail}, qty {args.qty:g}, costs {args.costs}"
    )
    print()
    rows = [
        ("trades", str(naive["trades"]), str(honest["trades"])),
        ("win rate", _pct(naive["win_rate"]), _pct(honest["win_rate"])),
        ("gross", _money(naive["gross"]), _money(honest["gross"])),
        ("costs", _money(naive["costs"]), _money(honest["costs"])),
        ("net", _money(naive["net"]), _money(honest["net"])),
        ("profit factor", _ratio(naive["profit_factor"]), _ratio(honest["profit_factor"])),
        ("max drawdown", _money(naive["max_drawdown"]), _money(honest["max_drawdown"])),
        ("stops through a gap", str(naive["gap_throughs"]), str(honest["gap_throughs"])),
        ("stop+target same bar", str(naive["collisions"]), str(honest["collisions"])),
    ]
    print(f"{'':22}{'naive':>12}{'honest':>12}")
    for name, a, b in rows:
        print(f"{name:22}{a:>12}{b:>12}")

    print()
    print("Where the difference comes from (each line adds one rule to the line above):")
    prev = None
    for label, fills, with_costs in STEPS:
        s = summarize(run(bars, entries, fills, costs if with_costs else NoCosts(), args.qty, fine))
        delta = "" if prev is None else f"{s['net'] - prev:>+12,.2f}"
        print(f"  {label:36}{_money(s['net']):>12}{delta}")
        prev = s["net"]
    return 0


def cmd_lint(args) -> int:
    return lint.main(args.paths)


def cmd_make_data(args) -> int:
    bars = write_sample_bars(args.out, days=args.days, seed=args.seed)
    print(f"wrote {len(bars)} bars to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honest-backtest")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("compare", help="run the sample strategy with naive and honest fills")
    _add_strategy_args(p)
    p.add_argument("--fine", type=Path, help="finer bars used to settle stop/target collisions")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("lint", help="flag optimistic fill patterns in backtest code")
    p.add_argument("paths", nargs="+", help="python files or directories")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("make-data", help="regenerate the synthetic sample bars")
    p.add_argument("--out", type=Path, default=DEFAULT_DATA)
    p.add_argument("--days", type=int, default=250)
    p.add_argument("--seed", type=int, default=SAMPLE_SEED)
    p.set_defaults(func=cmd_make_data)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
