import pandas as pd
import pytest

from trader.agent.context import AgentContext
from trader.agent.schema import Decision
from trader.guardrails import CLIP, PASS, REJECT, DayState, check
from trader.principles import Principle

P = Principle("P-1", "t", "h", "rsi14 < 30", 5, 0.05)
G = {"max_order_weight": 0.05, "max_position_weight": 0.10, "min_cash_weight": 0.10,
     "max_orders_per_day": 10, "daily_loss_stop": -0.03, "stop_loss": -0.07}


def ctx(rsi=25.0, holdings=None, cash=0.9):
    row = pd.Series({"close": 100.0, "rsi14": rsi})
    return AgentContext(date="2024-01-02", aliases={"AAA": "STOCK_A", "BBB": "STOCK_B"},
                        principles={"P-1": P}, rows={"AAA": row, "BBB": row}, shown={},
                        candidates=[], exit_due=[], holdings=holdings or {}, cash_weight=cash, equity=1e8)


def dec(action="BUY", w=0.05, stock="STOCK_A", pid="P-1"):
    return Decision(stock=stock, action=action, target_weight=w, principle_id=pid, reason="")


def day(**kw):
    return DayState(cash_weight=kw.pop("cash", 0.9), day_return=kw.pop("ret", 0.0), **kw)


def test_normal_buy_passes():
    r = check(dec(w=0.05), ctx(), day(), G)
    assert r.verdict == PASS and r.final_weight == 0.05


def test_oversized_buy_is_clipped_to_order_limit():
    r = check(dec(w=0.40), ctx(), day(), G)
    assert r.verdict == CLIP and r.final_weight == pytest.approx(0.05)
    assert [c.rule for c in r.checks if c.verdict == CLIP] == ["G07", "G06"]


@pytest.mark.parametrize("decision,context,state,rule", [
    (dec(stock="STOCK_Z"), ctx(), day(), "G01"),
    (dec(w=1.5), ctx(), day(), "G01"),
    (dec(pid="P-999"), ctx(), day(), "G02"),
    (dec(), ctx(rsi=55.0), day(), "G03"),                    # 인용한 조건이 실제로는 미충족
    (dec(action="SELL", w=0), ctx(), day(), "G04"),          # 보유하지 않은 종목 매도
    (dec(), ctx(), day(tickers={"AAA"}), "G05"),
    (dec(), ctx(), day(orders=10), "G09"),
    (dec(), ctx(), day(ret=-0.05), "G10"),
    (dec(), ctx(holdings={"AAA": {"weight": 0.10}}), day(), "G07"),
    (dec(), ctx(cash=0.10), day(cash=0.10), "G08"),
])
def test_rejections(decision, context, state, rule):
    r = check(decision, context, state, G)
    assert r.verdict == REJECT and r.checks[-1].rule == rule


def test_sell_allowed_even_after_daily_loss():
    c = ctx(holdings={"AAA": {"weight": 0.05, "qty": 10}})
    assert check(dec(action="SELL", w=0), c, day(ret=-0.05), G).verdict == PASS


def test_cash_floor_clips():
    r = check(dec(w=0.05), ctx(cash=0.12), day(cash=0.12), G)
    assert r.verdict == CLIP and r.final_weight == pytest.approx(0.02)
