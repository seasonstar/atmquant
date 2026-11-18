# -*- coding: utf-8 -*-
"""Bayesian BBSMA 双公式与逐根状态测试。"""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from itertools import product
import math

import pytest

from core.indicators.calculators.bayesian_bbsma_calculator import (
    BayesianBbsmaCalculator,
    BayesianBbsmaState,
    compute,
    legacy_nz,
    legacy_ratio,
    prime_fixed,
    prime_legacy,
    sigma_fixed,
    sigma_legacy,
)


@dataclass(frozen=True)
class SyntheticBar:
    """与计算器消费的 BarData 字段保持一致。"""

    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    datetime: datetime


def make_bar(close: float, index: int) -> SyntheticBar:
    open_price = close - 0.25
    return SyntheticBar(
        open_price=open_price,
        high_price=max(open_price, close) + 0.5,
        low_price=min(open_price, close) - 0.5,
        close_price=close,
        volume=1000.0 + index,
        datetime=datetime(2026, 1, 1, tzinfo=timezone.utc)
        + timedelta(hours=index),
    )


def make_bars(closes) -> list[SyntheticBar]:
    return [make_bar(float(close), index) for index, close in enumerate(closes)]


def assert_states_equal(actual, expected) -> None:
    assert len(actual) == len(expected)
    for index, (actual_state, expected_state) in enumerate(zip(actual, expected)):
        assert isinstance(actual_state, BayesianBbsmaState)
        for field in fields(BayesianBbsmaState):
            actual_value = getattr(actual_state, field.name)
            expected_value = getattr(expected_state, field.name)
            if isinstance(expected_value, bool):
                assert actual_value is expected_value, (index, field.name)
            elif math.isnan(expected_value):
                assert math.isnan(actual_value), (index, field.name)
            else:
                assert actual_value == pytest.approx(expected_value), (
                    index,
                    field.name,
                )


def test_legacy_nz_and_ratio_handle_na_and_zero_denominators() -> None:
    assert legacy_nz(math.nan) == 0.0
    assert legacy_nz(None) == 0.0
    assert legacy_nz(1.25) == 1.25
    assert legacy_nz(math.nan, 2.5) == 2.5
    assert legacy_ratio(2.0, 4.0) == 0.5
    assert math.isnan(legacy_ratio(0.0, 0.0))
    assert math.isnan(legacy_ratio(1.0, 0.0))
    assert math.isnan(legacy_ratio(math.nan, 1.0))


def test_sigma_hand_arithmetic_and_zero_first_factor() -> None:
    # 左结合链为 0.5**2 * 0.5**2，补项为 0.5**3。
    assert sigma_legacy(0.5, 0.5, 0.5) == pytest.approx(0.1875)
    assert sigma_fixed(0.5, 0.5, 0.5) == pytest.approx(0.5)

    # 原链在 0/0 处产生 na，整个表达式经 nz 归零；修正总分母也为零。
    assert sigma_legacy(0.0, 0.5, 0.5) == 0.0
    assert sigma_fixed(0.0, 0.5, 0.5) == 0.0


def test_prime_hand_arithmetic_and_zero_sigma_down() -> None:
    # 原始左结合链为 sigmaUp**2，再加 (1-sigmaDown)*(1-sigmaUp)。
    assert prime_legacy(0.5, 0.8) == pytest.approx(0.74)
    assert prime_fixed(0.5, 0.8) == pytest.approx(0.8)
    assert prime_legacy(0.0, 0.8) == 0.0
    assert prime_fixed(0.0, 0.8) == 0.0


def test_original_helpers_can_leave_probability_bounds() -> None:
    assert sigma_legacy(2.0, 2.0, 2.0) == pytest.approx(15.0)
    assert prime_legacy(2.0, 2.0) == pytest.approx(5.0)


def test_fixed_helpers_are_bounded_for_finite_probability_inputs() -> None:
    values = (0.0, 0.2, 0.5, 0.9, 1.0)
    for a, b, c in product(values, repeat=3):
        value = sigma_fixed(a, b, c)
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0

    for sigma_down, sigma_up in product(values, repeat=2):
        value = prime_fixed(sigma_down, sigma_up)
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0


