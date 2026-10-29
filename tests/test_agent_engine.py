"""API 키 없이 MockLLM으로 루프·그래프·엔진을 끝까지 돌려 본다."""
import pandas as pd

from trader.agent.context import AgentContext
from trader.agent.graph import run_agent_graph
from trader.agent.llm import MockChatModel, MockLLM
from trader.agent.loop import parse_decisions, run_agent
from trader.engine import Engine
from trader.journal import Journal
from trader.principles import Principle

P = Principle("P-1", "t", "h", "rsi14 < 45", 3, 0.05)


def sample_ctx():
    rows = {t: pd.Series({"close": 100.0, "rsi14": r}) for t, r in [("AAA", 30.0), ("BBB", 40.0)]}
    return AgentContext(date="2024-01-02", aliases={"AAA": "STOCK_A", "BBB": "STOCK_B"}, principles={"P-1": P},
                        rows=rows, shown={"STOCK_A": {"rsi14": 30.0}, "STOCK_B": {"rsi14": 40.0}},
                        candidates=[{"stock": "STOCK_A", "principles": ["P-1"]},
                                    {"stock": "STOCK_B", "principles": ["P-1"]}],
                        exit_due=[], holdings={}, cash_weight=1.0, equity=1e8)


def test_parse_keeps_invalid_items_separately():
    ok, bad = parse_decisions('{"decisions": [{"stock": "STOCK_A", "action": "BUY", "target_weight": 0.05, '
                              '"principle_id": "P-1", "reason": "r"}, {"stock": "STOCK_B", "action": "YOLO"}]}')
    assert len(ok) == 1 and len(bad) == 1
    assert parse_decisions("not json")[0] == []


def test_non_numeric_claimed_value_does_not_drop_decision():
    # 실제 GPT가 낸 응답: 근거 값 하나가 "N/A" → 예전에는 정상 매도까지 G01에서 거부됐다
    ok, bad = parse_decisions('{"decisions": [{"stock": "STOCK_T", "action": "SELL", "target_weight": 0, '
                              '"principle_id": "P-1", "conditions_claimed": [{"name": "sma20 > sma60", "value": "N/A"}], '
                              '"reason": "보유 기간 도달"}]}')
    assert len(ok) == 1 and not bad


def test_loop_and_graph_agree():
    a, _, steps = run_agent(sample_ctx(), MockLLM())
    b, _, _ = run_agent_graph(sample_ctx(), MockChatModel())
    assert [(d.stock, d.action, d.target_weight) for d in a] == [(d.stock, d.action, d.target_weight) for d in b]
    assert a[0].stock == "STOCK_A" and a[0].target_weight == 0.30   # 가장 낮은 RSI에 과대 비중
    assert any(s.get("tool") == "get_indicators" for s in steps)     # 도구를 거쳐 판단했다


def run_engine(cfg, prices, tmp_path, enforce):
    journal = Journal(tmp_path / f"j{enforce}.db")
    stocks = {f"S{i}": prices(300, seed=i) for i in range(4)}
    bench = prices(300, seed=99)
    run_id = journal.new_run("backtest", "t", {})
    eng = Engine(cfg, stocks, bench, {"P-1": P}, {"P-1": 1}, lambda c: run_agent(c, MockLLM()), "mock",
                 journal, run_id, enforce)
    for d in bench.index[100:]:
        eng.step(d)
    return journal, run_id


def test_engine_guardrails_cap_position_weight(cfg, prices, tmp_path):
    j_off, r_off = run_engine(cfg, prices, tmp_path, enforce=False)
    j_on, r_on = run_engine(cfg, prices, tmp_path, enforce=True)
    max_off = j_off.query("SELECT MAX(final_weight) FROM orders WHERE run_id=? AND side='BUY'", r_off)[0][0]
    max_on = j_on.query("SELECT MAX(final_weight) FROM orders WHERE run_id=? AND side='BUY'", r_on)[0][0]
    assert max_off > cfg["guardrails"]["max_position_weight"]
    assert max_on <= cfg["guardrails"]["max_order_weight"] + 1e-9
    # 모든 주문은 판단 기록으로 거슬러 올라갈 수 있다 (강제 손절 제외)
    orphan = j_on.query("""SELECT COUNT(*) FROM orders o LEFT JOIN decisions d USING (decision_id)
                           WHERE o.run_id=? AND o.source='AGENT' AND d.decision_id IS NULL""", r_on)[0][0]
    assert orphan == 0
    # 현금은 음수가 되지 않는다
    assert j_off.query("SELECT MIN(cash) FROM daily_equity WHERE run_id=?", r_off)[0][0] >= 0
