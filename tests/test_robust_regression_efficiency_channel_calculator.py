"""稳健回归效率通道的独立计算测试。"""

import numpy as np
import pytest

from core.indicators.calculators.robust_regression_efficiency_channel_calculator import (
    RobustRegressionEfficiencyCalculator,
    calculate_efficiency_ratio,
    fit_robust_regression,
    get_breakout_direction,
)


def make_bar(close: float, high: float | None = None, low: float | None = None):
    return {
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
    }


def test_theil_sen_uses_median_pairwise_slope_and_residual_intercept() -> None:
    """斜率取成对斜率中位数，截距取y-slope*x的中位数。"""
    fit = fit_robust_regression([10, 11, 13, 12, 15])

    assert fit.slope == pytest.approx(1.125)
    assert fit.intercept == pytest.approx(10.0)
    assert fit.mid == pytest.approx(14.5)
    assert fit.residual_mad == pytest.approx(1.4826 * 0.5)


def test_efficiency_ratio_handles_trend_zigzag_and_flat_prices() -> None:
    """ER比较净变化与路径长度，零分母时返回0。"""
    assert calculate_efficiency_ratio([10, 11, 12, 13]) == pytest.approx(1.0)
    assert calculate_efficiency_ratio([10, 11, 10, 11]) == pytest.approx(1 / 3)
    assert calculate_efficiency_ratio([10, 10, 10, 10]) == 0.0


def test_zero_mad_channel_cannot_open_a_breakout() -> None:
    """完全线性窗口的MAD为0，轨道重合且禁止新开仓。"""
    calc = RobustRegressionEfficiencyCalculator(window=5)
    states = [calc.update(make_bar(value)) for value in [10, 12, 14, 16, 18]]
    state = states[-1]

    assert state.residual_mad == 0.0
    assert not state.is_valid
    assert get_breakout_direction(state, 0.2) == 0


def test_breakout_requires_band_slope_and_efficiency() -> None:
    """多头必须同时突破上轨、斜率为正且ER达标。"""
    calc = RobustRegressionEfficiencyCalculator(
        window=5, deviation_factor=0.1, er_threshold=0.5
    )
    states = [calc.update(make_bar(value)) for value in [10, 10.2, 9.8, 10.4, 12.0]]
    state = states[-1]

    assert state.is_valid
    assert state.close > state.upper_band
    assert state.slope > 0
    assert state.efficiency_ratio >= 0.5
    assert get_breakout_direction(state, 0.5) == 1
    assert get_breakout_direction(state, 0.99) == 0


def test_atr_uses_sma_seed_then_rma() -> None:
    """ATR14首值取TR均值，之后按RMA更新。"""
    calc = RobustRegressionEfficiencyCalculator(window=40)
    states = [calc.update(make_bar(0.0, float(i), 0.0)) for i in range(15)]

    assert states[13].atr == pytest.approx(6.5)
    assert states[14].atr == pytest.approx((6.5 * 13 + 14) / 14)


def test_future_bars_cannot_change_existing_states() -> None:
    """追加未来K线后，历史稳健拟合、通道和ATR必须不变。"""
    rng = np.random.default_rng(19)
    closes = 100 + np.cumsum(rng.normal(0, 1, 35))
    bars = [make_bar(float(c), float(c + 1), float(c - 1)) for c in closes]
    calc = RobustRegressionEfficiencyCalculator(window=20)

    first = calc.compute(bars[:25])[-1]
    second = calc.compute(bars)[24]

    assert first == second
