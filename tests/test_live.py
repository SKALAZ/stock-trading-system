"""실거래 루프를 가짜 토스 클라이언트로 끝까지 돌려 본다 (실제 주문 없음)."""
from datetime import datetime

import pandas as pd
import pytest

from trader import live
from trader.agent.llm import MockLLM
from trader.agent.loop import run_agent
from trader.broker import LiveBroker
from trader.journal import Journal
from trader.principles import Principle

P = Principle("P-1", "t", "h", "rsi14 < 45", 3, 0.05)


class FakeToss:
    """토스 API 흉내: 시장가 주문은 마지막 가격에 즉시 전량 체결, 수수료 0.015%."""

    def __init__(self, cash, prices):
        self.cash, self.px, self.hold, self.orders, self.sent = cash, prices, {}, {}, []

    def holdings(self, account):
        return {"items": [{"symbol": s, "quantity": str(q), "marketCountry": "KR"} for s, q in self.hold.items()]}

    def buying_power(self, account, currency="KRW"):
        return {"cashBuyingPower": str(int(self.cash))}

    def prices(self, symbols):
        return [{"symbol": s, "lastPrice": str(self.px[s]), "currency": "KRW"} for s in symbols]

    def _create_order(self, account, body):
        self.sent.append(body)
        s, q, px = body["symbol"], int(body["quantity"]), self.px[body["symbol"]]
        fee = px * q * 0.00015
        if body["side"] == "BUY":
            self.cash -= px * q + fee
            self.hold[s] = self.hold.get(s, 0) + q
        else:
            self.cash += px * q - fee
            self.hold[s] -= q
        oid = f"T{len(self.orders) + 1}"
        self.orders[oid] = {"status": "FILLED", "execution": {"filledQuantity": str(q), "averageFilledPrice": str(px),
                                                                "commission": str(fee), "tax": "0", "filledAt": "2024-01-03T09:01:00+09:00"}}
        return {"orderId": oid}

    def order(self, account, oid):
        return self.orders[oid]


@pytest.fixture
def setup(cfg, prices, tmp_path, monkeypatch):
    monkeypatch.setattr(live, "STATE", tmp_path / "live.json")
    monkeypatch.setattr(live, "STOP", tmp_path / "STOP")
    stocks = {f"S{i}.KS": prices(300, seed=i) for i in range(4)}
    bench = prices(300, seed=99)
    journal = Journal(tmp_path / "j.db")
    # 판단할 날: 후보(rsi14 < 45)가 있는 날을 고른다
    from trader.indicators import add_indicators
    days = [d for d in bench.index[150:280]
            if any(P.signal(add_indicators(df, [P.entry])).get(d, False) for df in stocks.values())]
    d0 = days[0]
    pxs = {t.split(".")[0]: float(df["close"].loc[:d0].iloc[-1]) for t, df in stocks.items()}
    client = FakeToss(cash=5_000_000, prices=pxs)
    return cfg, journal, client, stocks, bench, d0


def at(monkeypatch, d, hh):
    monkeypatch.setattr(live, "now_kst", lambda: datetime(d.year, d.month, d.day, hh, 0, tzinfo=live.KST))


def decide(cfg, journal, client, stocks, bench, d, **kw):
    # 실제로는 그날까지의 데이터만 있다
    return live.decide(cfg, journal, client, 1, {t: df.loc[:d] for t, df in stocks.items()}, bench.loc[:d],
                       {"P-1": P}, {"P-1": 1},
                       lambda c: run_agent(c, MockLLM()), "mock", **kw)


def test_full_cycle(setup, monkeypatch):
    cfg, journal, client, stocks, bench, d0 = setup
    capital = cfg["execution"]["live_capital"]

    at(monkeypatch, d0, 16)
    r = decide(cfg, journal, client, stocks, bench, d0, dry_run=False)
    assert r["pending"], "후보가 있는 날이면 매수 대기 주문이 생겨야 한다"
    assert r["cash"] == capital  # 계좌에 500만 원이 있어도 Agent는 한도(live_capital)까지만 쓴다
    # 가드레일: mock 은 30%를 원했지만 1회 5%로 잘려야 한다
    first = journal.query("SELECT requested_weight, final_weight FROM orders WHERE order_id=?", r["pending"][0]["order_id"])[0]
    assert first["requested_weight"] == 0.30 and first["final_weight"] == pytest.approx(0.05)
    # 같은 날 다시 판단하면 건너뛴다
    assert "skipped" in decide(cfg, journal, client, stocks, bench, d0, dry_run=False)

    d1 = bench.index[bench.index.get_loc(d0) + 1]
    at(monkeypatch, d1, 10)
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "yes")
    msgs = live.execute(cfg, journal, client, LiveBroker(client, 1), 1)
    assert any("FILLED" in m for m in msgs)
    assert all(b["orderType"] == "MARKET" and b["clientOrderId"].startswith("live-") for b in client.sent)
    assert live.load_state()["pending"] == []

    pos, cash = live.ledger(journal, r["run_id"], capital)
    assert pos and cash < capital
    spent = sum(p["cost"] for p in pos.values())
    assert cash == pytest.approx(capital - spent)

    # 다음 날 장 마감 판단: 장부 포지션이 보유 1일로 이어진다
    at(monkeypatch, d1, 16)
    stocks1 = stocks
    r2 = decide(cfg, journal, client, stocks1, bench, d1, dry_run=False)
    assert all(p.held_days == 1 for p in r2["positions"].values())


