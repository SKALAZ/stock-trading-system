# 원칙 검정형 자동매매 Agent (MVP)

내 투자 원칙을 과거 데이터로 통계 검정하고, 통과한 원칙대로 GPT가 매수·매도를 판단한다.
GPT의 판단은 살리되, 원칙을 벗어난 주문은 주문 직전 가드레일이 막는다.

```
[원칙 YAML] → ① 검정 ─(통과)→ 사용 가능 원칙
                                  │
시세·지표 → 후보 스크리닝(코드) → ② GPT 판단 루프 → 주문 제안(JSON)
                                                        │
                                          ③ 가드레일 → PASS / CLIP / REJECT
                                                        │
                                          ④ 주문 (다음 날 시가) → ⑤ 기록 (journal.db)
```

- **GPT에게는 주문 권한이 없다.** 읽기 전용 도구로 정보를 보고 '제안'만 낸다. 주문은 가드레일을 통과한 뒤 코드가 낸다.
- **검정을 통과한 원칙만 쓴다.** 인용한 원칙이 통과 상태가 아니면 거부(G02).
- **검정 조건 = 운영 조건.** 진입 시점(다음 날 시가), 거래비용, 1회 매수 비중(5%)을 검정과 백테스트가 같은 값으로 쓴다.
- **모든 주문은 거슬러 올라갈 수 있다.** 주문 → GPT 판단(입력·도구 호출·출력) → 가드레일 판정 → 원칙 검정 리포트.

