"""
모니터링 API — journal.db 를 읽기 전용으로 열어 화면에 필요한 모양으로 돌려준다
──────────────────────────────────────────────────────────────
  GET /api/runs                    실행 목록
  GET /api/runs/{id}/summary       핵심 지표 (총자산, 수익률, 낙폭, 현금, 극단적 주문, 판정 수, GPT 사용량)
  GET /api/runs/{id}/equity        자산·코스피 누적 수익률과 낙폭 (일별)
  GET /api/runs/{id}/holdings      마지막 날 보유 종목 (체결 기록으로 재구성)
  GET /api/runs/{id}/decisions     판단 목록 (항목별 최종 판정)
  GET /api/runs/{id}/rules         규칙별 통과·조정·거부 수
  GET /api/decisions/{id}          판단 하나의 전체 추적 (입력 → 도구 → 제안 → 가드레일 → 주문)
  GET /api/principles              원칙과 최근 검정 결과
  GET /api/experiments             가드레일 끔/켬 짝 비교
쓰기 API는 없다. 모니터링 화면은 주문을 낼 수 없다.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from trader.config import ROOT, load_config
from trader.metrics import bench_on, equity_frame, rule_counts, run_metrics
from trader.principles import load_all

DB_PATH = Path(os.getenv("JOURNAL_DB", ROOT / "journal.db"))
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
STATIC_DIR = Path(os.getenv("STATIC_DIR", Path(__file__).parent / "static"))

app = FastAPI(title="Agent Monitor API")
CFG = load_config()
NAMES: dict[str, str] = CFG["market"]["universe"]
MAX_W = CFG["guardrails"]["max_position_weight"]


@contextmanager
def connect():
    if not DB_PATH.exists():
        raise HTTPException(503, f"기록 DB가 없습니다: {DB_PATH.name}. 먼저 백테스트를 실행하세요.")
    db = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def price_frame(ticker: str) -> pd.DataFrame:
    path = DATA_DIR / f"{ticker.replace('^', 'IDX_')}.csv"
    return pd.read_csv(path, index_col="date", parse_dates=True) if path.exists() else pd.DataFrame()


def bench() -> pd.DataFrame:
    return price_frame(CFG["market"]["benchmark"])


def get_run(db, run_id: int) -> dict:
    row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"run {run_id} 없음")
    r = dict(row)
    r["params"] = json.loads(r["params"] or "{}")
    return r


def code(ticker: str | None) -> str:
    return (ticker or "").split(".")[0]


def item_verdicts(db, decision_id: int) -> dict[int, str]:
    """판단 항목별 최종 판정: 거부가 하나라도 있으면 REJECT, 조정이 있으면 CLIP, HOLD, 나머지 PASS"""
    out: dict[int, set] = {}
    for r in db.execute("SELECT item, verdict FROM guardrail_checks WHERE decision_id=?", (decision_id,)):
        out.setdefault(r["item"], set()).add(r["verdict"])
    order = ["REJECT", "CLIP", "HOLD", "PASS"]
    return {i: next(v for v in order if v in vs) for i, vs in out.items()}


# ──────────────────────────────────────────────────────────────
# 실행 목록·요약
# ──────────────────────────────────────────────────────────────
@app.get("/api/runs")
def runs():
    with connect() as db:
        rows = db.execute("""SELECT r.run_id, r.created_at, r.mode, r.label, r.params,
                                    MIN(e.date) start, MAX(e.date) end, COUNT(e.date) days
                             FROM runs r LEFT JOIN daily_equity e USING (run_id)
                             GROUP BY r.run_id ORDER BY r.run_id DESC""").fetchall()
    out = []
    for r in rows:
        p = json.loads(r["params"] or "{}")
        out.append({"run_id": r["run_id"], "label": r["label"], "mode": r["mode"], "created_at": r["created_at"],
                    "start": r["start"], "end": r["end"], "days": r["days"], "agent": p.get("agent"),
                    "guardrails": p.get("guardrails", "on"), "principles": p.get("principles", []),
                    "untested": p.get("untested", False)})
    return out


@app.get("/api/runs/{run_id}/summary")
def summary(run_id: int):
    with connect() as db:
        run = get_run(db, run_id)
        eq = equity_frame(db, run_id)
        if eq.empty:
            raise HTTPException(404, "아직 기록된 날이 없습니다")
        m = run_metrics(db, run_id, MAX_W, bench())
        counts = {"PASS": 0, "CLIP": 0, "REJECT": 0, "HOLD": 0}
        n_items = 0
        for d in db.execute("SELECT decision_id FROM decisions WHERE run_id=?", (run_id,)).fetchall():
            for v in item_verdicts(db, d["decision_id"]).values():
                counts[v] += 1
                n_items += 1
        usage = db.execute("SELECT * FROM run_usage WHERE run_id=?", (run_id,)).fetchone()
        last_decision = db.execute("SELECT MAX(date) FROM decisions WHERE run_id=?", (run_id,)).fetchone()[0]
        status = {r["principle_id"]: r["status"] for r in db.execute("SELECT * FROM principle_status")}
    last = eq.iloc[-1]
    p = run["params"]
    principles = load_all()
    return {
        "run": {"run_id": run_id, "label": run["label"], "mode": run["mode"], "agent": p.get("agent"),
                "guardrails": p.get("guardrails", "on"), "untested": p.get("untested", False),
                "start": m["start"], "end": m["end"]},
        "as_of": m["end"], "last_decision": last_decision,
        "equity": float(last["equity"]), "start_equity": float(eq["equity"].iloc[0]),
        "return": m["return"], "bench_return": m.get("bench"), "mdd": m["mdd"],
        "cash_weight": float(last["cash"] / last["equity"]), "min_cash_weight": CFG["guardrails"]["min_cash_weight"],
        "extreme": m["extreme"], "decisions": m["decisions"], "orders": m["orders"], "forced": m["forced"],
        "verdicts": counts, "items": n_items,
        "usage": dict(usage) if usage else None,
        "principles": [{"id": pid, "name": principles[pid].name if pid in principles else pid,
                        "status": status.get(pid, "draft")} for pid in p.get("principles", [])],
    }


@app.get("/api/runs/{run_id}/equity")
def equity(run_id: int):
    with connect() as db:
        eq = equity_frame(db, run_id)
    if eq.empty:
        return []
    bm = bench()
    b = bench_on(bm, eq.index) if not bm.empty else None
    e = eq["equity"]
    out = pd.DataFrame({
        "agent": (e / e.iloc[0] - 1) * 100,
        "kospi": (b / b.iloc[0] - 1) * 100 if b is not None else None,
        "dd": (e / e.cummax() - 1) * 100,
        "cash": eq["cash"] / e * 100,
        "max_weight": eq["max_weight"] * 100,
    })
    return [{"date": d.strftime("%Y-%m-%d"), **{k: (None if pd.isna(v) else round(float(v), 3)) for k, v in r.items()}}
            for d, r in out.iterrows()]


@app.get("/api/runs/{run_id}/holdings")
def holdings(run_id: int):
    """체결 기록을 순서대로 다시 쌓아 마지막 날 보유 종목을 만든다."""
    with connect() as db:
        eq = equity_frame(db, run_id)
        fills = db.execute("""SELECT o.*, d.output FROM orders o LEFT JOIN decisions d USING (decision_id)
                              WHERE o.run_id=? AND o.status='FILLED' ORDER BY o.fill_date, o.order_id""",
                           (run_id,)).fetchall()
        ctx = db.execute("SELECT context FROM decisions WHERE run_id=? LIMIT 1", (run_id,)).fetchone()
    if eq.empty:
        return {"as_of": None, "items": []}
    aliases = json.loads(ctx["context"])["aliases"] if ctx else {}
    pos: dict[str, dict] = {}
    for f in fills:
        t = f["ticker"]
        if f["side"] == "SELL":
            pos.pop(t, None)
            continue
        pid = ""
        if f["output"] and f["item"] is not None and f["item"] >= 0:
            items = json.loads(f["output"])
            if f["item"] < len(items):
                pid = items[f["item"]].get("principle_id", "")
        p = pos.setdefault(t, {"qty": 0, "cost": 0.0, "since": f["fill_date"], "principle_id": pid})
        p["qty"] += f["fill_qty"]
        p["cost"] += f["fill_qty"] * f["fill_price"]

    as_of = eq.index[-1]
    equity_v = float(eq["equity"].iloc[-1])
    cal = bench().index
    g = CFG["guardrails"]
    principles = load_all()
    items = []
    for t, p in pos.items():
        px = price_frame(t)["close"].loc[:as_of]
        close = float(px.iloc[-1]) if len(px) else float("nan")
        avg = p["cost"] / p["qty"]
        held = int(((cal >= pd.Timestamp(p["since"])) & (cal <= as_of)).sum())
        horizon = principles[p["principle_id"]].horizon_days if p["principle_id"] in principles else None
        pnl = close / avg - 1
        items.append({
            "ticker": t, "code": code(t), "name": NAMES.get(t, t), "alias": aliases.get(t),
            "principle_id": p["principle_id"], "qty": p["qty"], "avg_cost": avg, "close": close,
            "weight": p["qty"] * close / equity_v, "pnl": pnl, "held_days": held, "horizon_days": horizon,
            "exit_due": bool(horizon and held >= horizon), "below_stop": pnl <= g["stop_loss"],
        })
    items.sort(key=lambda x: -x["weight"])
    return {"as_of": as_of.strftime("%Y-%m-%d"), "max_order_weight": g["max_order_weight"],
            "max_position_weight": g["max_position_weight"], "stop_loss": g["stop_loss"], "items": items}


# ──────────────────────────────────────────────────────────────
# 판단 기록
# ──────────────────────────────────────────────────────────────
@app.get("/api/runs/{run_id}/decisions")
def decisions(run_id: int, limit: int = 200):
    with connect() as db:
        rows = db.execute("SELECT decision_id, date, output, context FROM decisions WHERE run_id=? "
                          "ORDER BY date DESC, decision_id DESC LIMIT ?", (run_id, limit)).fetchall()
        out = []
        for r in rows:
            ctx = json.loads(r["context"])
            inv = {a: t for t, a in ctx["aliases"].items()}
            verdicts = item_verdicts(db, r["decision_id"])
            orders = {o["item"]: dict(o) for o in db.execute(
                "SELECT item, status, fill_qty, final_weight FROM orders WHERE decision_id=?", (r["decision_id"],))}
            items, n_invalid = [], 0
            for i, o in enumerate(json.loads(r["output"])):
                if "error" in o:
                    n_invalid += 1
                    raw = o.get("raw") or {}
                    t = inv.get(raw.get("stock")) if isinstance(raw, dict) else None
                    items.append({"side": raw.get("action") if isinstance(raw, dict) else None, "ticker": t,
                                  "name": NAMES.get(t, "형식 오류"), "weight": None, "verdict": "REJECT",
                                  "rule": "G01", "note": o["error"], "filled": False})
                    continue
                t = inv.get(o["stock"])
                order = orders.get(i)
                items.append({"side": o["action"], "ticker": t, "name": NAMES.get(t, o["stock"]),
                              "weight": o["target_weight"], "verdict": verdicts.get(i, "PASS"),
                              "note": o.get("reason", ""), "filled": bool(order and order["status"] == "FILLED"),
                              "final_weight": order["final_weight"] if order else None})
            out.append({"decision_id": r["decision_id"], "date": r["date"], "items": items, "invalid": n_invalid})
    return out


@app.get("/api/runs/{run_id}/rules")
def rules(run_id: int):
    with connect() as db:
        rows = rule_counts(db, run_id, ("PASS", "CLIP", "REJECT"))
    by: dict[str, dict] = {}
    for r in rows:
        rule = "G06" if r["rule"] == "G06-08" else r["rule"]
        by.setdefault(rule, {"PASS": 0, "CLIP": 0, "REJECT": 0})[r["verdict"]] += r["n"]
        if r["rule"] == "G06-08":  # 한도 이내 통과는 G06·G07·G08 모두 통과한 것
            for extra in ("G07", "G08"):
                by.setdefault(extra, {"PASS": 0, "CLIP": 0, "REJECT": 0})["PASS"] += r["n"]
    names = {"G01": "형식", "G02": "검정 통과 원칙", "G03": "조건 재계산", "G04": "보유 내 매도", "G05": "당일 중복",
             "G06": "1회 주문 한도", "G07": "종목 비중 상한", "G08": "최소 현금", "G09": "일 주문 건수",
             "G10": "일 손실 한도"}
    return [{"rule": k, "name": v, **by.get(k, {"PASS": 0, "CLIP": 0, "REJECT": 0})} for k, v in names.items()]


@app.get("/api/decisions/{decision_id}")
def decision(decision_id: int):
    with connect() as db:
        d = db.execute("SELECT * FROM decisions WHERE decision_id=?", (decision_id,)).fetchone()
        if d is None:
            raise HTTPException(404, f"판단 {decision_id} 없음")
        checks = [dict(c) for c in db.execute("SELECT * FROM guardrail_checks WHERE decision_id=? ORDER BY id",
                                              (decision_id,))]
        orders = [dict(o) for o in db.execute("SELECT * FROM orders WHERE decision_id=? ORDER BY order_id",
                                              (decision_id,))]
        run = get_run(db, d["run_id"])
        test_ids = json.loads(d["principle_test_ids"] or "{}")
        tests = {r["test_id"]: dict(r) for r in db.execute("SELECT test_id, principle_id, verdict FROM principle_tests")}
    ctx = json.loads(d["context"])
    inv = {a: t for t, a in ctx["aliases"].items()}
    real = lambda alias: {"alias": alias, "ticker": inv.get(alias), "name": NAMES.get(inv.get(alias), alias)}  # noqa: E731
    items = []
    for i, o in enumerate(json.loads(d["output"])):
        if "error" in o:
            items.append({"index": i, "invalid": True, "error": o["error"], "raw": o.get("raw")})
            continue
        t = inv.get(o["stock"])
        items.append({"index": i, "invalid": False, **o, **real(o["stock"]), "code": code(t),
                      "checks": [c for c in checks if c["item"] == i],
                      "order": next((x for x in orders if x["item"] == i), None)})
    return {
        "decision_id": decision_id, "date": d["date"], "agent": d["agent"], "model": d["model"],
        "prompt_version": d["prompt_version"], "run": {"run_id": run["run_id"], "label": run["label"],
                                                       "guardrails": run["params"].get("guardrails", "on")},
        "input": {"candidates": [{**c, **real(c["stock"])} for c in ctx["candidates"]],
                  "exit_due": [{**c, **real(c["stock"])} for c in ctx["exit_due"]],
                  "cash_weight": ctx["cash_weight"], "equity": ctx["equity"], "n_holdings": len(ctx["holdings"]),
                  "shown": {c["stock"]: ctx["shown"].get(c["stock"], {}) for c in ctx["candidates"] + ctx["exit_due"]}},
        "steps": json.loads(d["steps"]),
        "items": items,
        "invalid_checks": [c for c in checks if c["item"] < 0],
        "forced": [o for o in orders if o["source"] == "F01"],
        "trace": [{"principle_id": pid, "test_id": tid, "verdict": tests.get(tid, {}).get("verdict")}
                  for pid, tid in test_ids.items()],
    }


# ──────────────────────────────────────────────────────────────
# 원칙·검정
# ──────────────────────────────────────────────────────────────
def parse_yearly(report_path: str | None) -> list[dict]:
    if not report_path:
        return []
    path = ROOT / report_path.replace("\\", "/")
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    block = text.split("## 연도별", 1)[-1].split("##", 1)[0] if "## 연도별" in text else ""
    return [{"year": int(y), "n": int(n), "mean": float(m) / 100}
            for y, n, m in re.findall(r"\|\s*(\d{4})\s*\|\s*(\d+)\s*\|\s*([+-]?[\d.]+)%", block)]


@app.get("/api/principles")
def principles():
    with connect() as db:
        tests = [dict(r) for r in db.execute("SELECT * FROM principle_tests ORDER BY test_id")]
        status = {r["principle_id"]: dict(r) for r in db.execute("SELECT * FROM principle_status")}
    out = []
    for pid, p in load_all().items():
        mine = [t for t in tests if t["principle_id"] == pid]
        latest = mine[-1] if mine else None
        if latest:
            latest = {**latest, "reasons": [{"ok": line.startswith("✅"), "text": line[2:]}
                                            for line in (latest["reasons"] or "").splitlines() if line],
                      "yearly": parse_yearly(latest["report_path"])}
        out.append({**p.describe(), "status": status.get(pid, {}).get("status", "draft"),
                    "trials": len(mine), "latest": latest})
    return {"criteria": CFG["test"], "costs": CFG["costs"], "principles": out}


# ──────────────────────────────────────────────────────────────
# 가드레일 실험: 같은 조건에서 가드레일만 다른 실행끼리 짝을 짓는다
# ──────────────────────────────────────────────────────────────
@app.get("/api/experiments")
def experiments():
    b = bench()
    with connect() as db:
        rows = [get_run(db, r["run_id"]) for r in db.execute("SELECT run_id FROM runs WHERE mode='backtest'")]
        groups: dict[str, dict] = {}
        for r in rows:
            p = r["params"]
            key = json.dumps([p.get("principles"), p.get("start"), p.get("end"), p.get("agent")])
            groups.setdefault(key, {})[p.get("guardrails", "on")] = r  # 같은 조건이면 최신 실행이 남는다
        out = []
        for key, pair in groups.items():
            if "on" not in pair or "off" not in pair:
                continue
            off, on = pair["off"]["run_id"], pair["on"]["run_id"]
            m_off, m_on = run_metrics(db, off, MAX_W, b), run_metrics(db, on, MAX_W, b)
            offline = db.execute("""SELECT COUNT(DISTINCT c.decision_id || '-' || c.item) FROM guardrail_checks c
                                    JOIN decisions d USING (decision_id)
                                    WHERE d.run_id=? AND c.verdict IN ('CLIP','REJECT')""", (off,)).fetchone()[0]
            buys = db.execute("SELECT requested_weight FROM orders WHERE run_id=? AND side='BUY' AND source='AGENT'",
                              (off,)).fetchall()
            req = [x[0] for x in buys]
            usage = {r["run_id"]: dict(r) for r in db.execute("SELECT * FROM run_usage WHERE run_id IN (?, ?)", (off, on))}
            out.append({
                "agent": pair["on"]["params"].get("agent"), "principles": pair["on"]["params"].get("principles"),
                "untested": pair["on"]["params"].get("untested", False),
                "off": {"run_id": off, **m_off, "usage": usage.get(off)},
                "on": {"run_id": on, **m_on, "usage": usage.get(on),
                       "rule_bars": rule_counts(db, on)},
                "offline_filter": offline,
                "buy_requests": {"n": len(req), "max": max(req) if req else None,
                                 "within_order_limit": sum(1 for w in req if w <= CFG["guardrails"]["max_order_weight"] + 1e-9)},
            })
    out.sort(key=lambda x: -x["on"]["run_id"])
    return {"max_position_weight": MAX_W, "experiments": out}


# ──────────────────────────────────────────────────────────────
# 빌드된 Vue 화면 (있을 때만). /api 가 아닌 경로는 전부 index.html 로
# ──────────────────────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC_DIR / path
        return FileResponse(f if path and f.is_file() else STATIC_DIR / "index.html")
