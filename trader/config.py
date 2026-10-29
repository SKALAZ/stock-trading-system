"""config.yaml과 .env를 읽는다."""
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict:
    load_dotenv(ROOT / ".env")
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def round_trip_cost(cfg: dict) -> float:
    """한 번 사고 파는 데 드는 비용 (수익률 단위). 검정과 백테스트가 같은 값을 쓴다."""
    c = cfg["costs"]
    return 2 * c["commission"] + c["sell_tax"] + 2 * c["slippage"]
