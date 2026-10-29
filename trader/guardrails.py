"""③ 가드레일 — 주문 직전 마지막 확인.

GPT의 판단은 살리고, 넘지 말아야 할 선만 정한다. 판정은 세 가지:
  PASS   그대로 통과
  CLIP   한도까지 줄여서 통과
  REJECT 거부

검사 순서: 형식 → 원칙 → 계좌 → 시장 → 비중
  G01 형식 (알 수 있는 종목, 비중 0~1)          REJECT
  G02 인용 원칙이 검정 통과 상태                 REJECT
  G03 인용 원칙 조건을 코드로 다시 계산해 충족   REJECT   (매수만)
  G04 보유하지 않은 종목은 매도 불가             REJECT
  G05 같은 종목 당일 중복 주문 금지              REJECT
  G09 하루 주문 건수 상한                        REJECT
  G10 당일 손실 한도 도달 시 신규 매수 중단      REJECT   (매도는 허용)
  G07 한 종목 보유 비중 상한                     CLIP
  G06 1회 주문 금액 상한                         CLIP
  G08 최소 현금 비중 유지                        CLIP (여유가 없으면 REJECT)
  F01 강제 손절 — 엔진이 GPT와 무관하게 매도 주문을 만든다 (engine.py)
"""
import math
from dataclasses import dataclass, field

from trader.agent.context import AgentContext
from trader.agent.schema import Decision

PASS, CLIP, REJECT, HOLD = "PASS", "CLIP", "REJECT", "HOLD"


@dataclass
class Check:
    rule: str
    verdict: str
    reason: str
    before: float | None = None
    after: float | None = None


@dataclass
class DayState:
    """같은 날 앞선 주문을 반영하기 위한 상태 (현금이 두 번 쓰이지 않도록)."""
    cash_weight: float
    day_return: float
    orders: int = 0
    tickers: set = field(default_factory=set)


@dataclass
class GuardResult:
    verdict: str          # PASS / CLIP / REJECT / HOLD
    ticker: str | None
    final_weight: float   # 매수: 최종 목표 비중, 매도: 0
    checks: list[Check]


def check(dec: Decision, ctx: AgentContext, day: DayState, g: dict) -> GuardResult:
    checks: list[Check] = []
    ticker = ctx.ticker_of(dec.stock)

    def ok(rule, reason):
        checks.append(Check(rule, PASS, reason))

    def reject(rule, reason, before=None):
        checks.append(Check(rule, REJECT, reason, before))
        return GuardResult(REJECT, ticker, 0.0, checks)

    # ── 형식 ──
    if ticker is None:
        return reject("G01", f"알 수 없는 종목 {dec.stock}")
    w = dec.target_weight
    if math.isnan(w) or not 0 <= w <= 1:
        return reject("G01", f"목표 비중 {w}가 0~1 밖", w)
    ok("G01", "형식 정상")
    if dec.action == "HOLD":
        return GuardResult(HOLD, ticker, ctx.weight(ticker), checks)

    # ── 원칙 ──
    p = ctx.principles.get(dec.principle_id)
    if p is None:
        return reject("G02", f"{dec.principle_id}는 검정을 통과한 원칙이 아님")
    ok("G02", f"{p.id} 사용 가능")

    if dec.action == "BUY":
        if not p.matches(ctx.rows[ticker]):
            return reject("G03", f"{p.id} 조건 `{p.entry}`을 다시 계산하니 미충족")
        ok("G03", "원칙 조건 재계산 일치")

    # ── 계좌 ──
    if dec.action == "SELL":
        if ticker not in ctx.holdings:
            return reject("G04", "보유하지 않은 종목 매도")
        ok("G04", "보유 수량 내 매도")
    if ticker in day.tickers:
        return reject("G05", "같은 종목 당일 중복 주문")

    # ── 시장 ──
    if day.orders >= g["max_orders_per_day"]:
        return reject("G09", f"하루 주문 {g['max_orders_per_day']}건 초과")
    if dec.action == "SELL":
        return GuardResult(PASS, ticker, 0.0, checks)
    if day.day_return <= g["daily_loss_stop"]:
        return reject("G10", f"당일 손익 {day.day_return:.2%} ≤ {g['daily_loss_stop']:.0%}, 신규 매수 중단",
                      day.day_return)

    # ── 비중 (매수만) ──
    now, target, clipped = ctx.weight(ticker), w, False
    if target > g["max_position_weight"]:
        checks.append(Check("G07", CLIP, "종목 비중 상한", target, g["max_position_weight"]))
        target, clipped = g["max_position_weight"], True
    if target <= now + 1e-9:
        return reject("G07", f"이미 비중 {now:.1%}로 상한 이상", now)
    if target - now > g["max_order_weight"]:
        checks.append(Check("G06", CLIP, "1회 주문 상한", target, now + g["max_order_weight"]))
        target, clipped = now + g["max_order_weight"], True
    room = day.cash_weight - g["min_cash_weight"]
    if target - now > room:
        if room <= 1e-9:
            return reject("G08", f"현금 비중 {day.cash_weight:.1%}, 최소 {g['min_cash_weight']:.0%} 유지", day.cash_weight)
        checks.append(Check("G08", CLIP, "최소 현금 유지", target, now + room))
        target, clipped = now + room, True
    if not clipped:
        ok("G06-08", "비중 한도 이내")
    return GuardResult(CLIP if clipped else PASS, ticker, target, checks)
