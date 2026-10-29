"""
명령어
──────────────────────────────────────────────────────────────
  python -m trader data [--refresh]                 시세 받기
  python -m trader test P-001 [P-002 ...]           ① 원칙 검정 → 리포트, 통과 여부 등록
  python -m trader status                           원칙별 상태
  python -m trader backtest [옵션]                  ②~⑤ 판단·가드레일·주문·기록을 과거 기간에 실행
  python -m trader compare RUN_ID [RUN_ID ...]      백테스트 결과·극단적 주문·가드레일 발동 비교
  python -m trader agree RUN_ID [--n 20]            직접 구현 루프 vs LangGraph 판단 일치율
  python -m trader paper [옵션]                     모의투자: 최신 데이터로 하루 실행
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):  # 아나콘다 base 등 다른 파이썬으로 실행했을 때
    sys.exit(f"Python {sys.version.split()[0]} 으로 실행됐습니다. 프로젝트 가상환경으로 실행하세요:\n"
             "  .venv\\Scripts\\python -m trader ...   (또는 .venv\\Scripts\\activate 후 python -m trader ...)")

import argparse
import json
import warnings

import pandas as pd

from trader.config import ROOT, load_config
from trader.journal import Journal
from trader.principles import load_all, load_principle

warnings.filterwarnings("ignore", category=FutureWarning)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


# ──────────────────────────────────────────────────────────────
# ① 원칙 검정
# ──────────────────────────────────────────────────────────────
def cmd_data(cfg, args):
    from trader.data import load_market

    stocks, bench = load_market(cfg, refresh=args.refresh)
    for t, df in stocks.items():
        print(f"{t:<10} {cfg['market']['universe'][t]:<12} {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}일)")
    print(f"벤치마크 {cfg['market']['benchmark']}: ~ {bench.index[-1].date()}")


def cmd_test(cfg, args):
    from trader.data import load_market
    from trader.stats_test import run_test, write_report

    stocks, bench = load_market(cfg)
    journal = Journal()
    for pid in args.ids:
        p = load_principle(pid)
        r = run_test(cfg, stocks, bench, p)
        trial_no = journal.count_tests(pid) + 1
        path = write_report(cfg, r, trial_no)
        tid = journal.record_test(
            principle_id=pid, params=json.dumps(p.describe(), ensure_ascii=False), n_events=r.n,
            mean_excess=r.mean, ci_low=r.ci[0], ci_high=r.ci[1], p_value=r.p, random_percentile=r.random_pct,
            validate_n=r.v_n, validate_mean=r.v_mean, validate_p=r.v_p,
            verdict="passed" if r.passed else "rejected", reasons="\n".join(r.reasons), report_path=path)
        journal.set_status(pid, "passed" if r.passed else "rejected", tid)
        print(f"\n[{pid}] {p.name} → {'통과' if r.passed else '탈락'}  (test_id={tid}, {trial_no}번째 검정)")
        print("\n".join("  " + x for x in r.reasons))
        print(f"  리포트: {path}")


def cmd_status(cfg, args):
    journal = Journal()
    status = {r["principle_id"]: r for r in journal.query("SELECT * FROM principle_status")}
    for pid, p in load_all().items():
        s = status.get(pid)
        print(f"{pid}  {p.name:<20} {s['status'] if s else 'draft':<9} "
              f"{'test_id=' + str(s['test_id']) if s else '검정 전'}")


# ──────────────────────────────────────────────────────────────
# ②~⑤ 판단 → 가드레일 → 주문 → 기록
# ──────────────────────────────────────────────────────────────
def make_decider(cfg, agent: str, llm: str, journal: Journal):
    """(ctx) → (decisions, invalid, steps) 함수와 에이전트 이름을 돌려준다."""
    from trader.agent.llm import MockChatModel, MockLLM, OpenAIChat

    max_steps = cfg["agent"]["max_steps"]
    if agent == "loop":
        from trader.agent.loop import run_agent

        model = MockLLM() if llm == "mock" else OpenAIChat(cfg["agent"]["model"], cfg["agent"]["temperature"], journal)
        return (lambda ctx: run_agent(ctx, model, max_steps)), f"loop/{model.name}"

    from trader.agent.graph import run_agent_graph
    from trader.agent.llm import get_llm

    if llm == "mock":
        model = MockChatModel()
    else:
        load_config()  # .env 로드
        model = get_llm()
    return (lambda ctx: run_agent_graph(ctx, model, journal, max_steps)), f"graph/{llm}"


def select_principles(journal: Journal, ids: list[str] | None, untested: bool):
    """검정을 통과한 원칙만 쓴다. --untested 는 실험용으로 이 규칙을 끄고 그 사실을 기록한다."""
    passed = journal.passed_principles()
    ids = ids or list(passed)
    blocked = [pid for pid in ids if pid not in passed]
    if blocked and not untested:
        sys.exit(f"검정을 통과하지 않은 원칙: {blocked}. 먼저 `python -m trader test {' '.join(blocked)}` "
                 f"(실험 목적이면 --untested)")
    if not ids:
        sys.exit("사용할 원칙이 없습니다. `python -m trader test P-001` 로 먼저 검정하세요.")
    return {pid: load_principle(pid) for pid in ids}, {pid: passed.get(pid) for pid in ids}


def cmd_backtest(cfg, args):
    from trader.agent.llm import USAGE
    from trader.data import load_market
    from trader.engine import Engine

    journal = Journal()
    principles, test_ids = select_principles(journal, args.principles, args.untested)
    decide, agent_name = make_decider(cfg, args.agent, args.llm, journal)
    stocks, bench = load_market(cfg)
    enforce = args.guardrails == "on"
    params = {"principles": list(principles), "untested": args.untested, "start": args.start, "end": args.end,
              "agent": agent_name, "guardrails": args.guardrails, "guardrail_values": cfg["guardrails"]}
    run_id = journal.new_run("backtest", args.label or f"{agent_name} guardrails={args.guardrails}", params)
    engine = Engine(cfg, stocks, bench, principles, test_ids, decide, agent_name, journal, run_id, enforce)

    dates = bench.loc[args.start:args.end].index
    print(f"run {run_id}: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)}일), 원칙 {list(principles)}, "
          f"에이전트 {agent_name}, 가드레일 {args.guardrails}")
    for i, d in enumerate(dates):
        engine.step(d)
        if (i + 1) % 100 == 0:
            print(f"  … {d.date()}")
    print_runs(cfg, journal, [run_id], bench)
    if args.llm == "openai":
        print(USAGE.summary(cfg["agent"]["model"]))
        journal.record_usage(run_id, USAGE, cfg["agent"]["model"])


def print_runs(cfg, journal, run_ids, bench=None):
    from trader.metrics import run_metrics

    for rid in run_ids:
        m = run_metrics(journal.db, rid, cfg["guardrails"]["max_position_weight"], bench)
        print(f"\n── run {rid}: {m['label']}")
        line = f"  수익률 {m['return']:+.2%}"
        if "bench" in m:
            line += f" (코스피 {m['bench']:+.2%})"
        print(line + f", 최대낙폭 {m['mdd']:.2%}, 최대 종목 비중 {m['max_weight']:.1%}")
        print(f"  판단 {m['decisions']}회, 체결 {m['orders']}건 (강제 손절 {m['forced']}), 극단적 주문 {m['extreme']}건")
        print("  가드레일 판정: " + (", ".join(f"{k} {v}" for k, v in m["rules"].items()) or "없음"))


def cmd_compare(cfg, args):
    from trader.data import load_market

    _, bench = load_market(cfg)
    journal = Journal()
    print_runs(cfg, journal, args.run_ids, bench)
    for rid in args.run_ids:
        enforced = journal.query("""SELECT MAX(c.enforced) FROM guardrail_checks c JOIN decisions d USING (decision_id)
                                    WHERE d.run_id=?""", rid)[0][0]
        if enforced == 0:  # 가드레일을 끈 실행: 같은 판단을 가드레일이 걸렀다면? (오프라인 필터)
            n = journal.query("""SELECT COUNT(DISTINCT c.decision_id || '-' || c.item) FROM guardrail_checks c
                                 JOIN decisions d USING (decision_id) WHERE d.run_id=? AND c.verdict IN ('CLIP','REJECT')""",
                              rid)[0][0]
            print(f"\n  run {rid}은 가드레일을 끈 실행: 같은 판단에 가드레일을 적용했다면 {n}건이 조정·거부됨 (오프라인 필터)")


def cmd_agree(cfg, args):
    """같은 입력(기록된 스냅샷)으로 직접 구현 루프와 LangGraph 버전의 판단을 비교한다."""
    from trader.agent.context import AgentContext

    journal = Journal()
    rows = journal.query("SELECT context FROM decisions WHERE run_id=? ORDER BY date LIMIT ?", args.run_id, args.n)
    if not rows:
        sys.exit(f"run {args.run_id}에 판단 기록이 없습니다")
    loop_fn, _ = make_decider(cfg, "loop", args.llm, journal)
    graph_fn, _ = make_decider(cfg, "graph", args.llm, journal)
    principles = load_all()
    same = 0
    for r in rows:
        ctx = AgentContext.from_log(json.loads(r["context"]), principles)
        key = lambda ds: sorted((d.stock, d.action) for d in ds[0])  # noqa: E731
        a, b = key(loop_fn(ctx)), key(graph_fn(ctx))
        same += a == b
        if a != b:
            print(f"  {ctx.date}: loop={a} / graph={b}")
    print(f"판단 일치율 {same}/{len(rows)} = {same / len(rows):.0%}")


# ──────────────────────────────────────────────────────────────
# 모의투자: 하루 한 번 (장 마감 후) 실행. 상태는 state/paper.json 에 남는다.
# ──────────────────────────────────────────────────────────────
def cmd_paper(cfg, args):
    from trader.data import load_market
    from trader.engine import Engine

    state_path = ROOT / "state" / "paper.json"
    state_path.parent.mkdir(exist_ok=True)
    saved = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None

    journal = Journal()
    principles, test_ids = select_principles(journal, args.principles, args.untested)
    decide, agent_name = make_decider(cfg, args.agent, args.llm, journal)
    stocks, bench = load_market(cfg, refresh=True)
    run_id = saved["run_id"] if saved else journal.new_run("paper", f"paper {agent_name}", {"principles": list(principles)})
    engine = Engine(cfg, stocks, bench, principles, test_ids, decide, agent_name, journal, run_id, enforce=True)
    if saved:
        engine.load_state(saved["engine"])

    last = pd.Timestamp(saved["last_date"]) if saved else bench.index[-2]
    for d in bench.index[bench.index > last]:
        equity = engine.step(d)
        print(f"{d.date()}: 총자산 {equity:,.0f}원, 현금 {engine.cash:,.0f}원, 보유 {len(engine.positions)}종목, "
              f"내일 시가 주문 {len(engine.pending)}건")
        last = d
    state_path.write_text(json.dumps({"run_id": run_id, "last_date": str(last.date()), "engine": engine.state()},
                                     ensure_ascii=False, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────────────────────
# 토스증권 연결
#   toss check       조회만 (토큰·계좌·매수 가능 금액·보유 주식·현재가). 주문 없음
#   toss order-test  실계좌 1주 테스트 주문. ALLOW_LIVE_TRADING=yes + 화면에서 직접 확인 입력 필요
# ──────────────────────────────────────────────────────────────
def cmd_toss(cfg, args):
    from trader.toss import TossClient, TossError, mask

    client = TossClient()
    try:
        accounts = client.accounts()
    except TossError as e:
        hint = {"ip-not-allowed": "이 PC의 공인 IP를 토스증권 WTS 설정 > Open API > 허용 IP 관리에 등록하세요.",
                "access_denied": "허용 IP 미등록이거나 client_id/secret 이 틀렸습니다."}.get(e.code, "")
        sys.exit(f"토스 API 호출 실패: {e}\n{hint}")
    if not accounts:
        sys.exit("종합매매 계좌가 없습니다")
    acc = next((a for a in accounts if args.account is None or a["accountSeq"] == args.account), accounts[0])
    seq = acc["accountSeq"]

    if args.action == "check":
        print(f"✅ 토큰·허용 IP 정상 · 계좌 {len(accounts)}개")
        for a in accounts:
            print(f"   accountSeq={a['accountSeq']}  {mask(a['accountNo'])}  {a['accountType']}")
        krw, usd = client.buying_power(seq, "KRW"), client.buying_power(seq, "USD")
        print(f"✅ 매수 가능 금액 (accountSeq {seq}): {int(float(krw['cashBuyingPower'])):,}원 · "
              f"${float(usd['cashBuyingPower']):,.2f}")
        h = client.holdings(seq)
        mv = h["marketValue"]["amount"]
        print(f"✅ 보유 주식 {len(h['items'])}종목 · 평가금액 {int(float(mv['krw'])):,}원"
              + (f" + ${float(mv['usd']):,.2f}" if mv.get("usd") else ""))
        for it in h["items"]:
            print(f"   {it['symbol']} {it['name']}  {it['quantity']}주  평단 {it['averagePurchasePrice']}  현재가 {it['lastPrice']}")
        p = client.prices([args.symbol])[0]
        print(f"✅ 현재가 {p['symbol']}: {p['lastPrice']} {p['currency']} ({p.get('timestamp')})")
        return

    # order-test: 실제 돈이 움직인다. 코드가 대신 확인하지 않고 사람이 직접 입력해야 진행된다.
    from datetime import datetime

    from trader.broker import LiveBroker, round_to_tick

    broker = LiveBroker(client, seq)  # ALLOW_LIVE_TRADING=yes 가 아니면 여기서 멈춘다
    quote = client.prices([args.symbol])[0]
    last, cur = float(quote["lastPrice"]), quote["currency"]
    kr = args.symbol[:1].isdigit()
    price = None if args.market else (round_to_tick(args.price or last, args.side) if kr else round(args.price or last, 2))
    money = (lambda v: f"{v:,.0f}원") if cur == "KRW" else (lambda v: f"${v:,.2f}")
    coid = f"test-{datetime.now():%Y%m%d%H%M%S}-{args.symbol}-{args.side}"
    print(f"실계좌 주문: 계좌 {mask(acc['accountNo'])} · {args.symbol} {args.side} {args.qty}주 · "
          f"{'시장가' if price is None else '지정가 ' + money(price)} (현재가 {money(last)}) · clientOrderId {coid}")
    if not sys.stdin.isatty():
        sys.exit("확인 입력을 받을 수 없는 환경이라 주문하지 않습니다. 터미널에서 직접 실행하세요.")
    if input(f"진행하려면 종목코드 {args.symbol} 를 입력하세요: ").strip() != args.symbol:
        sys.exit("취소했습니다.")

    journal = Journal()
    run_id = journal.new_run("live", f"order-test {args.symbol} {args.side} {args.qty}", {"account": mask(acc["accountNo"])})
    oid = journal.log_order(run_id=run_id, decision_id=None, item=-1, client_order_id=coid,
                            date=datetime.now().strftime("%Y-%m-%d"), ticker=f"{args.symbol}.KS" if kr else args.symbol,
                            side=args.side,
                            qty=args.qty, requested_weight=None, final_weight=None, verdict="MANUAL",
                            source="MANUAL", status="SUBMITTED")
    order_id = broker.submit(args.symbol, args.side, args.qty, coid, price)
    print(f"주문 접수: orderId {order_id} → 체결 확인 중 ({args.wait}초)")
    o = broker.wait(order_id, timeout=args.wait)
    ex = o["execution"]
    print(f"상태 {o['status']} · 체결 {ex['filledQuantity']}주 · 평균 체결가 {ex['averageFilledPrice']} · "
          f"수수료 {ex['commission']} · 세금 {ex['tax']}")
    from trader.live import record_fill

    journal.update_order(oid, broker_order_id=order_id)
    record_fill(journal, oid, o)  # 실거래 루프와 같은 방식으로 체결가·수량·수수료·세금 기록
    if o["status"] not in LiveBroker.FINAL:
        print("아직 미체결입니다. 토스증권 앱에서 확인·취소할 수 있습니다.")


# ──────────────────────────────────────────────────────────────
# 실거래 루프 (trader/live.py)
#   live decide   장 마감 후: 계좌 동기화 → 판단 → 가드레일 → 다음 거래일 주문 대기열
#   live execute  다음 날 장중: 대기 주문을 토스에 시장가로 → 체결 확인
#   live status   Agent 장부·대기 주문·STOP 상태
# ──────────────────────────────────────────────────────────────
def cmd_live(cfg, args):
    from trader import live
    from trader.toss import TossClient, TossError, mask

    if args.untested and not args.dry_run:
        sys.exit("실거래에서는 검정을 통과한 원칙만 씁니다. --untested 는 --dry-run 에서만 허용됩니다.")
    if args.assume_cash and not args.dry_run:
        sys.exit("--assume-cash 는 --dry-run 에서만 씁니다.")
    journal = Journal()
    client = TossClient()
    try:
        accounts = client.accounts()
    except TossError as e:
        sys.exit(f"토스 API 호출 실패: {e}")
    acc = next((a for a in accounts if args.account is None or a["accountSeq"] == args.account), accounts[0])
    seq = acc["accountSeq"]
    state = live.load_state()

    if args.action == "status":
        pos, cash = live.ledger(journal, state.get("run_id"), cfg["execution"]["live_capital"])
        print(f"계좌 {mask(acc['accountNo'])} · 실행 run {state.get('run_id') or '(아직 없음)'} · 마지막 판단 {state.get('decided_for') or '—'}")
        print(f"Agent 현금 {cash:,.0f}원 (한도 {cfg['execution']['live_capital']:,}원) · "
              f"토스 매수 가능 {float(client.buying_power(seq, 'KRW')['cashBuyingPower']):,.0f}원")
        for t, p in pos.items():
            print(f"  {t} {cfg['market']['universe'].get(t, t)} {p['qty']}주 · 평단 {p['cost'] / p['qty']:,.0f}원 · {p['principle_id']} · {p['since']}~")
        for o in state.get("pending", []):
            print(f"  대기 주문 #{o['order_id']} {o['ticker']} {o['side']} {o['qty']}주")
        for o in state.get("open", []):
            print(f"  체결 확인 중 #{o['order_id']} {o['ticker']} {o['side']}")
        print("STOP 파일 있음 → 주문 중단 상태" if live.STOP.exists() else "STOP 파일 없음")
        return

    def do_execute():
        from trader.broker import LiveBroker

        broker = LiveBroker(client, seq)  # ALLOW_LIVE_TRADING=yes 가 아니면 여기서 멈춘다
        for m in live.execute(cfg, journal, client, broker, seq):
            print(m)

    def do_decide():
        from trader.agent.llm import USAGE
        from trader.data import load_market

        principles, test_ids = select_principles(journal, args.principles, args.untested)
        decide_fn, agent_name = make_decider(cfg, args.agent, args.llm, journal)
        stocks, bench = load_market(cfg, refresh=True)
        r = live.decide(cfg, journal, client, seq, stocks, bench, principles, test_ids, decide_fn, agent_name,
                        dry_run=args.dry_run, assume_cash=args.assume_cash)
        for m in r.get("msgs", []):
            print(m)
        if "skipped" in r:
            print(r["skipped"])
            return
        names = cfg["market"]["universe"]
        tag = "[dry-run · 주문 안 함] " if args.dry_run else ""
        print(f"{tag}run {r['run_id']} · {r['date']} 종가 판단 · Agent 총자산 {r['equity']:,.0f}원 "
              f"(현금 {r['cash']:,.0f}원, 토스 매수 가능 {r['buying_power']:,.0f}원) · 원칙 {list(principles)}")
        if not r["pending"]:
            print("다음 거래일 주문 없음")
        for o in r["pending"]:
            print(f"  {'미리 보기' if args.dry_run else '대기'} #{o['order_id']} {o['ticker']} {names.get(o['ticker'], '')} "
                  f"{o['side']} {o['qty']}주 ({o['principle_id']})")
        if not args.dry_run and r["pending"]:
            print("→ 다음 거래일 장중에 execute (auto 실행 중이면 자동)")
        if args.llm == "openai":
            print(USAGE.summary(cfg["agent"]["model"]))
            if not args.dry_run:
                journal.record_usage(r["run_id"], USAGE, cfg["agent"]["model"])

    if args.action == "execute":
        do_execute()
    elif args.action == "decide":
        do_decide()
    else:  # auto: 켜 두면 시간에 맞춰 decide·execute 를 알아서 부른다
        if args.dry_run:
            sys.exit("auto 는 실제 주문 루프입니다. 미리 보기는 `live decide --dry-run`")
        from trader.broker import LiveBroker

        LiveBroker(client, seq)  # 시작할 때 주문 스위치부터 확인
        live.auto(do_decide, do_execute)


def main():
    ap = argparse.ArgumentParser(prog="python -m trader")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("data")
    s.add_argument("--refresh", action="store_true")
    s = sub.add_parser("test")
    s.add_argument("ids", nargs="+")
    sub.add_parser("status")

    def agent_opts(s):
        s.add_argument("--principles", nargs="*", help="기본: 검정을 통과한 원칙 전부")
        s.add_argument("--untested", action="store_true", help="실험용: 검정을 통과하지 않은 원칙도 허용")
        s.add_argument("--agent", choices=["loop", "graph"], default="loop", help="loop=직접 구현, graph=LangGraph")
        s.add_argument("--llm", choices=["openai", "mock"], default="openai")

    s = sub.add_parser("backtest")
    agent_opts(s)
    s.add_argument("--start", default="2023-01-01")
    s.add_argument("--end", default=None)
    s.add_argument("--guardrails", choices=["on", "off"], default="on")
    s.add_argument("--label")
    s = sub.add_parser("compare")
    s.add_argument("run_ids", nargs="+", type=int)
    s = sub.add_parser("agree")
    s.add_argument("run_id", type=int)
    s.add_argument("--n", type=int, default=20)
    s.add_argument("--llm", choices=["openai", "mock"], default="openai")
    s = sub.add_parser("paper")
    agent_opts(s)
    s = sub.add_parser("toss", help="토스증권 연결: check(조회만) / order-test(실계좌 1주 테스트)")
    s.add_argument("action", choices=["check", "order-test"])
    s.add_argument("--account", type=int, help="accountSeq (기본: 첫 번째 종합매매 계좌)")
    s.add_argument("--symbol", default="005930")
    s.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    s.add_argument("--qty", type=int, default=1)
    s.add_argument("--price", type=float, help="지정가 (기본: 현재가를 호가 단위로 맞춤)")
    s.add_argument("--market", action="store_true", help="시장가 주문")
    s.add_argument("--wait", type=int, default=30, help="체결 확인 대기 초")
    s = sub.add_parser("live", help="실거래 루프: auto(켜 두면 알아서) / decide(장 마감 후) / execute(다음 날 장중) / status")
    s.add_argument("action", choices=["auto", "decide", "execute", "status"])
    agent_opts(s)
    s.add_argument("--account", type=int, help="accountSeq (기본: 첫 번째 종합매매 계좌)")
    s.add_argument("--dry-run", action="store_true", help="실계좌로 판단까지만 하고 주문 대기열에 넣지 않음")
    s.add_argument("--assume-cash", action="store_true", help="dry-run 에서 매수 가능 금액 대신 live_capital 을 현금으로 가정")

    args = ap.parse_args()
    cfg = load_config()
    try:
        COMMANDS[args.cmd](cfg, args)
    except RuntimeError as e:  # 키 없음, 데이터 없음 등 사용자가 고칠 수 있는 문제
        sys.exit(f"오류: {e}")


COMMANDS = {"data": cmd_data, "test": cmd_test, "status": cmd_status, "backtest": cmd_backtest,
            "compare": cmd_compare, "agree": cmd_agree, "paper": cmd_paper, "toss": cmd_toss, "live": cmd_live}


if __name__ == "__main__":
    main()
