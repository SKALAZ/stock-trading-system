"""⑤ 기록. 모든 검정·판단·가드레일 판정·주문을 SQLite 한 파일에 남긴다.

역추적 경로: orders.decision_id → decisions(GPT 입력·출력) → guardrail_checks
            decisions.principle_test_ids → principle_tests(검정 리포트)
"""
import hashlib
import json
import sqlite3
from datetime import datetime

from trader.config import ROOT

DB_PATH = ROOT / "journal.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS principle_tests (
    test_id INTEGER PRIMARY KEY, principle_id TEXT, created_at TEXT, params TEXT,
    n_events INTEGER, mean_excess REAL, ci_low REAL, ci_high REAL, p_value REAL,
    random_percentile REAL, validate_n INTEGER, validate_mean REAL, validate_p REAL,
    verdict TEXT, reasons TEXT, report_path TEXT
);
CREATE TABLE IF NOT EXISTS principle_status (
    principle_id TEXT PRIMARY KEY, status TEXT, test_id INTEGER, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY, created_at TEXT, mode TEXT, label TEXT, params TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY, run_id INTEGER, date TEXT, agent TEXT, model TEXT,
    prompt_version TEXT, context TEXT, steps TEXT, output TEXT, principle_test_ids TEXT
);
CREATE TABLE IF NOT EXISTS guardrail_checks (
    id INTEGER PRIMARY KEY, decision_id INTEGER, item INTEGER, ticker TEXT, action TEXT,
    principle_id TEXT, rule TEXT, verdict TEXT, before REAL, after REAL, reason TEXT,
    enforced INTEGER
);
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY, run_id INTEGER, decision_id INTEGER, item INTEGER,
    client_order_id TEXT UNIQUE, date TEXT, ticker TEXT, side TEXT, qty INTEGER,
    requested_weight REAL, final_weight REAL, verdict TEXT, source TEXT,
    status TEXT, fill_date TEXT, fill_price REAL, fill_qty INTEGER, weight_after REAL
);
CREATE TABLE IF NOT EXISTS daily_equity (
    run_id INTEGER, date TEXT, equity REAL, cash REAL, n_positions INTEGER,
    max_weight REAL, PRIMARY KEY (run_id, date)
);
CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, response TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS run_usage (
    run_id INTEGER PRIMARY KEY, model TEXT, calls INTEGER, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Journal:
    def __init__(self, path=DB_PATH):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # 실거래용 열 (예전에 만든 DB에는 없으므로 추가만 한다)
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(orders)")}
        for col, typ in (("broker_order_id", "TEXT"), ("commission", "REAL"), ("tax", "REAL"), ("note", "TEXT")):
            if col not in have:
                self.db.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
        self.db.commit()

    def _insert(self, table: str, **cols) -> int:
        keys = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        cur = self.db.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", list(cols.values()))
        self.db.commit()
        return cur.lastrowid

    def query(self, sql: str, *args) -> list[sqlite3.Row]:
        return self.db.execute(sql, args).fetchall()

    # ── 원칙 검정 ──────────────────────────────────────────────
    def record_test(self, **cols) -> int:
        return self._insert("principle_tests", created_at=_now(), **cols)

    def count_tests(self, principle_id: str) -> int:
        return self.query("SELECT COUNT(*) FROM principle_tests WHERE principle_id=?", principle_id)[0][0]

    def set_status(self, principle_id: str, status: str, test_id: int | None):
        self.db.execute("INSERT OR REPLACE INTO principle_status VALUES (?, ?, ?, ?)",
                        (principle_id, status, test_id, _now()))
        self.db.commit()

    def passed_principles(self) -> dict[str, int]:
        """검정을 통과한 원칙 id → 근거가 된 test_id"""
        rows = self.query("SELECT principle_id, test_id FROM principle_status WHERE status='passed'")
        return {r["principle_id"]: r["test_id"] for r in rows}

    # ── 운영·백테스트 ──────────────────────────────────────────
    def new_run(self, mode: str, label: str, params: dict) -> int:
        return self._insert("runs", created_at=_now(), mode=mode, label=label,
                            params=json.dumps(params, ensure_ascii=False))

    def log_decision(self, **cols) -> int:
        for k in ("context", "steps", "output", "principle_test_ids"):
            cols[k] = json.dumps(cols[k], ensure_ascii=False, default=str)
        return self._insert("decisions", **cols)

    def log_check(self, **cols):
        self._insert("guardrail_checks", **cols)

    def log_order(self, **cols) -> int:
        return self._insert("orders", **cols)

    def update_order(self, order_id: int, **cols):
        sets = ", ".join(f"{k}=?" for k in cols)
        self.db.execute(f"UPDATE orders SET {sets} WHERE order_id=?", [*cols.values(), order_id])
        self.db.commit()

    def record_usage(self, run_id: int, usage, model: str):
        """GPT 호출 횟수·토큰·예상 비용 (캐시로 재사용한 응답은 세지 않는다)"""
        self.db.execute("INSERT OR REPLACE INTO run_usage VALUES (?, ?, ?, ?, ?, ?)",
                        (run_id, model, usage.calls, usage.input_tokens, usage.output_tokens, usage.cost(model)))
        self.db.commit()

    def log_equity(self, run_id: int, date: str, equity: float, cash: float, n_positions: int, max_weight: float):
        self.db.execute("INSERT OR REPLACE INTO daily_equity VALUES (?, ?, ?, ?, ?, ?)",
                        (run_id, date, equity, cash, n_positions, max_weight))
        self.db.commit()

    # ── GPT 응답 캐시: 같은 입력이면 같은 응답 (재현성 + 비용 절감) ──
    @staticmethod
    def cache_key(payload) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def cache_get(self, key: str):
        rows = self.query("SELECT response FROM llm_cache WHERE key=?", key)
        return json.loads(rows[0]["response"]) if rows else None

    def cache_put(self, key: str, response):
        self.db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?)",
                        (key, json.dumps(response, ensure_ascii=False), _now()))
        self.db.commit()
