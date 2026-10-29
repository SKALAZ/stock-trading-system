"""
④ 실거래 루프 — 하루 두 번 (백테스트와 같은 규칙: 종가로 판단, 다음 날 시가 근처에서 체결)
──────────────────────────────────────────────────────────────
  장 마감 후      live decide    토스 계좌 동기화 → 판단(GPT) → 가드레일 → 다음 거래일 주문 대기열
  다음 날 장중    live execute   대기 주문을 토스에 시장가로 → 체결 확인 → 기록
                  live status    Agent가 관리하는 포지션·현금·대기 주문

Agent 장부(ledger) = journal.db 의 이 실행(run)의 체결 기록
  관리 현금   = live_capital + 매도 대금(수수료·세금 뺀) − 매수 대금(수수료 포함)
  관리 포지션 = Agent가 산 종목·수량만. 계좌의 다른 종목, 직접 산 주식은 건드리지 않는다
  토스 실제 값으로 한 번 더 자른다: 현금 ≤ 매수 가능 금액, 수량 ≤ 실제 보유 수량

안전장치
  - 주문은 LiveBroker 만 낸다 → ALLOW_LIVE_TRADING=yes 가 아니면 만들어지지 않는다
  - 검정을 통과한 원칙만 (--untested 는 --dry-run 에서만 허용, __main__.py)
  - 가드레일은 항상 켠다 (enforce=True). 끄는 옵션이 없다
  - state/STOP 파일이 있으면 execute 는 주문을 하나도 내지 않는다
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, time, timedelta, timezone

import pandas as pd

from trader.config import ROOT
from trader.engine import Engine, Position
from trader.toss import TossError, symbol_of

STATE = ROOT / "state" / "live.json"
STOP = ROOT / "state" / "STOP"
KST = timezone(timedelta(hours=9))
FINAL = {"FILLED", "CANCELED", "REJECTED", "REPLACED"}


def now_kst() -> datetime:
    return datetime.now(KST)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pending": [], "open": []}


def save_state(s: dict):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def broker_order_id(client_order_id: str) -> str:
    """journal 의 client_order_id 를 토스 clientOrderId 로 (영문·숫자·- 만). 같은 주문이면 항상 같은 값 → 멱등성"""
    return "live-" + re.sub(r"[^A-Za-z0-9-]", "", client_order_id)


# ──────────────────────────────────────────────────────────────
# 장부: 이 실행의 체결 기록으로 Agent의 현금·포지션을 다시 쌓는다
# ──────────────────────────────────────────────────────────────
def ledger(journal, run_id: int | None, capital: float) -> tuple[dict, float]:
    pos: dict[str, dict] = {}
    cash = float(capital)
    if run_id is None:
        return pos, cash
    rows = journal.query("""SELECT o.*, d.output FROM orders o LEFT JOIN decisions d USING (decision_id)
                            WHERE o.run_id=? AND o.fill_qty > 0 ORDER BY o.fill_date, o.order_id""", run_id)
    for r in rows:
        t, q = r["ticker"], r["fill_qty"]
        amount, fee, tax = r["fill_price"] * q, r["commission"] or 0.0, r["tax"] or 0.0
        if r["side"] == "BUY":
            cash -= amount + fee
            pid = ""
            if r["output"] and r["item"] is not None and r["item"] >= 0:
                items = json.loads(r["output"])
                pid = items[r["item"]].get("principle_id", "") if r["item"] < len(items) else ""
            p = pos.setdefault(t, {"qty": 0, "cost": 0.0, "since": r["fill_date"], "principle_id": pid})
            p["qty"] += q
            p["cost"] += amount + fee
        else:
            cash += amount - fee - tax
            p = pos.get(t)
            if p:
                p["cost"] *= max(p["qty"] - q, 0) / p["qty"]
                p["qty"] -= q
                if p["qty"] <= 0:
                    pos.pop(t)
    return pos, cash


def refresh_open(journal, client, account: int, state: dict) -> list[str]:
    """지난번에 체결 확인이 끝나지 않은 주문을 다시 조회해 기록을 맞춘다."""
    msgs, still = [], []
    for o in state.get("open", []):
        res = client.order(account, o["broker_order_id"])
        record_fill(journal, o["order_id"], res)
        msgs.append(f"  주문 #{o['order_id']} {o['ticker']} {o['side']}: {res['status']}")
        if res["status"] not in FINAL:
            still.append(o)
    state["open"] = still
    return msgs


def record_fill(journal, order_id: int, res: dict):
    ex = res.get("execution") or {}
    num = lambda v: float(v) if v not in (None, "") else None  # noqa: E731
    journal.update_order(order_id, status=res["status"],
                         fill_date=(ex.get("filledAt") or "")[:10] or None,
                         fill_price=num(ex.get("averageFilledPrice")),
                         fill_qty=int(float(ex.get("filledQuantity") or 0)),
                         commission=num(ex.get("commission")), tax=num(ex.get("tax")))


# ──────────────────────────────────────────────────────────────
# decide: 엔진 하루치를 실계좌 장부 위에서 돌린다
# ──────────────────────────────────────────────────────────────
class LiveEngine(Engine):
    """체결은 토스가 한다. 엔진은 판단·가드레일·주문 대기열까지만."""

    def _fill_pending(self, date, ds):
        return []


def decide(cfg, journal, client, account: int, stocks: dict, bench: pd.DataFrame, principles, test_ids,
           decide_fn, agent_name: str, dry_run: bool, assume_cash: bool = False) -> dict:
    state = load_state()
    msgs = refresh_open(journal, client, account, state) if not dry_run else []

    # 거래일 달력은 종목 일봉으로 만든다 (yfinance 지수 일봉은 하루 늦게 올라오는 경우가 있다)
    cal = bench.index.union(pd.DatetimeIndex(sorted({d for df in stocks.values() for d in df.index})))
    bench = bench.reindex(cal).ffill()
    # 장중에 돌리면 오늘 일봉은 아직 미완성 → 빼고 어제 종가로 판단한다
    now = now_kst()
    today = pd.Timestamp(now.date())
    if bench.index[-1] == today and now.time() < time(15, 40):
        bench = bench.iloc[:-1]
    date = bench.index[-1]
    ds = date.strftime("%Y-%m-%d")
    if not dry_run and state.get("decided_for") == ds:
        return {"skipped": f"{ds} 종가 판단은 이미 했습니다", "msgs": msgs}
    if state.get("pending") and not dry_run:
        raise RuntimeError(f"실행되지 않은 주문 {len(state['pending'])}건이 있습니다. 먼저 `live execute`")

    capital = cfg["execution"]["live_capital"]
    live_run = state.get("run_id")
    pos, cash = ledger(journal, live_run, capital)

    # 토스 실제 계좌로 한 번 더 자른다
    real = {it["symbol"]: int(float(it["quantity"])) for it in client.holdings(account)["items"]
            if it.get("marketCountry") == "KR"}
    buying_power = float(client.buying_power(account, "KRW")["cashBuyingPower"])
    cal = bench.index
    positions = {}
    for t, p in pos.items():
        q = min(p["qty"], real.get(symbol_of(t), 0))
        if q <= 0:
            msgs.append(f"  {t}: 계좌에 없음 (직접 매도한 것으로 보임) → Agent 장부에서 뺌")
            continue
        held_before = int(((cal >= pd.Timestamp(p["since"])) & (cal < date)).sum())  # step 이 오늘 하루를 더한다
        positions[t] = Position(q, p["cost"] / p["qty"], p["principle_id"], held_before)
    agent_cash = cash if (dry_run and assume_cash) else min(cash, buying_power)
    invested = sum(p.qty * float(stocks[t]["close"].loc[:date].iloc[-1]) for t, p in positions.items())
    if agent_cash + invested < cfg["execution"].get("live_min_equity", 10_000):
        raise RuntimeError(f"운용 가능한 돈이 없습니다 (매수 가능 금액 {buying_power:,.0f}원, Agent 현금 {cash:,.0f}원). "
                           f"원화를 입금하거나, 미리 보기는 --dry-run --assume-cash")

    if dry_run:
        run_id = journal.new_run("live-dry", f"live dry-run {agent_name} {ds}",
                                 {"principles": list(principles), "assume_cash": assume_cash, "agent": agent_name,
                                  "guardrails": "on", "untested": any(v is None for v in test_ids.values())})
    else:
        run_id = live_run or journal.new_run("live", f"live {agent_name}",
                                             {"principles": list(principles), "agent": agent_name, "guardrails": "on",
                                              "live_capital": capital})
    engine = LiveEngine(cfg, stocks, bench, principles, test_ids, decide_fn, agent_name, journal, run_id, enforce=True)
    engine.positions, engine.cash = positions, agent_cash
    engine.prev_equity = None if dry_run else state.get("prev_equity")
    equity = engine.step(date)

    pending = [{"order_id": o.order_id, "ticker": o.ticker, "side": o.side, "qty": o.qty,
                "principle_id": o.principle_id} for o in engine.pending]
    if dry_run:
        for o in pending:
            journal.update_order(o["order_id"], status="DRY", note="dry-run: 주문하지 않음")
    else:
        state.update(run_id=run_id, decided_for=ds, prev_equity=equity, pending=pending)
        save_state(state)
    return {"run_id": run_id, "date": ds, "equity": equity, "cash": agent_cash, "buying_power": buying_power,
            "positions": positions, "pending": pending, "msgs": msgs}


# ──────────────────────────────────────────────────────────────
# auto: 켜 두면 알아서 decide·execute 를 시간에 맞춰 부른다
#   - 대기 주문이 있고 장중(평일 09:00~15:20)이면 → execute
#   - 대기 주문이 없으면 → 시작할 때 한 번, 그리고 평일 15:45 이후 오늘 판단 전이면 → decide (10분마다 재시도)
#   - state/STOP 이 있으면 아무것도 하지 않고 기다린다
#   - 한 번 실패해도 멈추지 않는다 (기록하고 다음 차례에 다시)
# ──────────────────────────────────────────────────────────────
def market_open(n: datetime) -> bool:
    return n.weekday() < 5 and time(9, 0) <= n.time() <= time(15, 20)


def next_action(n: datetime, state: dict, first: bool, last_try: datetime | None) -> str | None:
    if STOP.exists():
        return None
    pending, decided = state.get("pending"), state.get("decided_for", "")
    if pending:
        return "execute" if market_open(n) and n.strftime("%Y-%m-%d") > decided else None
    if first:
        return "decide"
    after_close = n.weekday() < 5 and n.time() >= time(15, 45)
    if after_close and decided != n.strftime("%Y-%m-%d") and (last_try is None or n - last_try >= timedelta(minutes=10)):
        return "decide"
    return None


def auto(run_decide, run_execute, log=print, sleep=None, now=None, max_loops: int | None = None):
    import time as _t

    sleep, now = sleep or _t.sleep, now or now_kst
    first, last_try, loops, stopped = True, None, 0, False
    log("실거래 자동 실행 시작 (Ctrl+C 로 종료 · state/STOP 파일로 주문 중단)")
    while max_loops is None or loops < max_loops:
        loops += 1
        n = now()
        if STOP.exists() != stopped:
            stopped = STOP.exists()
            log(f"[{n:%m-%d %H:%M}] " + ("STOP 파일 감지 → 대기" if stopped else "STOP 해제 → 재개"))
        action = next_action(n, load_state(), first, last_try)
        first = False
        if action:
            log(f"[{n:%m-%d %H:%M}] {action}")
            if action == "decide":
                last_try = n
            try:
                (run_decide if action == "decide" else run_execute)()
            except Exception as e:  # noqa: BLE001 — 한 번 실패해도 루프는 계속
                log(f"  실패: {type(e).__name__}: {e}")
        sleep(60)


# ──────────────────────────────────────────────────────────────
# execute: 대기 주문을 토스에 낸다 (매도 먼저 → 현금 확보 후 매수)
# ──────────────────────────────────────────────────────────────
def execute(cfg, journal, client, broker, account: int) -> list[str]:
    state = load_state()
    msgs = refresh_open(journal, client, account, state)
    if STOP.exists():
        save_state(state)
        raise RuntimeError(f"{STOP} 파일이 있어 주문하지 않습니다 (지우면 재개)")
    pending = state.get("pending", [])
    if not pending:
        save_state(state)
        return msgs + ["대기 주문 없음"]
    now = now_kst()
    if now.weekday() >= 5 or not time(9, 0) <= now.time() <= time(15, 20):
        raise RuntimeError("정규장(평일 09:00~15:20 KST)에만 주문합니다")
    if now.strftime("%Y-%m-%d") <= state.get("decided_for", ""):
        raise RuntimeError(f"{state['decided_for']} 종가 판단은 다음 거래일에 실행합니다")

    timeout = cfg["execution"].get("live_fill_timeout", 60)
    real = {it["symbol"]: int(float(it["quantity"])) for it in client.holdings(account)["items"]
            if it.get("marketCountry") == "KR"}
    left = []
    for o in sorted(pending, key=lambda x: x["side"] != "SELL"):
        sym = symbol_of(o["ticker"])
        row = journal.query("SELECT client_order_id FROM orders WHERE order_id=?", o["order_id"])[0]
        qty = o["qty"]
        if o["side"] == "SELL":
            qty = min(qty, real.get(sym, 0))
        else:  # 체결가가 판단 때 종가와 다를 수 있으니 매수 가능 금액 안으로 줄인다
            last = float(client.prices([sym])[0]["lastPrice"])
            bp = float(client.buying_power(account, "KRW")["cashBuyingPower"])
            qty = min(qty, math.floor(bp / (last * 1.01)))
        if qty <= 0:
            journal.update_order(o["order_id"], status="REJECTED", note="수량 0 (매수 가능 금액 또는 보유 수량 부족)")
            msgs.append(f"  {o['ticker']} {o['side']}: 수량 0 → 건너뜀")
            continue
        try:
            boid = broker.submit(sym, o["side"], qty, broker_order_id(row["client_order_id"]))
        except TossError as e:
            if e.code == "order-hours-closed":  # 장이 안 열렸으면 남겨 두고 다음에 다시
                left.append(o)
                msgs.append(f"  {o['ticker']} {o['side']}: 주문 시간이 아님 → 대기 유지")
                continue
            journal.update_order(o["order_id"], status="REJECTED", note=str(e))
            msgs.append(f"  {o['ticker']} {o['side']} {qty}주: 거부 {e}")
            continue
        journal.update_order(o["order_id"], broker_order_id=boid, status="SUBMITTED", qty=qty)
        res = broker.wait(boid, timeout=timeout)
        record_fill(journal, o["order_id"], res)
        ex = res.get("execution") or {}
        msgs.append(f"  {o['ticker']} {o['side']} {qty}주: {res['status']} · 체결 {ex.get('filledQuantity')}주 "
                    f"@ {ex.get('averageFilledPrice')}")
        if res["status"] not in FINAL:
            state.setdefault("open", []).append({**o, "broker_order_id": boid})
    state["pending"] = left
    save_state(state)
    return msgs
