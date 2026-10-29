"""
판단 그래프 구성 (LangGraph) — loop.py 의 for 루프를 그래프로 옮긴 것
──────────────────────────────────────────────────────────────
  START → decider ─(도구 호출 있음)→ tools → decider
                  ├─(결론)──────────→ parse → END
                  └─(단계 한도 초과)→ give_up → END
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from trader.agent.context import AgentContext
from trader.agent.nodes import decider, give_up, parse, route_after_decider, tools
from trader.agent.prompts import SYSTEM_PROMPT, user_prompt
from trader.agent.schema import Decision
from trader.agent.state import AgentState


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("decider", decider)
    g.add_node("tools", tools)
    g.add_node("parse", parse)
    g.add_node("give_up", give_up)

    g.add_edge(START, "decider")
    g.add_conditional_edges("decider", route_after_decider,
                            {"tools": "tools", "parse": "parse", "give_up": "give_up"})
    g.add_edge("tools", "decider")
    g.add_edge("parse", END)
    g.add_edge("give_up", END)

    return g.compile()


graph = build_graph()


def run_agent_graph(ctx: AgentContext, model=None, journal=None,
                    max_steps: int = 6) -> tuple[list[Decision], list[dict], list[dict]]:
    """loop.run_agent 와 같은 입력·출력. model 을 주지 않으면 get_llm() (ChatOpenAI)을 씁니다."""
    initial: AgentState = {
        "ctx": ctx,
        "max_steps": max_steps,
        "messages": [SystemMessage(content=SYSTEM_PROMPT),
                     HumanMessage(content=user_prompt(ctx.candidates, ctx.exit_due))],
        "step": 0,
        "steps": [],
    }
    out = graph.invoke(initial, config={"configurable": {"model": model, "journal": journal},
                                        "recursion_limit": 2 * max_steps + 4})
    return out.get("decisions", []), out.get("invalid", []), out["steps"]
