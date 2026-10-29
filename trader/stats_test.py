"""① 원칙 검정 (이벤트 스터디).

신호일 t 종가로 조건 판정 → t+1 시가에 매수 → t+h 종가에 매도.
초과수익 = 종목 수익률 − 같은 기간 코스피 수익률 − 왕복 거래비용.

H0: 평균 초과수익 ≤ 0,  H1: 평균 초과수익 > 0 (단측)
- 주 검정: 날짜 블록 부트스트랩. 같은 날 여러 종목에서 신호가 나면 서로 독립이 아니므로
  날짜 단위로 묶어서 재표본추출한다.
- 무작위 진입 기준선: 같은 종목·같은 구간에서 아무 날이나 샀을 때보다 나은가.
"""
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from trader.config import ROOT, round_trip_cost
from trader.indicators import add_indicators
from trader.principles import Principle

REPORT_DIR = ROOT / "reports"


def forward_excess(df: pd.DataFrame, bench: pd.DataFrame, h: int, cost: float) -> pd.Series:
    """모든 날 t에 대해 't+1 시가 매수 → t+h 종가 매도'의 비용 차감 초과수익."""
    ret = df["close"].shift(-h) / df["open"].shift(-1) - 1
    b = bench.reindex(df.index)
    bret = b["close"].shift(-h) / b["open"].shift(-1) - 1
    return ret - bret - cost


def find_events(stocks: dict, bench: pd.DataFrame, p: Principle, cost: float) -> tuple[pd.DataFrame, dict]:
    """원칙 신호 이벤트 목록과, 무작위 기준선용 '종목별 전체 날짜 초과수익'을 돌려준다.

    한 종목에서 신호가 연달아 나면 보유 기간(h일) 동안은 다시 사지 않는다 (운영과 동일).
    """
    rows, all_days = [], {}
    for ticker, raw in stocks.items():
        df = add_indicators(raw, [p.entry])
        fwd = forward_excess(df, bench, p.horizon_days, cost)
        all_days[ticker] = fwd.dropna()
        hit = np.flatnonzero((p.signal(df) & fwd.notna()).to_numpy())
        last = -10**9
        for i in hit:
            if i - last >= p.horizon_days:
                rows.append((df.index[i], ticker, fwd.iloc[i]))
                last = i
    events = pd.DataFrame(rows, columns=["date", "ticker", "excess"]).sort_values("date", ignore_index=True)
    events["date"] = pd.to_datetime(events["date"])
    return events, all_days


