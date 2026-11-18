"""Adaptive Linear Regression Structure 共享计算测试。"""

from dataclasses import replace

import numpy as np
import pytest

from core.indicators.calculators.adaptive_linear_regression_calculator import (
    AdaptiveLinearRegressionCalculator,
    StatisticalModel,
    detect_signal,
    fit_ols,
    select_best_model,
)


def make_bar(close: float, high: float | None = None, low: float | None = None):
    return {
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
    }


def test_ols_matches_source_formulas() -> None:
    """OLS 使用局部时间0至N-1，并计算残差标准误与Duration评分。"""
    model = fit_ols([10, 11, 13, 12, 15], origin_idx=7)

    assert model.is_valid
    assert model.beta_slope == pytest.approx(1.1)
    assert model.alpha_offset == pytest.approx(10.0)
    assert model.coeff_deter == pytest.approx(121 / 148)
    assert model.std_deviation == pytest.approx(np.sqrt(0.9))
    assert model.current_est == pytest.approx(14.4)
    assert model.z_metric == pytest.approx(0.6 / np.sqrt(0.9))
    assert model.duration == 5
    assert model.origin_idx == 7
    assert model.perf_score == pytest.approx((121 / 148) * np.log(5))


def test_flat_prices_are_not_a_valid_model() -> None:
    """det_y 为0时原指标排除模型，不能制造零残差通道。"""
    model = fit_ols([10, 10, 10, 10, 10])

    assert not model.is_valid


def test_best_model_rewards_duration_and_keeps_newer_tie() -> None:
    """评分是R²乘ln(N)，严格大于才替换，因此同分保留较新的候选。"""
    newer = replace(fit_ols([10, 11, 13, 12, 15], origin_idx=10), coeff_deter=0.5, perf_score=1.0)
    older = replace(fit_ols([10, 11, 13, 12, 15], origin_idx=2), coeff_deter=0.9, perf_score=1.0)
    longer = replace(older, perf_score=2.0)

    assert select_best_model([newer, older], 0.5).origin_idx == 10
    assert select_best_model([newer, longer], 0.5).origin_idx == 2
    assert not select_best_model([replace(newer, coeff_deter=0.2)], 0.5).is_valid


def test_pivot_waits_for_confirmation_and_anchor_bar_is_excluded() -> None:
    """灵敏度2的枢轴在两根后注册，N=T-A，样本不包含A本身。"""
    highs = [8, 9, 10, 9, 8, 8, 8, 8]
    closes = [8, 9, 9.5, 9, 8.5, 8.7, 8.8, 9]
    bars = [make_bar(c, h, 7) for c, h in zip(closes, highs)]
    calc = AdaptiveLinearRegressionCalculator(
        scan_horizon=20,
        deviation_factor=2.0,
        structural_sensitivity=2,
        quality_threshold=0.0,
    )

    states = [calc.update(bar) for bar in bars]

    assert states[6].model.origin_idx is None
    assert states[7].model.origin_idx == 2
    assert states[7].model.duration == 5
    expected = fit_ols(closes[3:8], origin_idx=2)
    assert states[7].model.alpha_offset == pytest.approx(expected.alpha_offset)
    assert states[7].model.beta_slope == pytest.approx(expected.beta_slope)


def test_future_bars_cannot_change_an_existing_state() -> None:
    """追加未来行情后，此前最优模型、轨道和信号必须保持完全一致。"""
    rng = np.random.default_rng(7)
    closes = 100 + np.cumsum(rng.normal(0, 1, 30))
    bars = [make_bar(float(c), float(c + 1), float(c - 1)) for c in closes]
    calc = AdaptiveLinearRegressionCalculator(quality_threshold=0.0)
    first = calc.compute(bars[:20])[-1]
    second = calc.compute(bars)[19]

    assert first == second


def test_atr_uses_sma_seed_then_rma() -> None:
    """ATR14 首个值取前14个TR均值，此后按RMA递推。"""
    calc = AdaptiveLinearRegressionCalculator()
    states = [calc.update(make_bar(0.0, float(i), 0.0)) for i in range(15)]

    assert states[13].atr == pytest.approx(6.5)
    assert states[14].atr == pytest.approx((6.5 * 13 + 14) / 14)


def model_with_bands(mid: float, deviation: float = 2.0) -> StatisticalModel:
    base = fit_ols([10, 11, 13, 12, 15])
    return replace(base, current_est=mid, std_deviation=deviation)


def test_signal_uses_previous_bars_own_band_and_source_prices() -> None:
    """交叉必须比较上一根自己的轨道，LONG使用下轨减ATR作为SL。"""
    previous = model_with_bands(100)
    current = model_with_bands(101)

    long_signal = detect_signal(95, previous, 99, current, 2.0)
    short_signal = detect_signal(105, previous, 102, current, 2.0)

    assert long_signal.direction == 1
    assert long_signal.entry == 99
    assert long_signal.take_profit == 101
    assert long_signal.stop_loss == 95
    assert short_signal.direction == -1
    assert short_signal.entry == 102
    assert short_signal.take_profit == 101
    assert short_signal.stop_loss == 107
    assert detect_signal(97, previous, 99, current, 2.0) is None
