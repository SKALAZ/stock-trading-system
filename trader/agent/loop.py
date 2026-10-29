"""② 판단 루프 — 직접 구현한 추론-실행(ReAct) 루프.

  모델 호출 → 도구 호출이 있으면 실행하고 결과를 대화에 붙임 → 다시 모델 호출 → … → 최종 JSON
LangGraph 버전(graph.py)도 같은 일을 한다. 이 파일이 원리 설명용 기준 구현이다.
"""
import json

from pydantic import ValidationError

from trader.agent.context import TOOL_SPECS, AgentContext, call_tool
from trader.agent.prompts import SYSTEM_PROMPT, user_prompt
from trader.agent.schema import Decision


def parse_decisions(text: str | None) -> tuple[list[Decision], list[dict]]:
    """최종 응답을 Decision 목록으로. 형식이 틀린 항목은 버리지 않고 invalid로 돌려 G01에서 기록한다."""
    try:
        raw = json.loads((text or "").strip().removeprefix("```json").removesuffix("```"))
        items = raw["decisions"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return [], [{"raw": text, "error": f"JSON 해석 실패: {e}"}]
    valid, invalid = [], []
    for item in items:
        try:
            valid.append(Decision.model_validate(item))
        except ValidationError as e:
            invalid.append({"raw": item, "error": str(e.errors()[0]["msg"])})
    return valid, invalid


def run_agent(ctx: AgentContext, llm, max_steps: int = 6) -> tuple[list[Decision], list[dict], list[dict]]:
    """반환: (판단 목록, 형식 오류 항목, 단계별 로그)"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(ctx.candidates, ctx.exit_due)}]
    steps = []
    for step in range(max_steps):
        msg = llm.complete(messages, TOOL_SPECS)
        if not msg["tool_calls"]:                       # 도구 호출이 없으면 최종 답
            steps.append({"step": step, "final": msg["content"]})
            decisions, invalid = parse_decisions(msg["content"])
            return decisions, invalid, steps

        # 추론 → 도구 실행 → 관찰을 대화에 붙인다
        messages.append({"role": "assistant", "content": msg["content"], "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in msg["tool_calls"]]})
        for c in msg["tool_calls"]:
            result = call_tool(ctx, c["name"], c["arguments"])
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
            steps.append({"step": step, "tool": c["name"], "args": c["arguments"], "result": result})

    return [], [{"raw": None, "error": "MAX_STEPS: 단계 한도 안에 결론을 내지 못함 → 전부 HOLD"}], steps
