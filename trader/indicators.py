"""기술지표. 라이브러리 대신 pandas로 직접 계산해서 계산 과정을 설명할 수 있게 한다.

원칙 조건식에 쓸 수 있는 이름:
  smaN        N일 단순 이동평균 (종가)
  rsiN        N일 RSI (Wilder 방식)
  vol_ratioN  오늘 거래량 / 어제까지 N일 평균 거래량
  retN        N일 수익률 (종가 기준)
"""
import re

import pandas as pd

TOKEN = re.compile(r"\b(sma|rsi|vol_ratio|ret)(\d+)\b")


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder 평활 = 알파 1/n 지수이동평균
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    out = 100 - 100 / (1 + avg_gain / avg_loss)
    return out.where(avg_loss > 0, 100.0).where(avg_gain.notna())


def vol_ratio(volume: pd.Series, n: int) -> pd.Series:
    return volume / volume.shift(1).rolling(n, min_periods=n).mean()


def ret(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1


def tokens(expressions: list[str]) -> set[tuple[str, int]]:
    """조건식들에서 필요한 지표 이름을 뽑는다. 예: 'rsi14 < 30' → {('rsi', 14)}"""
    return {(kind, int(n)) for e in expressions for kind, n in TOKEN.findall(e)}


def add_indicators(df: pd.DataFrame, expressions: list[str]) -> pd.DataFrame:
    """조건식에 나오는 지표 열을 붙인 복사본을 돌려준다."""
    df = df.copy()
    for kind, n in sorted(tokens(expressions)):
        name = f"{kind}{n}"
        if kind == "sma":
            df[name] = sma(df["close"], n)
        elif kind == "rsi":
            df[name] = rsi(df["close"], n)
        elif kind == "vol_ratio":
            df[name] = vol_ratio(df["volume"], n)
        elif kind == "ret":
            df[name] = ret(df["close"], n)
    return df
