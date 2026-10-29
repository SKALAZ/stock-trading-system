"""GPT에게 보여 줄 하루치 상황과, GPT가 쓸 수 있는 읽기 전용 도구.

정보 누출 방지: GPT는 과거 시세를 학습했을 수 있으므로 종목은 STOCK_A처럼 가리고,
날짜는 주지 않으며, 가격 대신 정규화한 지표(종가/이평 비율 등)만 보여 준다.
"""
import json
import math
from dataclasses import dataclass

import pandas as pd

from trader.indicators import tokens
from trader.principles import Principle

# 원칙과 무관하게 GPT에게 항상 보여 주는 지표
CONTEXT_EXPR = "rsi14 sma20 sma60 vol_ratio20 ret5 ret20"


def normalized(row: pd.Series, exprs: list[str]) -> dict:
    """가격 수준을 숨긴 지표 값. smaN은 종가/smaN 비율로 바꾼다."""
    out = {}
    for kind, n in sorted(tokens(exprs + [CONTEXT_EXPR])):
        v = row.get(f"{kind}{n}")
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        if kind == "sma":
            out[f"close_to_sma{n}"] = round(float(row["close"] / v), 4)
        else:
            out[f"{kind}{n}"] = round(float(v), 4)
    return out


@dataclass
class AgentContext:
    date: str                          # 기록용. GPT에게는 보내지 않는다
    aliases: dict[str, str]            # ticker → STOCK_A
    principles: dict[str, Principle]   # 검정 통과(사용 가능) 원칙
    rows: dict[str, pd.Series]         # ticker → 오늘 지표 원본 (가드레일 재계산용, GPT 비공개)
    shown: dict[str, dict]             # alias → GPT에게 보여 주는 정규화 지표
    candidates: list[dict]             # [{"stock": "STOCK_A", "principles": ["P-001"]}]
    exit_due: list[dict]               # [{"stock", "principle_id", "held_days"}]
    holdings: dict[str, dict]          # ticker → {qty, weight, pnl, held_days, principle_id}
    cash_weight: float
    equity: float

    def ticker_of(self, alias: str) -> str | None:
        return {a: t for t, a in self.aliases.items()}.get(alias)

    def weight(self, ticker: str) -> float:
        return self.holdings.get(ticker, {}).get("weight", 0.0)

    # ── 읽기 전용 도구 (주문 도구는 없다) ─────────────────────
    def get_active_principles(self) -> list[dict]:
        """검정을 통과해 사용할 수 있는 투자 원칙 목록"""
        return [p.describe() for p in self.principles.values()]

    def get_indicators(self, stock: str) -> dict:
        """종목의 오늘 기술지표 (정규화 값)"""
        return self.shown.get(stock, {"error": f"{stock}: 알 수 없는 종목"})

    def get_portfolio(self) -> dict:
        """현금 비중과 보유 종목 (비중, 평가손익률, 보유일수, 근거 원칙)"""
        return {
            "cash_weight": round(self.cash_weight, 4),
            "holdings": [{"stock": self.aliases[t], **{k: v for k, v in h.items() if k != "qty"}}
                         for t, h in self.holdings.items()],
        }

    def tool_functions(self) -> dict:
        return {"get_active_principles": self.get_active_principles,
                "get_indicators": self.get_indicators,
                "get_portfolio": self.get_portfolio}

    def to_log(self) -> dict:
        """기록용 스냅샷 (가드레일을 나중에 다시 돌려 볼 수 있을 만큼)."""
        return {"date": self.date, "aliases": self.aliases, "principles": list(self.principles),
                "candidates": self.candidates, "exit_due": self.exit_due,
                "holdings": self.holdings, "cash_weight": self.cash_weight, "equity": self.equity,
                "shown": self.shown}

    @classmethod
    def from_log(cls, d: dict, principles: dict[str, Principle]) -> "AgentContext":
        """기록된 스냅샷으로 GPT가 봤던 입력을 그대로 재현한다 (에이전트 간 비교용)."""
        return cls(date=d["date"], aliases=d["aliases"],
                   principles={k: principles[k] for k in d["principles"]}, rows={}, shown=d["shown"],
                   candidates=d["candidates"], exit_due=d["exit_due"], holdings=d["holdings"],
                   cash_weight=d["cash_weight"], equity=d["equity"])


# OpenAI tool-calling 형식의 도구 명세
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_active_principles", "description": AgentContext.get_active_principles.__doc__,
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_indicators", "description": AgentContext.get_indicators.__doc__,
        "parameters": {"type": "object", "properties": {"stock": {"type": "string"}}, "required": ["stock"]}}},
    {"type": "function", "function": {
        "name": "get_portfolio", "description": AgentContext.get_portfolio.__doc__,
        "parameters": {"type": "object", "properties": {}}}},
]


def call_tool(ctx: AgentContext, name: str, arguments: str) -> dict | list:
    fn = ctx.tool_functions().get(name)
    if fn is None:
        return {"error": f"없는 도구: {name}"}
    try:
        return fn(**json.loads(arguments or "{}"))
    except (TypeError, json.JSONDecodeError) as e:
        return {"error": f"잘못된 인자: {e}"}
