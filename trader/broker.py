"""④ 주문 실행. 엔진은 브로커가 무엇이든 `execute()`만 부른다.

- SimBroker: 백테스트·모의투자. 다음 날 시가 ± 슬리피지로 체결, 수수료·세금 반영.
- LiveBroker: 토스증권 실계좌 주문 (trader/toss.py 클라이언트 사용).
"""
import math
import os
import time


class SimBroker:
    def __init__(self, costs: dict):
        self.c = costs

    def execute(self, side: str, qty: int, open_price: float, cash: float) -> tuple[float, int, float]:
        """반환: (체결가, 체결 수량, 현금 증감)"""
        if side == "BUY":
            px = open_price * (1 + self.c["slippage"])
            unit = px * (1 + self.c["commission"])
            qty = min(qty, math.floor(cash / unit))   # 현금보다 많이 살 수는 없다 (신용 없음)
            return px, qty, -qty * unit
        px = open_price * (1 - self.c["slippage"])
        return px, qty, qty * px * (1 - self.c["commission"] - self.c["sell_tax"])


def krx_tick(price: float) -> int:
    """KRX 호가 단위 (2023년 이후 코스피·코스닥 공통)"""
    for limit, tick in ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50), (200_000, 100), (500_000, 500)):
        if price < limit:
            return tick
    return 1_000


def round_to_tick(price: float, side: str) -> int:
    """지정가를 호가 단위에 맞춘다. 매수는 내림, 매도는 올림 (불리한 쪽으로 넘어가지 않게)."""
    t = krx_tick(price)
    return int(math.floor(price / t) * t if side == "BUY" else math.ceil(price / t) * t)


class LiveBroker:
    """토스증권 실계좌 주문. 실수로 켜지지 않도록 ALLOW_LIVE_TRADING=yes 가 아니면 만들어지지 않는다.

    - 주문마다 고유 clientOrderId 를 넘긴다 → 네트워크 재시도해도 같은 주문이 두 번 들어가지 않는다 (멱등성 키)
    - confirmHighValueOrder 는 보내지 않는다 → 1억 원 이상 주문은 토스가 거부한다 (착오주문 방지)
    - 체결은 주문 상세 조회로 확인한다 (부분 체결 포함)
    """

    FINAL = {"FILLED", "CANCELED", "REJECTED", "REPLACED"}

    def __init__(self, client, account_seq: int):
        if os.getenv("ALLOW_LIVE_TRADING") != "yes":
            raise RuntimeError("실계좌 주문은 꺼져 있습니다 (.env 에 ALLOW_LIVE_TRADING=yes 필요)")
        self.client, self.account = client, account_seq

    def submit(self, symbol: str, side: str, qty: int, client_order_id: str, limit_price: float | None = None) -> str:
        body = {"clientOrderId": client_order_id, "symbol": symbol, "side": side,
                "orderType": "LIMIT" if limit_price else "MARKET", "quantity": str(int(qty))}
        if limit_price:
            # 국내(6자리 코드)는 KRX 호가 단위, 미국 티커는 0.01달러 단위
            body["price"] = str(round_to_tick(limit_price, side)) if symbol[:1].isdigit() else f"{limit_price:.2f}"
        return self.client._create_order(self.account, body)["orderId"]

    def wait(self, order_id: str, timeout: float = 30, every: float = 2) -> dict:
        """끝난 상태(체결·취소·거부)가 되거나 timeout 까지 주문 상태를 확인한다."""
        deadline = time.monotonic() + timeout
        while True:
            o = self.client.order(self.account, order_id)
            if o["status"] in self.FINAL or time.monotonic() > deadline:
                return o
            time.sleep(every)
