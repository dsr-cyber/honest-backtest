# honest-backtest

A small bar-by-bar backtester that fills stops the way a market does, and a
linter that looks for the places where other backtests don't.

## Why this exists

I found this the expensive way. I had six intraday option-buying strategies
whose backtests said they made money. Then I changed one thing: stop-losses
filled at prices that actually traded, instead of at the stop level. Five of
the six turned into losers. The entries never changed. The fill model was wrong,
and every number after it inherited the mistake.

The mistakes are dull and very common:

- a bar opens below your stop and the backtest still fills you at the stop
- a bar touches both the stop and the target and the backtest picks the target
- a trailing stop gets pulled up by a bar's high and then "hit" by the same bar's low
- costs left out, or added as an afterthought

None of these show up as bugs. The code runs, the equity curve looks good.

## Quick start

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

honest-backtest compare          # naive vs honest on the bundled sample data
honest-backtest oos              # in/out-of-sample split and neighbouring parameters
honest-backtest lint your_backtest.py
pytest
```

Python 3.10 or newer. The only runtime dependencies are numpy and pandas.

## The three fill rules

1. A stop the bar opens through fills at the open. Long exit is
   `min(stop, open)`, short exit is `max(stop, open)`.
2. If the stop and the target are both inside one bar, the stop came first.
   Pass finer bars with `--fine` and the first finer bar to touch a level
   decides instead.
3. A trailing stop moves on the bar's close and applies from the next bar.
   It never moves on the high or low of the bar it is being checked against.

One bar is enough to see the first two. Long from 100.00, stop 98.00,
target 103.00:

```
bar: open 96.50  high 103.40  low 96.10  close 101.20

                 naive      honest
level hit        target     stop (the open is already below it)
fill             103.00     96.50
P&L per unit     +3.00      -3.50
```

Same bar, but opening at 100.20: now both levels are inside the bar and
nothing in it says which traded first. Naive takes the target (+3.00), honest
takes the stop at 98.00 (-2.00).

For the third: trailing 1.50 behind, a bar with open 100.40, high 104.00,
low 100.30, close 100.60. Naive moves the stop to 104.00 - 1.50 = 102.50 off
this bar's high, sees the low under it and books an exit at 102.50. Honest
moves the stop to 100.60 - 1.50 = 99.10 after the close and the trade is
still open on the next bar.

Targets fill at the target, even when a bar opens beyond it. I don't credit
the price improvement. It's small, and leaving it out errs toward
understating the result.

Costs are per order. Presets: `us-equity` (zero commission, SEC Section 31 fee
and FINRA TAF on sells, a cent a share of slippage), `india-options` (flat
brokerage, STT 0.15 % on sell premium, NSE transaction charge, SEBI fee, GST,
stamp duty, half a point of slippage per unit) and `none`. Every rate in
`src/honest_backtest/costs.py` has the date I checked it. They change, so check
them again before trusting a result near break-even.

`naive` mode does all of this the common way: fills at the stop price, target
first, trail off the intrabar high, no costs.

## Sample comparison

The data is synthetic. `data/sample_bars.csv` is 250 days of 5-minute bars
made by `honest-backtest make-data` from a fixed seed: a random walk with fat
tails, overnight gaps, a U-shaped intraday volatility profile and rare jumps
between bars. There is no edge in it on purpose, so anything the naive column
earns is the fill model talking. The strategy is a plain opening range
breakout: 15-minute range, enter on the next bar after a close outside it,
stop half the range away, target 2R, flat at the close, 100 shares.

This is a real run, pasted as printed:

```
$ honest-backtest compare
Opening range breakout on data\sample_bars.csv (synthetic), 250 days
range 3 bars, stop 0.5 x range, target 2.0R, trail none, qty 100, costs us-equity

                             naive      honest
trades                         250         250
win rate                     32.8%       32.8%
gross                       -26.00     -171.00
costs                         0.00      533.41
net                         -26.00     -704.41
profit factor                 0.99        0.78
max drawdown               -427.00     -989.53
stops through a gap              3           3
stop+target same bar             0           0

Where the difference comes from (each line adds one rule to the line above):
  naive                                     -26.00
  + stops fill at the open on a gap        -171.00     -145.00
  + stop first when both are hit           -171.00       +0.00
  + trail moves on the bar close           -171.00       +0.00
  + costs                                  -704.41     -533.41
```

The average risk per trade is about $16, so naive says -1.6R over 250 trades,
which reads as "break-even, maybe tweak it". Honest says about -43R.

Only 3 of 250 stops were gapped through, and on a liquid-stock-like series
that's about right. Naive booked each of them as exactly a 1R loss. The real
fills lost 3.0R, 3.3R and 3.2R. Those three trades are the whole $145. On
5-minute option premium bars, gaps through a stop are far more frequent than
this, which is where my five strategies went.

With these parameters the target is far enough away that no bar ever touches
both levels, so rule 2 changes nothing here. Tighten the bracket
(`--stop-frac 0.25 --target-r 1`) and 18 bars do; the stop-first rule then
costs $222 on its own.

One result surprised me. Add `--trail 0.5` and the "trail moves on the bar
close" step moves net up, by $536. Trailing off the bar's own high isn't
always optimistic: on the bars where the low came first, it stops you out of
trades that were still alive. It's wrong in a direction you can't know from
the bars, and that is the problem with it.

## Out of sample and neighbours

`honest-backtest oos` splits the days 60/40, then moves each parameter one
step either way and reruns both halves with honest fills and costs:

```
$ honest-backtest oos
data\sample_bars.csv (synthetic): in-sample 2025-01-02 to 2025-07-30, out-of-sample 2025-07-31 to 2025-12-17
honest fills, costs us-equity, qty 100

