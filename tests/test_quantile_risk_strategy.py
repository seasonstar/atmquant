"""分位数风险仓位策略的执行边界测试。"""

from dataclasses import replace

import pytest

from core.indicators.calculators.adaptive_linear_regression_calculator import (
    AdaptiveState,
    RegressionSignal,
    fit_ols,
)
from core.strategies.quantile_risk_strategy import QuantileRiskStrategy


def make_state(close: float, mid: float = 100, signal=None):
    model = replace(
        fit_ols([10, 11, 13, 12, 15], origin_idx=0),
        current_est=mid,
        is_valid=True,
    )
    return AdaptiveState(
        index=20,
        close=close,
        model=model,
        upper_band=mid + 4,
        lower_band=mid - 4,
        signal=signal,
        atr=2.0,
        pivot_indices=(0,),
    )


class FakeAdaptiveCalculator:
    def __init__(self, state):
        self.state = state

    def update(self, bar):
        return self.state


class FakeRiskCalculator:
    def __init__(self, risk):
        self.risk = risk

    def update(self, bar):
        from types import SimpleNamespace

        return SimpleNamespace(risk=self.risk, quantile=-self.risk)


def make_strategy(state, position: int, risk: float, model: str = "caviar"):
    strategy = QuantileRiskStrategy.__new__(QuantileRiskStrategy)
    strategy.calculator = FakeAdaptiveCalculator(state)
    strategy.risk_model = model
    strategy.risk_calculator = FakeRiskCalculator(risk)
    strategy.reference_risk = 0.5
    strategy.base_size = 2
    strategy.max_size = 2
    strategy.pos = position
    strategy.pending_stop_price = 0.0
    strategy.entry_stop_price = 95.0 if position > 0 else 105.0
    strategy.entry_signal_price = 0.0
    strategy.entry_actual_price = 0.0
    strategy.first_signal_datetime = None
    strategy.last_bar_datetime = None
    strategy.current_risk = 0.0
    strategy.current_quantile = 0.0
    strategy.target_size = 2
    strategy.signal_log = []
    strategy.orders = []
    strategy.trading = True
    strategy.cancel_all = lambda: None
    strategy.buy = lambda price, volume: strategy.orders.append(("buy", price, volume))
    strategy.short = lambda price, volume: strategy.orders.append(("short", price, volume))
    strategy.sell = lambda price, volume: strategy.orders.append(("sell", price, volume))
    strategy.cover = lambda price, volume: strategy.orders.append(("cover", price, volume))
    return strategy


def test_entry_uses_risk_size_without_changing_signal_or_stop() -> None:
    signal = RegressionSignal(1, 99, 101, 95)
    strategy = make_strategy(make_state(99, signal=signal), 0, risk=2.0)

    strategy.on_15min_bar({"close": 99, "high": 100, "low": 98})

    assert strategy.orders == [("buy", pytest.approx(99 * 1.1), 1)]
    assert strategy.pending_stop_price == 95
    assert strategy.signal_log[-1][1:] == ("entry", 1)


def test_long_reduction_sells_but_never_reverses() -> None:
    strategy = make_strategy(make_state(99, mid=110), 2, risk=2.0)

    strategy.on_15min_bar({"close": 99, "high": 100, "low": 98})

    assert strategy.orders == [("sell", pytest.approx(99 * 0.9), 1)]
    assert strategy.target_size == 1


def test_original_exit_closes_full_position_without_resizing() -> None:
    strategy = make_strategy(make_state(94, mid=100), 2, risk=2.0)

    strategy.on_15min_bar({"close": 94, "high": 100, "low": 93})

    assert strategy.orders == [("sell", pytest.approx(94 * 0.9), 2)]
    assert strategy.signal_log[-1][1:] == ("exit", 1)


def test_short_increase_uses_short_not_buy() -> None:
    strategy = make_strategy(make_state(101, mid=90), -1, risk=0.1)

    strategy.on_15min_bar({"close": 101, "high": 102, "low": 100})

    assert strategy.orders == [("short", pytest.approx(101 * 0.9), 1)]
    assert strategy.target_size == 2


def test_fixed_model_keeps_two_lots() -> None:
    signal = RegressionSignal(1, 99, 101, 95)
    strategy = make_strategy(make_state(99, signal=signal), 0, risk=100.0, model="fixed")

    strategy.on_15min_bar({"close": 99, "high": 100, "low": 98})

    assert strategy.orders == [("buy", pytest.approx(99 * 1.1), 2)]


def test_risk_calculator_is_ready_before_parent_warmup(monkeypatch) -> None:
    """父类回放预热K线前，风险状态机必须已经存在。"""
    from types import SimpleNamespace
    from core.strategies.adaptive_linear_regression_strategy import (
        AdaptiveLinearRegressionStrategy,
    )

    strategy = QuantileRiskStrategy.__new__(QuantileRiskStrategy)
    strategy.risk_model = "caviar"

    def fake_parent_init(self):
        assert hasattr(self, "risk_calculator")
        self.risk_calculator.update(SimpleNamespace(
            close_price=100.0, high_price=101.0, low_price=99.0
        ))

    monkeypatch.setattr(AdaptiveLinearRegressionStrategy, "on_init", fake_parent_init)
    strategy.on_init()
