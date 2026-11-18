"""自适应线性回归CTA执行测试。"""

from dataclasses import replace

import pytest

from core.indicators.calculators.adaptive_linear_regression_calculator import (
    AdaptiveState,
    RegressionSignal,
    fit_ols,
)
from core.strategies.adaptive_linear_regression_strategy import (
    AdaptiveLinearRegressionStrategy,
    get_exit_reason,
)


def make_state(close: float, mid: float = 100, valid: bool = True, signal=None):
    model = replace(
        fit_ols([10, 11, 13, 12, 15], origin_idx=0),
        current_est=mid,
        is_valid=valid,
    )
    return AdaptiveState(
        index=20,
        close=close,
        model=model,
        upper_band=mid + 4 if valid else None,
        lower_band=mid - 4 if valid else None,
        signal=signal,
        atr=2.0,
        pivot_indices=(0,),
    )


def test_long_stop_still_works_when_model_is_invalid() -> None:
    """通道失效不能跳过已有止损，止损优先于止盈。"""
    assert get_exit_reason(1, 94, make_state(94, valid=False).model, 95) == "stop"
    assert get_exit_reason(1, 94, make_state(94, mid=90).model, 95) == "stop"


def test_dynamic_midline_take_profit_for_both_directions() -> None:
    """多头向上触及当前中轨退出，空头向下触及当前中轨退出。"""
    assert get_exit_reason(1, 101, make_state(101, mid=100).model, 95) == "take_profit"
    assert get_exit_reason(-1, 99, make_state(99, mid=100).model, 105) == "take_profit"
    assert get_exit_reason(1, 99, make_state(99, mid=100).model, 95) is None


class FakeCalculator:
    def __init__(self, state):
        self.state = state

    def update(self, bar):
        return self.state


def make_strategy(state: AdaptiveState, position: int):
    strategy = AdaptiveLinearRegressionStrategy.__new__(AdaptiveLinearRegressionStrategy)
    strategy.calculator = FakeCalculator(state)
    strategy.pos = position
    strategy.fixed_size = 1
    strategy.pending_stop_price = 0.0
    strategy.entry_stop_price = 95.0 if position > 0 else 105.0
    strategy.first_signal_datetime = None
    strategy.orders = []
    strategy.cancel_all = lambda: None
    strategy.buy = lambda price, volume: strategy.orders.append(("buy", price, volume))
    strategy.short = lambda price, volume: strategy.orders.append(("short", price, volume))
    strategy.sell = lambda price, volume: strategy.orders.append(("sell", price, volume))
    strategy.cover = lambda price, volume: strategy.orders.append(("cover", price, volume))
    return strategy


def test_flat_strategy_enters_with_signal_price_and_frozen_stop() -> None:
    """空仓出现LONG时只开1手，并保存信号对应的初始止损。"""
    signal = RegressionSignal(1, 99, 101, 95)
    strategy = make_strategy(make_state(99, signal=signal), 0)

    strategy.on_15min_bar({"close": 99, "high": 100, "low": 98})

    assert strategy.orders == [("buy", pytest.approx(99 * 1.1), 1)]
    assert strategy.pending_stop_price == 95


def test_holding_strategy_does_not_reverse_on_new_signal() -> None:
    """持仓期间出现反向标签也不能直接反手。"""
    signal = RegressionSignal(1, 100, 101, 95)
    strategy = make_strategy(make_state(100, mid=90, signal=signal), -1)

    strategy.on_15min_bar({"close": 100, "high": 101, "low": 99})

    assert strategy.orders == []
