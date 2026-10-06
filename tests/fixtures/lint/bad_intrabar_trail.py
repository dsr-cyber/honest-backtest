def run(df, atr_mult, atr, slippage=0.02):
    trades = []
    trail = None
    entry = None
    for _, bar in df.iterrows():
        if entry is None:
            if bar["signal"]:
                entry = bar["open"]
                trail = entry - atr_mult * atr
            continue
        trail = max(trail, bar["high"] - atr_mult * atr)
        if bar["low"] <= trail:
            exit_price = min(trail, bar["open"])
            trades.append(exit_price - entry - 2 * slippage)
            entry = None
    return trades
