"""
토스증권 Open API 클라이언트 (https://developers.tossinvest.com/docs)
──────────────────────────────────────────────────────────────
  인증      POST /oauth2/token  (client_credentials, client 당 유효 토큰 1개 — 재발급 시 이전 토큰 무효)
  조회      GET  /api/v1/accounts · holdings · prices · buying-power · orders · orders/{id}
  주문      POST /api/v1/orders  ← LiveBroker 에서만, ALLOW_LIVE_TRADING=yes 일 때만

키는 .env 에서만 읽는다: TOSS_CLIENT_ID, TOSS_CLIENT_SECRET, (있으면) TOSS_ACCESS_TOKEN.
새로 발급한 토큰은 .env 를 고치지 않고 state/toss_token.json 에 캐시한다 (git 제외 폴더).
허용 IP 목록에 없는 PC 에서 부르면 403 ip-not-allowed — 토스증권 WTS 설정 > Open API > 허용 IP 관리에서 등록.
"""
from __future__ import annotations

import json
import os
import time

import httpx

from trader.config import ROOT, load_config

BASE = "https://openapi.tossinvest.com"
TOKEN_CACHE = ROOT / "state" / "toss_token.json"
# 그룹별 초당 한도 (문서의 Rate Limits). 넘지 않도록 호출 사이 간격을 둔다
MIN_INTERVAL = {"AUTH": 0.25, "ACCOUNT": 1.05, "ASSET": 0.25, "MARKET_DATA": 0.1, "ORDER": 0.15,
                "ORDER_HISTORY": 0.25, "ORDER_INFO": 0.4}


class TossError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, request_id: str | None = None):
        super().__init__(f"[{status} {code}] {message}" + (f" (requestId {request_id})" if request_id else ""))
        self.status, self.code = status, code


class TossClient:
    def __init__(self, timeout: float = 10.0):
        load_config()  # .env 로드
        self.client_id = os.getenv("TOSS_CLIENT_ID")
        self.client_secret = os.getenv("TOSS_CLIENT_SECRET")
        if not (self.client_id and self.client_secret):
            raise RuntimeError("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 가 .env 에 없습니다")
        self.http = httpx.Client(base_url=BASE, timeout=timeout)
        self._token = self._cached_token() or os.getenv("TOSS_ACCESS_TOKEN")
        self._last: dict[str, float] = {}

    # ──────────────────────────────────────────────────────────────
    # 토큰
    # ──────────────────────────────────────────────────────────────
    def _cached_token(self) -> str | None:
        try:
            d = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            return d["access_token"] if d.get("expires_at", 0) > time.time() + 60 else None
        except (OSError, ValueError, KeyError):
            return None

    def issue_token(self) -> str:
        """새 토큰 발급. 이 client 의 이전 토큰은 즉시 무효가 된다."""
        r = self._send("AUTH", "POST", "/oauth2/token", auth=False,
                       data={"grant_type": "client_credentials", "client_id": self.client_id,
                             "client_secret": self.client_secret})
        self._token = r["access_token"]
        TOKEN_CACHE.parent.mkdir(exist_ok=True)
        TOKEN_CACHE.write_text(json.dumps({"access_token": self._token, "expires_at": time.time() + r["expires_in"]}),
                               encoding="utf-8")
        return self._token

    # ──────────────────────────────────────────────────────────────
    # 공통 호출: 한도 간격 · 429 재시도 · 토큰 만료 시 1회 재발급 · 에러 envelope 해석
    # ──────────────────────────────────────────────────────────────
    def _send(self, group: str, method: str, path: str, auth: bool = True, account: int | None = None,
              retry_auth: bool = True, **kw):
        wait = MIN_INTERVAL.get(group, 0.25) - (time.monotonic() - self._last.get(group, 0))
        if wait > 0:
            time.sleep(wait)
        headers = kw.pop("headers", {})
        if auth:
            if not self._token:
                self.issue_token()
            headers["Authorization"] = f"Bearer {self._token}"
        if account is not None:
            headers["X-Tossinvest-Account"] = str(account)
        for attempt in range(4):
            resp = self.http.request(method, path, headers=headers, **kw)
            self._last[group] = time.monotonic()
            if resp.status_code != 429:
                break
            time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
        if resp.status_code == 401 and auth and retry_auth:
            code = self._error(resp).code
            if code in ("expired-token", "invalid-token", "token-revoked"):
                self.issue_token()
                return self._send(group, method, path, auth, account, retry_auth=False, headers={}, **kw)
        if resp.status_code >= 400:
            raise self._error(resp)
        body = resp.json()
        return body.get("result", body) if isinstance(body, dict) else body

    @staticmethod
    def _error(resp: httpx.Response) -> TossError:
        try:
            body = resp.json()
        except ValueError:
            return TossError(resp.status_code, "http-error", resp.text[:200])
        err = body.get("error")
        if isinstance(err, dict):
            return TossError(resp.status_code, err.get("code", "?"), err.get("message", ""), err.get("requestId"))
        # OAuth2 표준 형식 (토큰 발급 실패)
        return TossError(resp.status_code, str(err or "?"), body.get("error_description", ""))

    # ──────────────────────────────────────────────────────────────
    # 조회 (주문 없음)
    # ──────────────────────────────────────────────────────────────
    def accounts(self) -> list[dict]:
        return self._send("ACCOUNT", "GET", "/api/v1/accounts")

    def holdings(self, account: int) -> dict:
        return self._send("ASSET", "GET", "/api/v1/holdings", account=account)

    def prices(self, symbols: list[str]) -> list[dict]:
        return self._send("MARKET_DATA", "GET", "/api/v1/prices", params={"symbols": ",".join(symbols)})

    def buying_power(self, account: int, currency: str = "KRW") -> dict:
        return self._send("ORDER_INFO", "GET", "/api/v1/buying-power", account=account, params={"currency": currency})

    def order(self, account: int, order_id: str) -> dict:
        return self._send("ORDER_HISTORY", "GET", f"/api/v1/orders/{order_id}", account=account)

    def orders(self, account: int, **params) -> dict:
        """{"orders": [...], "nextCursor", "hasNext"}. status=OPEN(대기중) / CLOSED(종료)"""
        return self._send("ORDER_HISTORY", "GET", "/api/v1/orders", account=account, params=params)

    # ──────────────────────────────────────────────────────────────
    # 주문 — LiveBroker 만 부른다
    # ──────────────────────────────────────────────────────────────
    def _create_order(self, account: int, body: dict) -> dict:
        return self._send("ORDER", "POST", "/api/v1/orders", account=account, json=body)


def symbol_of(ticker: str) -> str:
    """yfinance 티커 → 토스 심볼. 005930.KS → 005930"""
    return ticker.split(".")[0]


def mask(no: str) -> str:
    return no[:3] + "*" * max(len(no) - 5, 0) + no[-2:] if no and len(no) > 5 else "***"
