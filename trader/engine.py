"""
하루 실행 흐름 (백테스트·모의투자 공통)
──────────────────────────────────────────────────────────────
  장 시작   ④ 어제 낸 주문을 오늘 시가에 체결
  장 마감   종가로 평가 → 후보 스크리닝(코드) → ② GPT 판단 → ③ 가드레일 → 주문 접수 → ⑤ 기록
            (F01 강제 손절은 GPT와 무관하게 엔진이 매도 주문을 만든다)

가드레일을 끈 실행(enforce=False)에서도 가드레일 판정은 계산해서 기록만 한다(shadow).
→ 같은 GPT 판단을 가드레일이 얼마나 막았을지(오프라인 필터)와,
  가드레일을 켜고 다시 돌린 결과(폐루프)를 함께 비교할 수 있다.
"""
from __future__ import annotations

import math
import string
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from trader.agent.context import CONTEXT_EXPR, AgentContext, normalized
from trader.broker import SimBroker
from trader.guardrails import CLIP, HOLD, REJECT, DayState, check
from trader.indicators import add_indicators
from trader.journal import Journal
from trader.principles import Principle


@dataclass
class Position:
    qty: int
    avg_cost: float
    principle_id: str
    held_days: int = 0


@dataclass
class PendingOrder:
    order_id: int
    ticker: str
    side: str
    qty: int
    principle_id: str


