"""Transaction costs per order.

Every model answers one question: what does this order cost, given its side
(+1 buy, -1 sell), fill price and quantity. Slippage is charged here as a
cost rather than by moving the fill price, so gross P&L stays a pure price
difference and the report can show the two separately.

The regulatory numbers below are the ones I last checked, with the date. They
change, sometimes several times a year. Verify them against the source before
you rely on any result that is close to break-even.
"""

from __future__ import annotations

from dataclasses import dataclass

BUY = 1
SELL = -1


@dataclass(frozen=True)
class NoCosts:
    def order(self, side: int, price: float, qty: float) -> float:
        return 0.0


@dataclass(frozen=True)
class SimpleCosts:
    commission_per_order: float = 0.0
    slippage_per_unit: float = 0.0
    pct_on_buy: float = 0.0
    pct_on_sell: float = 0.0

    def order(self, side: int, price: float, qty: float) -> float:
        notional = abs(price * qty)
        pct = self.pct_on_buy if side == BUY else self.pct_on_sell
        return self.commission_per_order + self.slippage_per_unit * abs(qty) + pct * notional


@dataclass(frozen=True)
class USEquityCosts:
    """Zero-commission US stock broker.

    SEC Section 31 fee: $27.80 per $1M of sales, the rate in force from
    2024-05-22. The SEC resets it at least once a fiscal year; current rate
    is on sec.gov ("Section 31 fee rate").
    FINRA TAF: $0.000166 per share sold, capped at $8.30 per trade, the 2024
    schedule. Check finra.org before relying on it.
    Slippage default is one cent a share each way, which is generous for a
    liquid large cap and too small for anything thin.
    """

    commission_per_order: float = 0.0
    slippage_per_unit: float = 0.01
    sec_fee_per_million: float = 27.80
    finra_taf_per_share: float = 0.000166
    finra_taf_cap: float = 8.30

    def order(self, side: int, price: float, qty: float) -> float:
        qty = abs(qty)
        cost = self.commission_per_order + self.slippage_per_unit * qty
        if side == SELL:
            cost += abs(price) * qty * self.sec_fee_per_million / 1_000_000
            cost += min(qty * self.finra_taf_per_share, self.finra_taf_cap)
        return cost


@dataclass(frozen=True)
class IndiaIndexOptionCosts:
    """Buying NSE index options through a flat-fee discount broker, in rupees.

    Rates as I last checked them, 2026-10:
      STT 0.15 % of premium on the sell side (raised from 0.1 % with effect
      from 2026-04-01 -- confirm against the current Finance Act / NSE notice)
      NSE transaction charge 0.03503 % of premium (rate from 2024-10-01)
      SEBI turnover fee Rs 10 per crore = 0.0001 %
      Stamp duty 0.003 % of premium on the buy side
      GST 18 % on brokerage + transaction charge + SEBI fee
    BSE options carry a different transaction charge. Brokerage of Rs 20 per
    executed order is the common discount-broker figure; set it to 0 for a
    zero-brokerage plan.
    Slippage is in premium points per unit.
    """

    brokerage_per_order: float = 20.0
    slippage_per_unit: float = 0.5
    stt_on_sell: float = 0.0015
    exchange_txn: float = 0.0003503
    sebi_fee: float = 0.000001
    stamp_on_buy: float = 0.00003
    gst: float = 0.18

    def order(self, side: int, price: float, qty: float) -> float:
        qty = abs(qty)
        premium = abs(price) * qty
        exchange = premium * self.exchange_txn
        sebi = premium * self.sebi_fee
        cost = self.brokerage_per_order + exchange + sebi
        cost += self.gst * (self.brokerage_per_order + exchange + sebi)
        if side == SELL:
            cost += premium * self.stt_on_sell
        else:
            cost += premium * self.stamp_on_buy
        return cost + self.slippage_per_unit * qty


PRESETS = {
    "none": NoCosts(),
    "us-equity": USEquityCosts(),
    "india-options": IndiaIndexOptionCosts(),
}
