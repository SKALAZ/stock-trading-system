"""실행(run) 하나의 성과·통제 지표. CLI(compare)와 모니터링 API가 같은 함수를 쓴다.

db: sqlite3 연결 (row_factory=sqlite3.Row). 읽기만 한다.
"""
from __future__ import annotations

import sqlite3

import pandas as pd


def equity_frame(db: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    eq = pd.read_sql("SELECT date, equity, cash, n_positions, max_weight FROM daily_equity WHERE run_id=? ORDER BY date",
                     db, params=(run_id,), parse_dates=["date"])
    return eq.set_index("date")


def extreme_orders(db: sqlite3.Connection, run_id: int, max_position_weight: float) -> int:
    """극단적 주문 = 목표 비중이 종목 상한을 넘거나, 인용한 원칙 조건이 실제로는 미충족인데 체결된 매수"""
    return db.execute(
        """SELECT COUNT(*) FROM orders o WHERE o.run_id=? AND o.side='BUY' AND o.status='FILLED'
           AND (o.final_weight > ? + 1e-9 OR EXISTS (SELECT 1 FROM guardrail_checks c
                WHERE c.decision_id=o.decision_id AND c.item=o.item AND c.rule='G03' AND c.verdict='REJECT'))""",
        (run_id, max_position_weight)).fetchone()[0]


def rule_counts(db: sqlite3.Connection, run_id: int, verdicts=("CLIP", "REJECT")) -> list[dict]:
    marks = ",".join("?" for _ in verdicts)
    rows = db.execute(
        f"""SELECT c.rule, c.verdict, COUNT(*) n FROM guardrail_checks c JOIN decisions d USING (decision_id)
            WHERE d.run_id=? AND c.verdict IN ({marks}) GROUP BY c.rule, c.verdict ORDER BY c.rule""",
        (run_id, *verdicts)).fetchall()
    return [dict(r) for r in rows]


def run_metrics(db: sqlite3.Connection, run_id: int, max_position_weight: float,
                bench: pd.DataFrame | None = None) -> dict:
    eq = equity_frame(db, run_id)
    s = eq["equity"]
    one = lambda sql: db.execute(sql, (run_id,)).fetchone()[0]  # noqa: E731
    m = {
        "label": one("SELECT label FROM runs WHERE run_id=?"),
        "start": s.index[0].strftime("%Y-%m-%d"),
        "end": s.index[-1].strftime("%Y-%m-%d"),
        "return": float(s.iloc[-1] / s.iloc[0] - 1),
        "mdd": float((s / s.cummax() - 1).min()),
        "max_weight": float(eq["max_weight"].max()),
        "decisions": one("SELECT COUNT(*) FROM decisions WHERE run_id=?"),
        "orders": one("SELECT COUNT(*) FROM orders WHERE run_id=? AND status='FILLED'"),
        "forced": one("SELECT COUNT(*) FROM orders WHERE run_id=? AND source='F01' AND status='FILLED'"),
        "extreme": extreme_orders(db, run_id, max_position_weight),
        "rules": {r["rule"] + " " + r["verdict"]: r["n"] for r in rule_counts(db, run_id)},
    }
    if bench is not None and not bench.empty:
        b = bench_on(bench, s.index)
        r = b.iloc[-1] / b.iloc[0] - 1
        m["bench"] = None if pd.isna(r) else float(r)
    return m


def bench_on(bench: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """지수 종가를 주어진 날짜에 맞춘다. 지수 일봉이 아직 안 올라온 날은 직전 값으로 채운다."""
    return bench["close"].reindex(bench.index.union(index)).ffill().reindex(index)
