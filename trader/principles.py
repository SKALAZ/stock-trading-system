"""투자 원칙 = 숫자로 참/거짓을 판정할 수 있는 가설. principles/*.yaml에서 읽는다."""
from dataclasses import dataclass

import pandas as pd
import yaml

from trader.config import ROOT

PRINCIPLE_DIR = ROOT / "principles"


@dataclass(frozen=True)
class Principle:
    id: str
    name: str
    hypothesis: str
    entry: str            # pandas 조건식. 예: "close > sma60 and rsi14 < 30"
    horizon_days: int
    position_size: float

    def signal(self, df: pd.DataFrame) -> pd.Series:
        """각 날짜 종가 기준으로 진입 조건 충족 여부. 지표가 아직 없는(NaN) 날은 False."""
        return df.eval(self.entry, engine="python").fillna(False).astype(bool)

    def matches(self, row: pd.Series) -> bool:
        """하루치 데이터로 조건을 다시 판정한다 (가드레일 G03에서 사용)."""
        return bool(self.signal(row.to_frame().T.astype(float)).iloc[0])

    def describe(self) -> dict:
        return {
            "id": self.id, "name": self.name, "hypothesis": self.hypothesis.strip(),
            "entry": self.entry, "horizon_days": self.horizon_days, "position_size": self.position_size,
        }


def load_principle(pid: str) -> Principle:
    with open(PRINCIPLE_DIR / f"{pid}.yaml", encoding="utf-8") as f:
        d = yaml.safe_load(f)
    return Principle(d["id"], d["name"], d["hypothesis"], d["entry"],
                     int(d["horizon_days"]), float(d["position_size"]))


def load_all() -> dict[str, Principle]:
    return {p.stem: load_principle(p.stem) for p in sorted(PRINCIPLE_DIR.glob("*.yaml"))}
