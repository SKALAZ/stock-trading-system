"""
판단 그래프의 노드
──────────────────────────────────────────────────────────────
  decider   GPT 호출 (도구를 부를지, 결론을 낼지 GPT가 정함)
  tools     GPT가 부른 읽기 전용 도구 실행 → 결과를 대화에 붙임
  parse     최종 답(JSON)을 Decision 목록으로 변환
  give_up   단계 한도 초과 → 전부 HOLD

loop.py 와의 대응
  llm.complete(...)            → decider
  for c in msg["tool_calls"]   → tools
  parse_decisions(...)         → parse
  for 루프가 끝까지 돈 경우     → give_up
"""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from trader.agent.context import TOOL_SPECS, call_tool
from trader.agent.llm import USAGE, get_llm, message_to_dict
from trader.agent.loop import parse_decisions
from trader.agent.state import AgentState
from trader.journal import Journal


# ──────────────────────────────────────────────────────────────
# decider : GPT 호출
#  - 같은 입력의 응답은 journal.db 에 캐시합니다 (재현성 + 비용 절감).
# ──────────────────────────────────────────────────────────────
def decider(state: AgentState, config: RunnableConfig) -> dict:
    conf = config.get("configurable", {})
    model = conf.get("model") or get_llm()
    journal: Journal | None = conf.get("journal")

    key = Journal.cache_key({"graph": getattr(model, "model_name", type(model).__name__),
                             "m": [message_to_dict(m) for m in state["messages"]]})
    hit = journal.cache_get(key) if journal else None
    if hit is not None:
        response = AIMessage(content=hit["content"], tool_calls=hit["tool_calls"])
    else:
        response = model.bind_tools(TOOL_SPECS).invoke(state["messages"])
        USAGE.add(getattr(response, "usage_metadata", None))
        if journal:
            journal.cache_put(key, {"content": response.content, "tool_calls": response.tool_calls})

    step = state.get("step", 0)
    log = {"step": step, "tool_calls": [{"name": c["name"], "args": c["args"]} for c in response.tool_calls]}
    if not response.tool_calls:
        log["final"] = response.content
    return {"messages": [response], "step": step + 1, "steps": [log]}


def route_after_decider(state: AgentState) -> str:
    """조건부 엣지: 도구 호출이 있으면 tools, 없으면 parse, 한도를 넘으면 give_up"""
    last = state["messages"][-1]
    if not last.tool_calls:
        return "parse"
    return "give_up" if state["step"] >= state["max_steps"] else "tools"


# ──────────────────────────────────────────────────────────────
# tools : 읽기 전용 도구 실행 (주문 도구는 없습니다)
# ──────────────────────────────────────────────────────────────
def tools(state: AgentState) -> dict:
    ctx, last = state["ctx"], state["messages"][-1]
    results, logs = [], []
    for c in last.tool_calls:
        result = call_tool(ctx, c["name"], json.dumps(c["args"]))
        results.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=c["id"]))
        logs.append({"step": state["step"] - 1, "tool": c["name"], "args": c["args"], "result": result})
    return {"messages": results, "steps": logs}


# ──────────────────────────────────────────────────────────────
# parse / give_up : 최종 출력
# ──────────────────────────────────────────────────────────────
def parse(state: AgentState) -> dict:
    decisions, invalid = parse_decisions(state["messages"][-1].content)
    return {"decisions": decisions, "invalid": invalid}


def give_up(state: AgentState) -> dict:
    return {"decisions": [], "invalid": [{"raw": None, "error": "MAX_STEPS: 단계 한도 안에 결론을 내지 못함 → 전부 HOLD"}]}
