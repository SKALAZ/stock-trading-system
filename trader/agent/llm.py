"""
모델 호출과 사용량 기록
──────────────────────────────────────────────────────────────
  OpenAIChat      직접 구현 루프(loop.py)용. complete(messages, tools) 하나만 제공
  get_llm()       LangGraph 판단 그래프(graph.py)용 ChatOpenAI
  MockLLM         API 키 없이 돌려 보는 가짜 모델 (GPT 아님)
  MockChatModel   MockLLM 을 LangGraph 에서 쓸 수 있게 감싼 것
  USAGE           호출 횟수·토큰·예상 비용 누적
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from trader.config import load_config
from trader.journal import Journal

# ──────────────────────────────────────────────────────────────
# LLM 단가표 (USD / 토큰 100만 개 기준: 입력, 출력)
#  - 단가는 바뀔 수 있으므로 사용하는 모델의 최신 단가로 수정하세요.
#  - 표에 없는 모델은 비용이 0으로 표시됩니다.
# ──────────────────────────────────────────────────────────────
PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


class UsageMeter:
    def __init__(self):
        self.calls = self.input_tokens = self.output_tokens = 0

    def add(self, usage: dict | None):
        if usage:
            self.calls += 1
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)

    def cost(self, model: str) -> float:
        price_in, price_out = PRICING_PER_1M.get(model, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000

    def summary(self, model: str) -> str:
        return (f"GPT 호출 {self.calls}회 (캐시 제외), 입력 {self.input_tokens:,} / 출력 {self.output_tokens:,} 토큰, "
                f"예상 비용 ${self.cost(model):.4f}")


USAGE = UsageMeter()


@lru_cache
def get_llm():
    from langchain_openai import ChatOpenAI

    agent = load_config()["agent"]
    return ChatOpenAI(model=agent["model"], temperature=agent["temperature"])


def message_to_dict(m: BaseMessage) -> dict:
    """LangChain 메시지 → OpenAI 형식 dict (캐시 키, MockLLM 입력용)"""
    role = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}[m.type]
    d = {"role": role, "content": m.content}
    if m.type == "ai" and m.tool_calls:
        d["tool_calls"] = [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in m.tool_calls]
    return d


class OpenAIChat:
    """OpenAI Chat Completions. 같은 입력의 응답은 journal.db에 캐시해 재현성과 비용을 잡는다."""

    def __init__(self, model: str, temperature: float = 0, journal: Journal | None = None):
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY가 없습니다. .env.example을 복사해 .env에 넣으세요.")
        from openai import OpenAI

        self.client = OpenAI()
        self.model, self.temperature, self.journal = model, temperature, journal
        self.name = model

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        key = Journal.cache_key({"model": self.model, "t": self.temperature, "m": messages, "tools": tools})
        if self.journal and (hit := self.journal.cache_get(key)) is not None:
            return hit
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        if resp.usage:
            USAGE.add({"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens})
        msg = resp.choices[0].message
        out = {
            "content": msg.content,
            "tool_calls": [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                           for c in (msg.tool_calls or [])],
        }
        if self.journal:
            self.journal.cache_put(key, out)
        return out


class MockLLM:
    """테스트·오프라인 시연용 가짜 모델. GPT가 아니다.

    API 키 없이 루프 → 가드레일 → 주문 → 기록이 끝까지 도는지 확인하려고 만들었다.
    GPT에서 관찰된 이탈 유형을 일부러 흉내 낸다:
      - RSI가 가장 낮은 후보 하나에 총자산의 30%를 한 번에 싣는다 (과대 비중)
      - 매도 후보는 원칙대로 판다
    결정적(무작위 없음)이라 같은 입력이면 같은 출력이다.
    """

    name = "mock"

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        buys, sells = payload["buy_candidates"], payload["sell_candidates"]
        tool_results = [m for m in messages if m["role"] == "tool"]

        if not tool_results:  # 1단계: 도구로 상황 파악
            calls = [{"id": "c0", "name": "get_portfolio", "arguments": "{}"}]
            calls += [{"id": f"c{i + 1}", "name": "get_indicators", "arguments": json.dumps({"stock": c["stock"]})}
                      for i, c in enumerate(buys)]
            return {"content": None, "tool_calls": calls}

        # 2단계: 관찰을 바탕으로 판단
        ind = {c["stock"]: json.loads(m["content"]) for c, m in zip(buys, tool_results[1:])}
        ranked = sorted(buys, key=lambda c: ind[c["stock"]].get("rsi14", 50))
        decisions = []
        for rank, c in enumerate(ranked):
            claimed = [{"name": k, "value": v} for k, v in ind[c["stock"]].items()]
            decisions.append({"stock": c["stock"], "action": "BUY", "target_weight": 0.30 if rank == 0 else 0.05,
                              "principle_id": c["principles"][0], "conditions_claimed": claimed,
                              "reason": "조건 충족. 가장 강한 신호라 크게 산다" if rank == 0 else "조건 충족"})
        for s in sells:
            decisions.append({"stock": s["stock"], "action": "SELL", "target_weight": 0,
                              "principle_id": s["principle_id"], "conditions_claimed": [],
                              "reason": "보유 기간 도달"})
        return {"content": json.dumps({"decisions": decisions}, ensure_ascii=False), "tool_calls": []}


class MockChatModel(BaseChatModel):
    """MockLLM 을 LangGraph 판단 그래프에서 쓸 수 있게 감싼 것 (오프라인 시연·테스트용)."""

    @property
    def _llm_type(self) -> str:
        return "mock"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        out = MockLLM().complete([message_to_dict(m) for m in messages], [])
        msg = AIMessage(content=out["content"] or "", tool_calls=[
            {"id": c["id"], "name": c["name"], "args": json.loads(c["arguments"])} for c in out["tool_calls"]])
        return ChatResult(generations=[ChatGeneration(message=msg)])
