"""시세 수집: yfinance 일봉(수정주가)을 받아 data/에 CSV로 캐시한다."""
import warnings
from datetime import date

import pandas as pd

from trader.config import ROOT

DATA_DIR = ROOT / "data"
COLUMNS = ["open", "high", "low", "close", "volume"]


def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df[COLUMNS].dropna()


def load_ticker(ticker: str, start: str, refresh: bool = False, is_index: bool = False) -> pd.DataFrame:
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"{ticker.replace('^', 'IDX_')}.csv"
    if path.exists() and not refresh:
        df = pd.read_csv(path, index_col="date", parse_dates=True)
    else:
        df = _download(ticker, start, date.today().isoformat())
        if df.empty:
            raise RuntimeError(f"{ticker} 시세를 받지 못했습니다")
        df.to_csv(path)
    if not is_index:
        df = df[df["volume"] > 0]  # 거래정지일은 이벤트에서 제외한다 (보간하지 않음)
    return df


def load_market(cfg: dict, refresh: bool = False) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """유니버스 종목별 일봉과 벤치마크 일봉을 돌려준다."""
    m = cfg["market"]
    stocks = {t: load_ticker(t, m["data_start"], refresh) for t in m["universe"]}
    bench = load_ticker(m["benchmark"], m["data_start"], refresh, is_index=True)
    return stocks, bench
