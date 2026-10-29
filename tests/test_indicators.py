import numpy as np
import pandas as pd

from trader.indicators import add_indicators, rsi, sma, tokens, vol_ratio


def test_sma():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert np.isnan(sma(s, 3).iloc[1])


def test_rsi_only_up_is_100_only_down_is_0():
    up = pd.Series(np.arange(1, 40, dtype=float))
    down = up[::-1].reset_index(drop=True)
    assert rsi(up, 14).iloc[-1] == 100
    assert rsi(down, 14).iloc[-1] == 0


def test_rsi_wilder_reference():
    # 같은 크기로 오르내리면 RSI는 50 근처
    s = pd.Series([10, 11] * 30, dtype=float)
    assert 45 < rsi(s, 14).iloc[-1] < 55


def test_vol_ratio_uses_previous_days_only():
    v = pd.Series([10.0] * 20 + [30.0])
    assert vol_ratio(v, 20).iloc[-1] == 3.0


def test_tokens_and_add_indicators(prices):
    assert tokens(["close > sma60 and rsi14 < 30"]) == {("sma", 60), ("rsi", 14)}
    df = add_indicators(prices(100), ["sma20 > sma60 and vol_ratio20 >= 2 and ret1 > 0"])
    assert {"sma20", "sma60", "vol_ratio20", "ret1"} <= set(df.columns)
