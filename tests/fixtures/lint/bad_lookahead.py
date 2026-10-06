import pandas as pd


def label_and_trade(df: pd.DataFrame, commission: float = 1.0) -> float:
    df = df.copy()
    df["next_close"] = df["close"].shift(-1)
    df["signal"] = df["next_close"] > df["close"]
    df["ret"] = df["signal"] * (df["close"].shift(periods=-1) - df["close"])
    return df["ret"].sum() - commission * df["signal"].sum()