def test_small_window_states_match_hand_computed_ratios_and_events() -> None:
    # period=2、lookback=2、stddev_mult=0 时，三组特征都等于 close 与 SMA 的比较。
    # 第2/3根分别上涨、下跌，因此第3根 up=down=1/2；第4根相等使窗口只剩 down。
    states = compute(
        make_bars([1.0, 3.0, 2.0, 2.0, 3.0]),
        period=2,
        lookback=2,
        stddev_mult=0.0,
    )

    assert not states[0].ready
    assert not states[1].ready
    assert states[2].ready
    assert states[2].sma == pytest.approx(2.5)
    assert states[2].basis == states[2].sma
    assert states[2].upper == states[2].basis
    assert states[2].sigma_down_legacy == pytest.approx(0.1875)
    assert states[2].sigma_up_legacy == pytest.approx(0.1875)
    assert states[2].sigma_down_fixed == pytest.approx(0.5)
    assert states[2].sigma_up_fixed == pytest.approx(0.5)
    assert states[2].prime_legacy == pytest.approx(0.6953125)
    assert states[2].prime_fixed == pytest.approx(0.5)
    assert not states[2].long_legacy
    assert not states[2].short_legacy

    # prime 从 >0.15 降为 0，触发两组 short。
    assert states[3].sigma_down_legacy == 0.0
    assert states[3].sigma_up_legacy == 1.0
    assert states[3].prime_legacy == 0.0
    assert states[3].prime_fixed == 0.0
    assert states[3].short_legacy
    assert states[3].short_fixed
    assert not states[3].long_legacy
    assert not states[3].long_fixed

    # sigmaUp 从 1 降为 0，触发两组 long；prime 前值已为零，不能重复 short。
    assert states[4].sigma_down_legacy == 1.0
    assert states[4].sigma_up_legacy == 0.0
    assert states[4].long_legacy
    assert states[4].long_fixed
    assert not states[4].short_legacy
    assert not states[4].short_fixed


def test_default_rolling_windows_and_population_stdev() -> None:
    states = compute(make_bars(range(1, 41)))

    assert math.isnan(states[18].sma)
    assert all(not state.ready for state in states[:38])
    assert states[38].ready

    # 1..20 与 2..21 的总体方差都为 33.25；第二窗口证明最旧值已移出。
    assert states[19].sma == pytest.approx(10.5)
    assert states[19].basis == states[19].sma
    assert states[19].upper == pytest.approx(10.5 + 2.5 * math.sqrt(33.25))
    assert states[20].sma == pytest.approx(11.5)
    assert states[20].upper == pytest.approx(11.5 + 2.5 * math.sqrt(33.25))
    assert all(state.basis == state.sma for state in states[19:])


def test_compute_matches_sequential_online_updates() -> None:
    bars = make_bars(100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60))
    calculator = BayesianBbsmaCalculator()

    online_states = [calculator.update(bar) for bar in bars]

    assert_states_equal(online_states, compute(bars))


def test_every_prefix_matches_the_same_prefix_of_full_compute() -> None:
    bars = make_bars(100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60))
    full_states = compute(bars)

    for prefix_length in range(len(bars) + 1):
        assert_states_equal(compute(bars[:prefix_length]), full_states[:prefix_length])


def test_changing_future_bars_does_not_change_historical_states() -> None:
    bars = make_bars(100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60))
    cutoff = 43
    expected_history = compute(bars)[:cutoff]
    future_bars = [make_bar(1000.0 + (i % 5) * 100.0, i) for i in range(cutoff, len(bars))]

    mutated_states = compute(bars[:cutoff] + future_bars)

    assert_states_equal(mutated_states[:cutoff], expected_history)


def test_constant_prices_do_not_raise_or_create_nan_driven_events() -> None:
    states = compute(make_bars([42.0] * 60))

    assert all(
        not (state.long_legacy or state.short_legacy or state.long_fixed or state.short_fixed)
        for state in states
    )
    assert all(state.ready for state in states[38:])
    for state in states[38:]:
        assert state.sma == pytest.approx(42.0)
        assert state.basis == pytest.approx(42.0)
        assert state.upper == pytest.approx(42.0)
        assert state.sigma_up_legacy == 0.0
        assert state.sigma_down_legacy == 0.0
        assert state.prime_legacy == 0.0
        assert state.sigma_up_fixed == 0.0
        assert state.sigma_down_fixed == 0.0
        assert state.prime_fixed == 0.0
