"""稳健回归效率通道CTA测试。"""

from types import SimpleNamespace

import pytest

from core.indicators.calculators.robust_regression_efficiency_channel_calculator import (
    RobustEfficiencyState,
)
from core.strategies.robust_regression_efficiency_channel_strategy import (
    RobustRegressionEfficiencyChannelStrategy,
    get_robust_exit_reason,
    get_tightened_atr_stop,
)


def make_state(
    close: float = 110,
    slope: float = 1.0,
    upper: float = 105,
    lower: float = 95,
    er: float = 0.8,
    atr: float = 2.0,
    valid: bool = True,
):
    return RobustEfficiencyState(
        index=20,
        close=close,
        slope=slope,
        intercept=100,
        mid=100,
        residual_mad=2,
        upper_band=upper,
        lower_band=lower,
        efficiency_ratio=er,
        atr=atr,
        is_valid=valid,
    )


def test_atr_stop_can_only_tighten() -> None:
    """多头止损只上移，空头止损只下移。"""
    assert get_tightened_atr_stop(1, 90, 120, 5, 2) == 110
    assert get_tightened_atr_stop(1, 110, 100, 5, 2) == 110
    assert get_tightened_atr_stop(-1, 130, 80, 5, 2) == 90
    assert get_tightened_atr_stop(-1, 90, 100, 5, 2) == 90


def test_exit_uses_stop_then_slope_reversal_without_midline_take_profit() -> None:
    """止损优先，其次斜率反向，不设置中轨止盈。"""
    assert get_robust_exit_reason(1, 99, 1, 100) == "stop"
    assert get_robust_exit_reason(1, 105, -1, 100) == "slope_reversal"
    assert get_robust_exit_reason(1, 105, 1, 100) is None
    assert get_robust_exit_reason(-1, 101, 1, 100) == "stop"
    assert get_robust_exit_reason(-1, 95, 1, 100) == "slope_reversal"


class FakeCalculator:
    def __init__(self, state):
        self.state = state

    def update(self, bar):
        return self.state


def make_strategy(state, position=0):
    strategy = RobustRegressionEfficiencyChannelStrategy.__new__(
        RobustRegressionEfficiencyChannelStrategy
    )
    strategy.calculator = FakeCalculator(state)
    strategy.pos = position
    strategy.fixed_size = 1
    strategy.atr_multiplier = 2.0
    strategy.er_threshold = 0.3
    strategy.pending_atr = 0.0
    strategy.pending_extreme_close = 0.0
    strategy.entry_stop_price = 0.0 if position == 0 else (100.0 if position > 0 else 120.0)
    strategy.extreme_close = 110.0 if position > 0 else 90.0
    strategy.first_signal_datetime = None
    strategy.orders = []
    strategy.cancel_all = lambda: None
    strategy.buy = lambda price, volume: strategy.orders.append(("buy", price, volume))
    strategy.short = lambda price, volume: strategy.orders.append(("short", price, volume))
    strategy.sell = lambda price, volume: strategy.orders.append(("sell", price, volume))
    strategy.cover = lambda price, volume: strategy.orders.append(("cover", price, volume))
    return strategy


def test_breakout_entry_waits_for_actual_fill_to_set_atr_stop() -> None:
    """信号只记录ATR，实际成交后才按成交价计算初始止损。"""
    strategy = make_strategy(make_state())

    strategy.on_15min_bar({"close": 110, "high": 111, "low": 109})
    strategy.pos = 1
    strategy.on_trade(SimpleNamespace(price=108.0))

    assert strategy.orders == [("buy", pytest.approx(110 * 1.1), 1)]
    assert strategy.entry_stop_price == 104.0


def test_atr_must_be_ready_before_entry() -> None:
    """通道有效但ATR尚未形成时禁止开仓。"""
    strategy = make_strategy(make_state(atr=float("nan")))

    strategy.on_15min_bar({"close": 110, "high": 111, "low": 109})

    assert strategy.orders == []


def test_invalid_channel_does_not_disable_existing_stop() -> None:
    """通道失效禁止新仓，但已有仓位仍按ATR止损退出。"""
    strategy = make_strategy(make_state(close=95, slope=0, valid=False), position=1)
    strategy.extreme_close = 95.0

    strategy.on_15min_bar({"close": 95, "high": 96, "low": 94})

    assert strategy.orders == [("sell", pytest.approx(95 * 0.9), 1)]
