"""GPT 판단의 출력 형식. 값의 범위(비중 0~1 등)는 여기서 막지 않고 가드레일 G01이 판정한다."""
from typing import Literal

from pydantic import BaseModel, Field


class ClaimedCondition(BaseModel):
    """GPT가 근거로 든 지표 값. 기록용이다 — 조건 충족 여부는 가드레일 G03이 코드로 다시 계산한다.
    그래서 GPT가 "N/A" 같은 글자를 넣어도 판단 전체를 버리지 않는다 (실제 GPT 백테스트에서 매도가 막힌 사례)."""
    name: str = Field(description="지표 이름. 예: rsi14, close_to_sma60")
    value: float | str | None = Field(description="GPT가 읽은 값 (참/거짓은 1/0)")


class Decision(BaseModel):
    stock: str = Field(description="익명 종목 코드. 예: STOCK_A")
    action: Literal["BUY", "SELL", "HOLD"]
    target_weight: float = Field(description="매수 후 이 종목의 목표 보유 비중 (0~1). 매도·HOLD는 0")
    principle_id: str = Field(description="판단 근거 원칙 id. 예: P-001")
    conditions_claimed: list[ClaimedCondition] = Field(default_factory=list)
    reason: str


class DecisionBatch(BaseModel):
    decisions: list[Decision]