def test_stop_file_blocks_orders(setup, monkeypatch):
    cfg, journal, client, stocks, bench, d0 = setup
    at(monkeypatch, d0, 16)
    decide(cfg, journal, client, stocks, bench, d0, dry_run=False)
    live.STOP.write_text("stop")
    d1 = bench.index[bench.index.get_loc(d0) + 1]
    at(monkeypatch, d1, 10)
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "yes")
    with pytest.raises(RuntimeError, match="STOP"):
        live.execute(cfg, journal, client, LiveBroker(client, 1), 1)
    assert client.sent == []


def test_execute_outside_market_hours_refuses(setup, monkeypatch):
    cfg, journal, client, stocks, bench, d0 = setup
    at(monkeypatch, d0, 16)
    decide(cfg, journal, client, stocks, bench, d0, dry_run=False)
    at(monkeypatch, d0, 18)  # 같은 날 저녁
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "yes")
    with pytest.raises(RuntimeError):
        live.execute(cfg, journal, client, LiveBroker(client, 1), 1)
    assert client.sent == []


def test_dry_run_leaves_no_queue(setup, monkeypatch):
    cfg, journal, client, stocks, bench, d0 = setup
    at(monkeypatch, d0, 16)
    r = decide(cfg, journal, client, stocks, bench, d0, dry_run=True)
    assert r["pending"] and live.load_state().get("pending", []) == []
    statuses = {x["status"] for x in journal.query("SELECT status FROM orders WHERE run_id=?", r["run_id"])}
    assert statuses == {"DRY"}


def test_no_money_refuses(setup, monkeypatch):
    cfg, journal, client, stocks, bench, d0 = setup
    client.cash = 8
    at(monkeypatch, d0, 16)
    with pytest.raises(RuntimeError, match="운용 가능한 돈"):
        decide(cfg, journal, client, stocks, bench, d0, dry_run=False)


def kst(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=live.KST)


def test_next_action_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "STOP", tmp_path / "STOP")
    wed_morning, wed_close, sat = kst(2026, 10, 28, 10), kst(2026, 10, 28, 15, 50), kst(2026, 10, 31, 10)
    queued = {"pending": [{"order_id": 1}], "decided_for": "2026-10-27"}
    assert live.next_action(wed_morning, queued, False, None) == "execute"
    assert live.next_action(sat, queued, False, None) is None                       # 주말엔 주문 안 함
    assert live.next_action(wed_morning, {**queued, "decided_for": "2026-10-28"}, False, None) is None  # 판단한 날엔 실행 안 함
    assert live.next_action(wed_morning, {"pending": []}, True, None) == "decide"  # 시작하자마자 한 번 판단
    assert live.next_action(wed_morning, {"pending": []}, False, None) is None
    assert live.next_action(wed_close, {"pending": [], "decided_for": "2026-10-27"}, False, None) == "decide"
    assert live.next_action(wed_close, {"pending": [], "decided_for": "2026-10-28"}, False, None) is None
    assert live.next_action(wed_close, {"pending": []}, False, kst(2026, 10, 28, 15, 45)) is None  # 10분 안엔 재시도 안 함
    (tmp_path / "STOP").write_text("x")
    assert live.next_action(wed_morning, queued, False, None) is None


def test_auto_keeps_running_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "STOP", tmp_path / "STOP")
    monkeypatch.setattr(live, "STATE", tmp_path / "live.json")
    calls, logs = [], []

    def bad_decide():
        calls.append("decide")
        raise RuntimeError("일시 오류")

    clock = iter([kst(2026, 10, 28, 15, 50), kst(2026, 10, 28, 15, 51), kst(2026, 10, 28, 16, 1)])
    live.auto(bad_decide, lambda: calls.append("execute"), log=logs.append, sleep=lambda s: None,
              now=lambda: next(clock), max_loops=3)
    assert calls == ["decide", "decide"]                 # 시작 시 1번, 10분 뒤 1번 (15:51엔 쉼)
    assert any("실패" in m for m in logs)
