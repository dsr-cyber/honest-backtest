import numpy as np
import pandas as pd


def sma_cross(df: pd.DataFrame, fast: int = 10, slow: int = 30) -> pd.Series:
    df = df.copy()
    df["fast"] = df["close"].rolling(fast).mean()
    df["slow"] = df["close"].rolling(slow).mean()
    df["position"] = np.where(df["fast"] > df["slow"], 1, -1)
    df["pnl"] = df["position"].shift(1) * df["close"].diff()
    equity = df["pnl"].cumsum()
    return equity