def block_bootstrap(events: pd.DataFrame, trials: int, rng) -> tuple[float, float, float, float]:
    """평균, 95% 신뢰구간, 단측 p값."""
    g = events.groupby("date")["excess"].agg(["sum", "count"])
    sums, counts = g["sum"].to_numpy(), g["count"].to_numpy()
    obs = sums.sum() / counts.sum()
    idx = rng.integers(0, len(g), size=(trials, len(g)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    # 분포를 0 중심으로 옮겼을 때(H0) 관측값 이상이 나올 확률
    p = float(((means - obs) >= obs).mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(obs), float(lo), float(hi), p


def random_entry_percentile(events: pd.DataFrame, all_days: dict, trials: int, rng) -> tuple[float, np.ndarray]:
    """원칙 성과가 '같은 종목·같은 구간 무작위 진입' 분포에서 몇 분위인가."""
    lo, hi = events["date"].min(), events["date"].max()
    total = np.zeros(trials)
    for ticker, k in events["ticker"].value_counts().items():
        pool = all_days[ticker]
        pool = pool[(pool.index >= lo) & (pool.index <= hi)].to_numpy()
        total += rng.choice(pool, size=(trials, k)).sum(axis=1)
    rand_means = total / len(events)
    return float((rand_means < events["excess"].mean()).mean()), rand_means


@dataclass
class PrincipleTestResult:
    principle: Principle
    events: pd.DataFrame
    n: int = 0
    mean: float = float("nan")
    ci: tuple = (float("nan"), float("nan"))
    p: float = 1.0
    random_pct: float = 0.0
    v_n: int = 0
    v_mean: float = float("nan")
    v_p: float = 1.0
    passed: bool = False
    reasons: list = field(default_factory=list)


def run_test(cfg: dict, stocks: dict, bench: pd.DataFrame, p: Principle) -> PrincipleTestResult:
    t = cfg["test"]
    rng = np.random.default_rng(t["seed"])
    events, all_days = find_events(stocks, bench, p, round_trip_cost(cfg))
    split = pd.Timestamp(t["validate_start"])
    ins, val = events[events["date"] < split], events[events["date"] >= split]

    r = PrincipleTestResult(p, events, n=len(ins), v_n=len(val))
    if len(ins) >= 2:
        r.mean, lo, hi, r.p = block_bootstrap(ins, t["bootstrap_trials"], rng)
        r.ci = (lo, hi)
        r.random_pct, _ = random_entry_percentile(ins, all_days, t["random_trials"], rng)
    if len(val) >= 2:
        r.v_mean, _, _, r.v_p = block_bootstrap(val, t["bootstrap_trials"], rng)

    checks = [
        (r.n >= t["min_events"], f"검정 구간 이벤트 수 {r.n} ≥ {t['min_events']}"),
        (r.mean > 0, f"평균 초과수익 {r.mean:+.4f} > 0"),
        (r.ci[0] > 0, f"95% 신뢰구간 하한 {r.ci[0]:+.4f} > 0"),
        (r.p < t["alpha"], f"p값 {r.p:.4f} < {t['alpha']}"),
        (r.random_pct >= t["random_percentile"], f"무작위 진입 대비 {r.random_pct:.1%} ≥ {t['random_percentile']:.0%}"),
        (r.v_mean > 0 and r.v_p < t["alpha_validate"],
         f"검증 구간 같은 방향 (평균 {r.v_mean:+.4f}, p {r.v_p:.4f} < {t['alpha_validate']})"),
    ]
    r.reasons = [("✅ " if ok else "❌ ") + msg for ok, msg in checks]
    r.passed = all(ok for ok, _ in checks)
    return r


def write_report(cfg: dict, r: PrincipleTestResult, trial_no: int) -> str:
    """검정 리포트(마크다운)를 reports/에 저장하고 경로를 돌려준다."""
    REPORT_DIR.mkdir(exist_ok=True)
    p, ev = r.principle, r.events
    names = cfg["market"]["universe"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"{p.id}_{stamp}.md"

    yearly = ev.assign(year=ev["date"].dt.year).groupby("year")["excess"].agg(["count", "mean"])
    by_stock = ev.groupby("ticker")["excess"].agg(["count", "mean"]).sort_values("count", ascending=False)
    win = (ev["excess"] > 0).mean() if len(ev) else float("nan")
    gains, losses = ev.loc[ev["excess"] > 0, "excess"], ev.loc[ev["excess"] <= 0, "excess"]
    payoff = gains.mean() / -losses.mean() if len(gains) and len(losses) else float("nan")

    lines = [
        f"# {p.id} {p.name} — {'통과 (passed)' if r.passed else '탈락 (rejected)'}",
        "",
        f"- 가설: {p.hypothesis.strip()}",
        f"- 진입 조건: `{p.entry}` / 보유 {p.horizon_days}거래일 / 왕복 비용 {round_trip_cost(cfg):.4%}",
        f"- 이 원칙의 {trial_no}번째 검정 (여러 번 고쳐서 시험할수록 우연히 통과할 확률이 커진다)",
        f"- 검정 구간: ~ {cfg['test']['validate_start']} 전 / 검증 구간: {cfg['test']['validate_start']} ~",
        "",
        "## 판정",
        *[f"- {x}" for x in r.reasons],
        "",
        "## 요약",
        "| 구간 | 이벤트 | 평균 초과수익 | 95% CI | p (단측) |",
        "|---|---|---|---|---|",
        f"| 검정 | {r.n} | {r.mean:+.4%} | [{r.ci[0]:+.4%}, {r.ci[1]:+.4%}] | {r.p:.4f} |",
        f"| 검증 | {r.v_n} | {r.v_mean:+.4%} | — | {r.v_p:.4f} |",
        "",
        f"- 전체 승률 {win:.1%}, 손익비 {payoff:.2f}, 중앙값 {ev['excess'].median():+.4%}",
        f"- 무작위 진입 기준선 대비 분위: {r.random_pct:.1%}",
        "",
        "## 연도별",
        "| 연도 | 이벤트 | 평균 초과수익 |",
        "|---|---|---|",
        *[f"| {y} | {int(row['count'])} | {row['mean']:+.4%} |" for y, row in yearly.iterrows()],
        "",
        "## 종목별 (이벤트 많은 순 상위 10)",
        "| 종목 | 이벤트 | 평균 초과수익 |",
        "|---|---|---|",
        *[f"| {names.get(t, t)} | {int(row['count'])} | {row['mean']:+.4%} |" for t, row in by_stock.head(10).iterrows()],
        "",
        "## 데이터 한계",
        "- 유니버스가 '현재' 대형주라 생존편향이 있다 (과거에 대형주였다가 빠진 종목이 없음).",
        "- yfinance 수정주가 기준. 거래정지일은 제외, 보간하지 않음.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path.relative_to(ROOT))
