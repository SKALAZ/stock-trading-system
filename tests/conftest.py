import numpy as np
import pandas as pd
import pytest

from trader.config import load_config


@pytest.fixture
def cfg():
    return load_config()


def make_prices(n=400, drift=0.0, seed=0, start="2020-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n, name="date")
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.02, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    vol = rng.integers(1_000, 2_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.01,
                         "low": np.minimum(open_, close) * 0.99, "close": close, "volume": vol}, index=idx)


@pytest.fixture
def prices():
    return make_prices