def make_aliases(tickers: list[str], seed: int) -> dict[str, str]:
    """종목 익명화: 티커 순서를 섞어 STOCK_A, STOCK_B, … STOCK_AA … 를 붙인다."""
    letters = string.ascii_uppercase
    names = [letters[i] if i < 26 else letters[i // 26 - 1] + letters[i % 26] for i in range(len(tickers))]
    order = np.random.default_rng(seed).permutation(len(tickers))
    return {tickers[j]: f"STOCK_{names[i]}" for i, j in enumerate(order)}


class Engine:
    def __init__(self, cfg: dict, stocks: dict, bench: pd.DataFrame, principles: dict[str, Principle],
                 test_ids: dict[str, int], decide, agent_name: str, journal: Journal, run_id: int,
                 enforce: bool = True):
        self.cfg, self.g = cfg, cfg["guardrails"]
        self.principles, self.test_ids = principles, test_ids
        self.decide, self.agent_name = decide, agent_name
        self.journal, self.run_id, self.enforce = journal, run_id, enforce
        self.broker = SimBroker(cfg["costs"])

        exprs = [p.entry for p in principles.values()] + [CONTEXT_EXPR]
        self.data = {t: add_indicators(df, exprs) for t, df in stocks.items()}
        self.signals = {pid: {t: p.signal(df) for t, df in self.data.items()} for pid, p in principles.items()}
        self.close = pd.DataFrame({t: df["close"] for t, df in self.data.items()}).reindex(bench.index).ffill()
        self.aliases = make_aliases(sorted(stocks), cfg["test"]["seed"])

        self.cash = float(cfg["execution"]["initial_cash"])
        self.positions: dict[str, Position] = {}
        self.pending: list[PendingOrder] = []
        self.prev_equity: float | None = None

    # ──────────────────────────────────────────────────────────────
    # 상태 저장/복원 (모의투자는 하루씩 실행되므로 상태를 파일에 남긴다)
    # ──────────────────────────────────────────────────────────────
    def state(self) -> dict:
        return {"cash": self.cash, "prev_equity": self.prev_equity,
                "positions": {t: asdict(p) for t, p in self.positions.items()},
                "pending": [asdict(o) for o in self.pending]}

    def load_state(self, s: dict):
        self.cash, self.prev_equity = s["cash"], s["prev_equity"]
        self.positions = {t: Position(**p) for t, p in s["positions"].items()}
        self.pending = [PendingOrder(**o) for o in s["pending"]]

    # ──────────────────────────────────────────────────────────────
    # 하루 실행
    # ──────────────────────────────────────────────────────────────
    def step(self, date: pd.Timestamp):
        ds = date.strftime("%Y-%m-%d")
        filled = self._fill_pending(date, ds)
        for pos in self.positions.values():
            pos.held_days += 1

        closes = self.close.loc[date]
        equity = self.cash + sum(p.qty * closes[t] for t, p in self.positions.items())
        day_return = equity / self.prev_equity - 1 if self.prev_equity else 0.0
        holdings = {t: {"qty": p.qty, "weight": round(p.qty * closes[t] / equity, 4),
                        "pnl": round(closes[t] / p.avg_cost - 1, 4), "held_days": p.held_days,
                        "principle_id": p.principle_id}
                    for t, p in self.positions.items()}
        for oid, t in filled:
            self.journal.update_order(oid, weight_after=holdings.get(t, {}).get("weight", 0.0))

        day = DayState(cash_weight=self.cash / equity, day_return=day_return)
        pending_tickers = {o.ticker for o in self.pending}

        # F01 강제 손절: GPT에게 묻지 않는다
        forced = [t for t, h in holdings.items() if self.enforce and h["pnl"] <= self.g["stop_loss"]]
        for t in forced:
            self._submit(ds, None, "F", t, "SELL", 0.0, 0.0, "FORCED", "F01", equity, closes, day)

        # 후보 스크리닝 (코드): 원칙 조건을 충족한 미보유 종목 / 보유 기간이 찬 보유 종목
        rows = {t: df.loc[date] for t, df in self.data.items() if date in df.index}
        candidates = []
        for t in sorted(rows, key=self.aliases.get):
            if t in self.positions or t in pending_tickers:
                continue
            hits = [pid for pid in self.principles if self.signals[pid][t].get(date, False)]
            if hits:
                candidates.append({"stock": self.aliases[t], "principles": hits})
        exit_due = [{"stock": self.aliases[t], "principle_id": p.principle_id, "held_days": p.held_days}
                    for t, p in self.positions.items()
                    if t not in forced and p.principle_id in self.principles
                    and p.held_days >= self.principles[p.principle_id].horizon_days]

        if candidates or exit_due:
            exprs = [p.entry for p in self.principles.values()]
            ctx = AgentContext(
                date=ds, aliases=self.aliases, principles=self.principles, rows=rows,
                shown={self.aliases[t]: normalized(r, exprs) for t, r in rows.items()},
                candidates=candidates, exit_due=exit_due, holdings=holdings,
                cash_weight=day.cash_weight, equity=equity)
            self._decide_and_order(ds, ctx, day, equity, closes)

        n_pos = len(self.positions)
        max_w = max((h["weight"] for h in holdings.values()), default=0.0)
        self.journal.log_equity(self.run_id, ds, equity, self.cash, n_pos, max_w)
        self.prev_equity = equity
        return equity

    def _decide_and_order(self, ds, ctx, day, equity, closes):
        decisions, invalid, steps = self.decide(ctx)
        did = self.journal.log_decision(
            run_id=self.run_id, date=ds, agent=self.agent_name, model=self.cfg["agent"]["model"],
            prompt_version=self.cfg["agent"]["prompt_version"], context=ctx.to_log(), steps=steps,
            output=[d.model_dump() for d in decisions] + invalid,
            principle_test_ids={pid: self.test_ids.get(pid) for pid in self.principles})
        for k, bad in enumerate(invalid):  # 형식이 틀린 판단은 G01에서 거부된 것으로 기록
            self.journal.log_check(decision_id=did, item=-(k + 1), ticker=None, action=None, principle_id=None,
                                   rule="G01", verdict=REJECT, before=None, after=None,
                                   reason=bad["error"], enforced=int(self.enforce))

        for i, dec in enumerate(decisions):
            res = check(dec, ctx, day, self.g)
            for c in res.checks:
                self.journal.log_check(decision_id=did, item=i, ticker=res.ticker, action=dec.action,
                                       principle_id=dec.principle_id, rule=c.rule, verdict=c.verdict,
                                       before=c.before, after=c.after, reason=c.reason,
                                       enforced=int(self.enforce))
            if dec.action == "HOLD" or res.verdict == HOLD:
                continue
            if self.enforce:
                if res.verdict == REJECT:
                    continue
                weight = res.final_weight
            else:
                # 가드레일 끔: 판정은 위에서 기록만 하고 GPT 원안대로 실행한다.
                # 단, 물리적으로 불가능한 주문(모르는 종목, 미보유 매도)은 실행할 수 없다.
                if res.ticker is None or (dec.action == "SELL" and res.ticker not in self.positions):
                    continue
                w = dec.target_weight
                weight = 0.0 if math.isnan(w) else min(max(w, 0.0), 1.0)
            self._submit(ds, did, i, res.ticker, dec.action, dec.target_weight, weight,
                         res.verdict, dec.principle_id, equity, closes, day)

    def _submit(self, ds, did, item, ticker, side, requested, weight, verdict, principle_id, equity, closes, day):
        if side == "BUY":
            now = self.positions[ticker].qty * closes[ticker] / equity if ticker in self.positions else 0.0
            delta = weight - now
            qty = math.floor(max(delta, 0) * equity / closes[ticker])
            day.cash_weight -= max(delta, 0)
        else:
            qty = self.positions[ticker].qty
        if qty <= 0:
            return
        oid = self.journal.log_order(
            run_id=self.run_id, decision_id=did, item=item if isinstance(item, int) else -1,
            client_order_id=f"{self.run_id}-{ds}-{ticker}-{side}-{item}", date=ds, ticker=ticker, side=side,
            qty=qty, requested_weight=requested, final_weight=weight, verdict=verdict,
            source="F01" if verdict == "FORCED" else "AGENT", status="PENDING")
        self.pending.append(PendingOrder(oid, ticker, side, qty, principle_id))
        day.orders += 1
        day.tickers.add(ticker)

    def _fill_pending(self, date, ds) -> list[tuple[int, str]]:
        filled = []
        for o in self.pending:
            df = self.data[o.ticker]
            if date not in df.index:  # 거래정지 → 주문 취소
                self.journal.update_order(o.order_id, status="CANCELLED", fill_date=ds)
                continue
            px, qty, cash_change = self.broker.execute(o.side, o.qty, float(df.at[date, "open"]), self.cash)
            if qty <= 0:
                self.journal.update_order(o.order_id, status="CANCELLED", fill_date=ds)
                continue
            self.cash += cash_change
            if o.side == "BUY":
                pos = self.positions.get(o.ticker)
                if pos:
                    pos.avg_cost = (pos.avg_cost * pos.qty + px * qty) / (pos.qty + qty)
                    pos.qty += qty
                else:
                    self.positions[o.ticker] = Position(qty, px, o.principle_id)
            else:
                self.positions.pop(o.ticker, None)
            self.journal.update_order(o.order_id, status="FILLED", fill_date=ds, fill_price=px, fill_qty=qty)
            filled.append((o.order_id, o.ticker))
        self.pending = []
        return filled
