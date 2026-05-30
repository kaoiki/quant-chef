"""
技术指标计算模块
基于 pandas 和 numpy 实现常用技术指标
"""

import pandas as pd
import numpy as np


def sma(data: pd.Series, period: int = 20) -> pd.Series:
    """简单移动平均线"""
    return data.rolling(window=period).mean()


def ema(data: pd.Series, period: int = 20) -> pd.Series:
    """指数移动平均线"""
    return data.ewm(span=period, adjust=False).mean()


def rsi(data: pd.Series, period: int = 14) -> pd.Series:
    """相对强弱指标 (RSI)"""
    delta = data.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(data: pd.Series) -> pd.DataFrame:
    """MACD 指标"""
    ema12 = ema(data, 12)
    ema26 = ema(data, 26)
    dif = ema12 - ema26
    dea = ema(dif, 9)
    macd_bar = 2 * (dif - dea)
    return pd.DataFrame({"DIF": dif, "DEA": dea, "MACD": macd_bar})
