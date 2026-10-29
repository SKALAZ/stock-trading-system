import numpy as np
import pandas as pd

from trader.principles import Principle
from trader.stats_test import block_bootstrap, forward_excess, run_test


def test_forward_excess_enters_next_open_exits_close_h_days_later(prices):
    df = prices(10)
    bench = df.copy()
    bench[["open", "close"]] = 1.0  # 벤치마크 수익률 0
    fwd = forward_excess(df, bench, h=3, cost=0.0)
    expected = df["close"].iloc[3] / df["open"].iloc[1] - 1
    assert np.isclose(fwd.iloc[0], expected)
    assert fwd.iloc[-3:].isna().all()  # 미래가 없는 날은 계산하지 않는다


def test_bootstrap_detects_positive_mean_and_not_zero_mean():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2020-01-01", periods=300)
    pos = pd.DataFrame({"date": dates, "excess": rng.normal(0.01, 0.02, 300)})
    zero = pd.DataFrame({"date": dates, "excess": rng.normal(0.0, 0.02, 300)})
    m, lo, hi, p = block_bootstrap(pos, 2000, np.random.default_rng(0))
    assert m > 0 and lo > 0 and p < 0.01
    assert block_bootstrap(zero, 2000, np.random.default_rng(0))[3] > 0.05


def test_rule_that_fires_rarely_is_rejected(cfg, prices):
    stocks = {f"S{i}": prices(600, seed=i) for i in range(3)}
    bench = prices(600, seed=99)
    p = Principle("T", "test", "h", "rsi14 < 1", 5, 0.05)
    r = run_test(cfg, stocks, bench, p)
    assert not r.passed and r.n < cfg["test"]["min_events"]