params                  IS net  IS trades     OOS net  OOS trades  OOS PF
base                   -280.24        150     -424.17         100    0.70
range_bars=2            -46.74        150      212.32         100    1.22
range_bars=4           -324.24        150     -335.67         100    0.78
stop_frac=0.4          -333.34        150     -292.47         100    0.75
stop_frac=0.6          -266.34        150     -292.47         100    0.81
target_r=1.5           -412.74        150     -440.17         100    0.67
target_r=2.5           -332.49        150     -497.42         100    0.68
```

`range_bars=2` making $212 out of sample with a profit factor of 1.22 is the
kind of row people go and trade. It's a random walk. A real edge should look
roughly the same one step away in every direction, and in both halves.

## What the linter catches

`honest-backtest lint` reads Python source with `ast` and flags:

| rule  | what it looks for |
|-------|-------------------|
| HB001 | an exit or fill price set straight from the stop, or P&L computed as stop minus entry, with no reference to the bar open |
| HB002 | the target checked before the stop on the same bar (if/elif, sibling ifs that both exit, or a "both hit" branch that takes the target) |
| HB003 | a trailing stop ratcheted from the current bar's high/low before that bar's stop check |
| HB004 | P&L computed in a file that never mentions commission, fees, slippage or costs |
| HB005 | `shift` with a negative period, which reads future rows |

On the bad fixtures in this repo:

```
$ honest-backtest lint tests/fixtures/lint/
tests/fixtures/lint/bad_gap_fill.py:16:13: HB001 exit priced at the stop without checking the bar open; a gap through the stop fills at the open
tests/fixtures/lint/bad_gap_fill.py:28:34: HB001 exit priced at the stop without checking the bar open; a gap through the stop fills at the open
tests/fixtures/lint/bad_gap_fill.py:29:9: HB001 exit priced at the stop without checking the bar open; a gap through the stop fills at the open
tests/fixtures/lint/bad_intrabar_trail.py:11:9: HB003 trailing stop moved from this bar's high/low before this bar's stop check
tests/fixtures/lint/bad_lookahead.py:6:24: HB005 shift with a negative period reads future rows
tests/fixtures/lint/bad_lookahead.py:8:33: HB005 shift with a negative period reads future rows
tests/fixtures/lint/bad_no_costs.py:10:5: HB004 P&L computed, but no commission, fee, slippage or cost appears anywhere in the file
tests/fixtures/lint/bad_target_first.py:6:12: HB002 target checked before stop on the same bar; with both inside one bar the stop may have traded first
tests/fixtures/lint/bad_target_first.py:16:12: HB002 target checked before stop on the same bar; with both inside one bar the stop may have traded first
tests/fixtures/lint/bad_target_first.py:20:13: HB001 exit priced at the stop without checking the bar open; a gap through the stop fills at the open
tests/fixtures/lint/bad_target_first.py:26:8: HB002 target checked before stop on the same bar; with both inside one bar the stop may have traded first
```

`good_backtest.py` in the same folder comes back clean. It exits 1 when it
finds something, 2 when a file won't parse. Silence a line you've checked by
hand with `# noqa: HB001`.

## Layout

```
src/honest_backtest/
  engine.py     fill model, resolve_bar() for one bar, the bar loop
  costs.py      per-order cost models and presets
  strategy.py   the opening range breakout used by compare
  data.py       CSV loading and the synthetic sample generator
  metrics.py    win rate, profit factor, drawdown
  oos.py        in/out-of-sample split, parameter neighbours
  lint.py       the linter
  cli.py
```

To run your own bars, give `compare` or `oos` a CSV with
`timestamp,open,high,low,close`, timestamps marking the start of each bar.

## Limitations

- It's a bar engine: entries fill at the next bar's open, one position at a
  time, fixed size. No partial fills, no queue position, no market impact
  beyond a flat slippage figure.
- Stop-first is the conservative answer, not the true one. Without finer data
  it will understate some strategies, which I'd rather do than the opposite.
- The linter works from names. A stop held in a variable called `x` gets
  past it, and an unusual naming scheme can produce a false alarm. It's a
  reading aid for an audit, not a proof.
- Cost constants go stale. They are dated in `costs.py`; check them.
- The sample data is a liquid-stock-like random walk. It understates gap risk
  for thin instruments.

Nothing here is financial advice; it's a tool for checking arithmetic.

If you want me to audit your backtest, open an issue with a short description
of the strategy and the data, and I'll tell you what's left of the edge.