## 시작

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # OPENAI_API_KEY 입력
```

`.env` 변수: `OPENAI_API_KEY`, `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`, `TOSS_ACCESS_TOKEN`, `ALLOW_LIVE_TRADING`(기본 `no`).
변수 이름에 띄어쓰기가 있으면 읽히지 않는다.

## 명령어

```bash
python -m trader data                         # 시세 받기 (data/에 캐시)
python -m trader test P-001 P-002             # ① 원칙 검정 → reports/에 리포트, 통과 여부 등록
python -m trader status                       # 원칙별 상태
python -m trader backtest                     # 통과한 원칙으로 2023-01-01~ 백테스트 (GPT, 가드레일 on)
python -m trader backtest --guardrails off    # 같은 기간, 가드레일 끄고 (판정은 기록만)
python -m trader compare 1 2                  # 수익률·최대낙폭·극단적 주문·규칙별 발동 비교
python -m trader agree 1 --n 20               # 직접 구현 루프 vs LangGraph 판단 일치율
python -m trader paper                        # 모의투자: 최신 데이터로 하루 실행 (장 마감 후)
python -m pytest -q                           # 테스트
```

공통 옵션: `--agent loop|graph` (직접 구현 / LangGraph), `--llm openai|mock`, `--principles P-002`,
`--untested` (실험용으로 검정 미통과 원칙 허용 — 실행 기록에 남는다).

`--llm mock`은 GPT가 아니다. API 키 없이 흐름을 확인하려고 만든 가짜 모델로,
관찰된 이탈 유형(한 종목에 30%를 싣는 과대 비중)을 일부러 흉내 낸다.

## 모니터링 화면 (Vue + FastAPI, Docker)

```bash
docker compose up --build        # → http://localhost:8000
```

내 PC에 Node.js가 없어도 된다. Vue 빌드는 컨테이너 안에서 한다. 화면은 `journal.db`를 **읽기 전용**으로 열고, 쓰기·주문 API는 없다.
`.env`는 이미지에도 컨테이너에도 들어가지 않는다 (`.dockerignore`, `docker-compose.yml`).

| 화면 | 답하는 질문 |
|---|---|
| 대시보드 | 지금 어떻게 돌아가나 — 총자산·수익률·낙폭·현금, 극단적 주문, 판정 수, 자산 추이, 보유 종목, 최근 판단, 규칙별 판정 |
| 판단 추적 | 이 주문은 왜 나갔나 — GPT 입력 → 도구 호출 → 제안 → 가드레일 → 주문·체결, 검정 리포트까지 역추적 |
| 원칙·검정 | 어떤 원칙을 쓸 수 있나 — 원칙별 통과/탈락, 이벤트·초과수익·신뢰구간·p값, 통과 기준, 연도별 |
| 가드레일 실험 | 가드레일이 정말 막는가 — 같은 조건 off/on 실행을 자동으로 짝지어 비교 |

화면 코드를 고칠 때는 `docker compose --profile dev up` → http://localhost:5173 (저장하면 바로 반영).
Node.js를 설치했다면 `cd monitor/web && npm install && npm run dev`도 된다 (API는 8000번에 떠 있어야 함).

## 토스증권 연결

```bash
python -m trader toss check                       # 조회만: 토큰·허용 IP·계좌·매수 가능 금액·보유 주식·현재가
python -m trader toss order-test --symbol 005930  # 실계좌 1주 지정가 테스트 (현재가를 호가 단위로 맞춤)
python -m trader toss order-test --symbol AAPL --market   # 미국 주식 1주 시장가
```

`order-test`는 실제 돈이 움직인다. 세 겹으로 막아 두었다.
1. `.env`의 `ALLOW_LIVE_TRADING=yes`가 아니면 실행되지 않는다 (기본 `no`).
2. 터미널에서 종목코드를 직접 다시 입력해야 주문이 나간다. 입력을 받을 수 없는 환경(스크립트·자동화)에서는 주문하지 않는다.
3. 1억 원 이상 주문은 토스가 거부하도록 `confirmHighValueOrder`를 보내지 않는다.

주문마다 `clientOrderId`(멱등성 키)를 붙여 재시도해도 두 번 들어가지 않고, 체결은 주문 상세 조회로 확인해 `journal.db`에 남긴다 (모니터링 화면의 run 목록에 `live`로 보임).
토큰은 client 당 1개만 유효하다. 새로 발급하면 이전 토큰은 무효가 되며, 발급한 토큰은 `state/toss_token.json`에 캐시한다 (`.env`는 건드리지 않음).

## 실거래 루프

백테스트와 같은 규칙(종가로 판단 → 다음 거래일에 체결)을 실계좌에서 하루 두 번 돌린다.

```bash
python -m trader live auto       # 켜 두면 알아서: 시작 시 판단 1회 → 평일 15:45 이후 판단 → 다음 날 장중 주문 (Ctrl+C로 종료)
python -m trader live decide     # 장 마감 후(15:40~): 토스 계좌 동기화 → GPT 판단 → 가드레일 → 다음 거래일 주문 대기열
python -m trader live execute    # 다음 거래일 장중(09:00~15:20): 대기 주문을 토스에 시장가로 → 체결 확인 → 기록
python -m trader live status     # Agent 장부(현금·포지션)·대기 주문·STOP 상태
python -m trader live decide --dry-run   # 실계좌로 판단까지만, 주문 대기열에 넣지 않음 (--untested --assume-cash 가능)
```

- **Agent 몫만 굴린다.** `config.yaml`의 `live_capital`(기본 100만 원)이 상한이다. 장부는 이 실행의 체결 기록으로 다시 쌓고(현금 = 한도 + 매도 대금 − 매수 대금), 토스 실제 매수 가능 금액·보유 수량으로 한 번 더 자른다. 계좌의 다른 종목이나 직접 산 주식은 건드리지 않는다.
- **검정을 통과한 원칙만.** `--untested`는 `--dry-run`에서만 된다. 가드레일은 끌 수 없다.
- **멈추기:** `state/STOP` 파일을 만들면 `execute`가 주문을 하나도 내지 않는다. 지우면 재개.
- 매도를 먼저 내 현금을 확보한 뒤 매수한다. 매수 수량은 체결 직전 매수 가능 금액 안으로 줄인다. 장 시간이 아니면(`order-hours-closed`) 주문을 대기열에 남겨 둔다. 60초 안에 체결이 안 끝난 주문은 다음 실행 때 다시 조회해 기록을 맞춘다.
- 모니터링 화면 run 목록에 `LIVE`(실거래)·`LIVE-DRY`(미리 보기)로 나온다.

## 새 가설 시험하기

1. `principles/P-003.yaml` 작성 (P-001 형식, 조건식에는 `smaN`, `rsiN`, `vol_ratioN`, `retN`, `close` 등 사용)
2. `python -m trader test P-003` → 리포트 확인
3. 통과하면 `python -m trader backtest`에 자동 포함

리포트에는 그 원칙을 몇 번째로 검정했는지가 찍힌다. 같은 원칙을 고쳐 가며 여러 번 시험할수록 우연히 통과할 확률이 커진다.

## ① 검정 방법 (`trader/stats_test.py`)

- 이벤트 스터디: 신호일 t 종가 판정 → t+1 시가 매수 → t+h 종가 매도. 초과수익 = 종목 − 코스피 − 왕복 비용
- 한 종목에서 신호가 연달아 나면 보유 기간 동안은 다시 세지 않는다
- 주 검정: 날짜 단위 블록 부트스트랩 (같은 날 신호끼리는 독립이 아니므로)
- 무작위 진입 기준선: 같은 종목·같은 구간에서 아무 날이나 샀을 때보다 상위 5%인가
- 검정 구간(~2022)에서 판정하고, 검증 구간(2023~)에서도 같은 방향인지 확인
- 통과 기준은 `config.yaml`의 `test:` (전부 충족해야 통과)

## ③ 가드레일 (`trader/guardrails.py`, 값은 `config.yaml`)

| 코드 | 규칙 | 위반 시 |
|---|---|---|
| G01 | 형식 (알 수 있는 종목, 비중 0~1) | REJECT |
| G02 | 인용 원칙이 검정 통과 상태 | REJECT |
| G03 | 인용 원칙 조건을 코드로 다시 계산해 충족 (매수) | REJECT |
| G04 | 보유하지 않은 종목 매도 금지 | REJECT |
| G05 | 같은 종목 당일 중복 주문 금지 | REJECT |
| G06 | 1회 주문 ≤ 총자산 5% | CLIP |
| G07 | 한 종목 비중 ≤ 10% | CLIP |
| G08 | 현금 비중 ≥ 10% | CLIP / REJECT |
| G09 | 하루 주문 ≤ 10건 | REJECT |
| G10 | 당일 -3%면 신규 매수 중단 (매도는 허용) | REJECT |
| F01 | 매수가 대비 -7%면 GPT와 무관하게 매도 | 강제 실행 |

가드레일을 끈 실행에서도 판정은 계산해 기록한다. 그래서 두 가지를 볼 수 있다.
- **오프라인 필터**: 가드레일 off 실행의 GPT 판단에 가드레일을 적용했다면 몇 건이 걸렸을까
- **폐루프 재백테스트**: 가드레일 on으로 같은 기간을 다시 돌린 결과 (막힌 뒤 포트폴리오가 달라져 이후 판단도 달라진다)

'극단적 주문' = 목표 비중이 종목 상한(10%)을 넘거나, 인용 조건이 실제로는 미충족인데 체결된 매수.

## ② 판단 루프: 직접 구현 → LangGraph

| 직접 구현 `agent/loop.py` | LangGraph `agent/graph.py`, `nodes.py`, `state.py` |
|---|---|
| `llm.complete(...)` | `decider` 노드 |
| `for c in msg["tool_calls"]` | `tools` 노드 |
| `parse_decisions(...)` | `parse` 노드 |
| for 루프가 끝까지 돈 경우 | `give_up` 노드 |
| `messages` 리스트 | `AgentState.messages` |

정보 누출 방지: 종목은 `STOCK_A`처럼 가리고, 날짜를 주지 않고, 가격 대신 정규화 지표(종가/이평 비율 등)만 준다.
GPT 응답은 `journal.db`의 `llm_cache`에 저장돼 같은 입력이면 다시 호출하지 않는다.

## ⑤ 기록 (`journal.db`)

`principle_tests`, `principle_status`, `runs`, `decisions`, `guardrail_checks`, `orders`, `daily_equity`, `llm_cache`

## 현재 상태와 한계

- 예시 원칙 P-001, P-002는 둘 다 **탈락**했다. P-001은 이 유니버스에서 조건이 한 번도 충족되지 않았고(60일선 위에서 RSI14 < 30),
  P-002는 비용 차감 후 평균 초과수익이 음수였다. 원칙은 직접 써서 넣어야 한다.
- 실계좌 주문(`broker.py`의 `LiveBroker`)은 아직 구현하지 않았다. 백테스트·모의투자는 `SimBroker`(다음 날 시가 체결)로 돈다.
- 유니버스가 현재 대형주라 생존편향이 있다. 거래세율은 `config.yaml`에서 확인 후 조정.
- 백테스트는 보유 기간이 찬 날 종가에 판단하고 다음 날 시가에 매도한다. 검정(그날 종가 매도)과 하루 차이가 난다.
