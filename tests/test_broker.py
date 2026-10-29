import pytest

from trader.broker import LiveBroker, krx_tick, round_to_tick


@pytest.mark.parametrize("price,tick", [(1_500, 1), (4_990, 5), (19_000, 10), (45_000, 50), (150_000, 100),
                                        (199_900, 100), (245_000, 500), (566_566, 1_000)])
def test_krx_tick(price, tick):
    assert krx_tick(price) == tick


def test_round_to_tick_never_crosses_to_worse_side():
    assert round_to_tick(245_050, "BUY") == 245_000   # 호가 단위 500원
    assert round_to_tick(245_050, "SELL") == 245_500
    assert round_to_tick(23_173, "BUY") == 23_150     # 호가 단위 50원


def test_live_broker_refuses_without_explicit_flag(monkeypatch):
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_LIVE_TRADING"):
        LiveBroker(client=None, account_seq=1)
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "no")
    with pytest.raises(RuntimeError):
        LiveBroker(client=None, account_seq=1)
