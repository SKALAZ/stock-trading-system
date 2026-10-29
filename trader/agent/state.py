"""
그래프 상태(State)
──────────────────────────────────────────────────────────────
모든 노드가 함께 읽고 쓰는 공유 데이터입니다.
노드는 상태 전체를 돌려주지 않고, "바꾸고 싶은 항목만" 담은 dict를 돌려줍니다.
LangGraph가 그 dict를 기존 상태에 반영합니다.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from trader.agent.context import AgentContext
from trader.agent.schema import Decision


class AgentState(TypedDict, total=False):
    # ── 입력 ─────────────────────────────
    ctx: AgentContext           # 오늘의 후보·포트폴리오와 읽기 전용 도구
    max_steps: int              # GPT 호출 최대 횟수 (loop.py 의 max_steps)

    # ── 루프 ─────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]   # 대화 기록 (새 메시지는 뒤에 붙음)
    step: int                                              # 지금까지 GPT를 부른 횟수
    steps: Annotated[list[dict], operator.add]             # 단계별 로그 (기록용)

    # ── 출력 ─────────────────────────────
    decisions: list[Decision]   # 최종 판단
    invalid: list[dict]         # 형식이 틀린 판단 (가드레일 G01에서 거부로 기록)
