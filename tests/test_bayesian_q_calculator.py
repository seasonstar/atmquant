# -*- coding: utf-8 -*-
"""Bayesian Q 六模型事件映射、手造状态及离在线一致性测试。"""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
import math

import pytest

import core.indicators.calculators.bayesian_q_calculator as bayesian_q_module
from core.indicators.calculators.bayesian_bbsma_calculator import BayesianBbsmaState
from core.indicators.calculators.bayesian_q_calculator import (
    MODEL_NAMES,
    BayesianQCalculator,
    BayesianQState,
    calculate_signals,
    compute,
)
from core.indicators.calculators.nqqe_calculator import NqqeState


EXPECTED_MODEL_NAMES = (
    "bayes_legacy",
    "bayes_fixed",
    "nqqe",
    "bayes_q_legacy",
    "bayes_q_fixed",
    "sma_momentum",
)


@dataclass(frozen=True)
class SyntheticBar:
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


def assert_float_or_nan(actual, expected, index, field_name) -> None:
    if math.isnan(expected):
        assert math.isnan(actual), (index, field_name)
    else:
        assert actual == pytest.approx(expected), (index, field_name)


def assert_states_equal(actual, expected) -> None:
    assert len(actual) == len(expected)
    for index, (actual_state, expected_state) in enumerate(zip(actual, expected)):
        assert isinstance(actual_state, BayesianQState)
        assert actual_state.signals == expected_state.signals, (index, "signals")
        for field in fields(BayesianBbsmaState):
            actual_value = getattr(actual_state.bayes, field.name)
            expected_value = getattr(expected_state.bayes, field.name)
            if isinstance(expected_value, bool):
                assert actual_value is expected_value, (index, field.name)
            else:
                assert_float_or_nan(actual_value, expected_value, index, field.name)
        for field in fields(NqqeState):
            actual_value = getattr(actual_state.nqqe, field.name)
            expected_value = getattr(expected_state.nqqe, field.name)
            if isinstance(expected_value, (bool, str)):
                assert actual_value == expected_value, (index, field.name)
            else:
                assert_float_or_nan(actual_value, expected_value, index, field.name)


def test_model_names_freeze_all_six_models_in_plan_order() -> None:
    assert MODEL_NAMES == EXPECTED_MODEL_NAMES


def test_long_mapping_accepts_strictly_dominant_sigma_and_sma_direction() -> None:
    bayes = BayesianBbsmaState(
        sma=100.0,
        sigma_up_legacy=0.8,
        sigma_down_legacy=0.2,
        sigma_up_fixed=0.7,
        sigma_down_fixed=0.3,
        long_legacy=True,
        long_fixed=True,
        ready=True,
    )
    nqqe = NqqeState(qqef=65.0, qqes=60.0, crossover=True, trend="up", ready=True)

    signals = calculate_signals(110.0, bayes, nqqe)

    assert signals == {
        "bayes_legacy": 1,
        "bayes_fixed": 1,
        "nqqe": 1,
        "bayes_q_legacy": 1,
        "bayes_q_fixed": 1,
        "sma_momentum": 1,
    }


def test_short_mapping_accepts_strictly_dominant_sigma_and_sma_direction() -> None:
    bayes = BayesianBbsmaState(
        sma=100.0,
        sigma_up_legacy=0.2,
        sigma_down_legacy=0.8,
        sigma_up_fixed=0.3,
        sigma_down_fixed=0.7,
        short_legacy=True,
        short_fixed=True,
        ready=True,
    )
    nqqe = NqqeState(qqef=35.0, qqes=40.0, crossunder=True, trend="down", ready=True)

    signals = calculate_signals(90.0, bayes, nqqe)

    assert signals == {
        "bayes_legacy": -1,
        "bayes_fixed": -1,
        "nqqe": -1,
        "bayes_q_legacy": -1,
        "bayes_q_fixed": -1,
        "sma_momentum": -1,
    }


def test_each_formula_independently_rejects_wrong_or_equal_sigma() -> None:
    nqqe = NqqeState(crossover=True, ready=True)
    bayes = BayesianBbsmaState(
        sigma_up_legacy=0.8,
        sigma_down_legacy=0.2,
        sigma_up_fixed=0.2,
        sigma_down_fixed=0.8,
        ready=True,
    )
    signals = calculate_signals(100.0, bayes, nqqe)
    assert signals["nqqe"] == 1
    assert signals["bayes_q_legacy"] == 1
    assert signals["bayes_q_fixed"] == 0

    equal_bayes = BayesianBbsmaState(
        sigma_up_legacy=0.5,
        sigma_down_legacy=0.5,
        sigma_up_fixed=0.5,
        sigma_down_fixed=0.5,
        ready=True,
    )
    equal_signals = calculate_signals(100.0, equal_bayes, nqqe)
    assert equal_signals["nqqe"] == 1
    assert equal_signals["bayes_q_legacy"] == 0
    assert equal_signals["bayes_q_fixed"] == 0


def test_probability_warmup_blocks_only_bayesian_q_filters() -> None:
    bayes = BayesianBbsmaState(
        sigma_up_legacy=1.0,
        sigma_down_legacy=0.0,
        sigma_up_fixed=1.0,
        sigma_down_fixed=0.0,
        ready=False,
    )
    nqqe = NqqeState(crossover=True, ready=True)

    signals = calculate_signals(100.0, bayes, nqqe)

    assert signals["nqqe"] == 1
    assert signals["bayes_q_legacy"] == 0
    assert signals["bayes_q_fixed"] == 0


def test_sma_momentum_returns_zero_for_equality_and_warmup() -> None:
    nqqe = NqqeState()
    equal_bayes = BayesianBbsmaState(sma=100.0, ready=True)
    warmup_bayes = BayesianBbsmaState(sma=math.nan, ready=False)

    assert calculate_signals(100.0, equal_bayes, nqqe)["sma_momentum"] == 0
    assert calculate_signals(100.0, warmup_bayes, nqqe)["sma_momentum"] == 0


class StubCalculator:
    """按调用顺序返回完整手造 state，并记录每次真实 update 调用。"""

    def __init__(self, states):
        self._states = list(states)
        self.calls = []

    def update(self, bar):
        self.calls.append(bar)
        return self._states[len(self.calls) - 1]


def test_update_updates_each_component_once_and_does_not_persist_events(
    monkeypatch,
) -> None:
    crossing_bayes = BayesianBbsmaState(
        sigma_up_legacy=0.8,
        sigma_down_legacy=0.2,
        sigma_up_fixed=0.7,
        sigma_down_fixed=0.3,
        long_legacy=True,
        long_fixed=True,
        ready=True,
    )
    crossing_nqqe = NqqeState(crossover=True, ready=True)
    bayes_stub = StubCalculator([crossing_bayes, BayesianBbsmaState()])
    nqqe_stub = StubCalculator([crossing_nqqe, NqqeState()])
    monkeypatch.setattr(
        bayesian_q_module, "BayesianBbsmaCalculator", lambda: bayes_stub
    )
    monkeypatch.setattr(bayesian_q_module, "NqqeCalculator", lambda: nqqe_stub)
    calculator = BayesianQCalculator()
    first_bar = make_bar(100.0, 0)
    second_bar = make_bar(101.0, 1)

    first = calculator.update(first_bar)
    second = calculator.update(second_bar)

    assert bayes_stub.calls == [first_bar, second_bar]
    assert nqqe_stub.calls == [first_bar, second_bar]
    assert first.bayes is crossing_bayes
    assert first.nqqe is crossing_nqqe
    assert first.signals["bayes_legacy"] == 1
    assert first.signals["bayes_fixed"] == 1
    assert first.signals["nqqe"] == 1
    assert first.signals["bayes_q_legacy"] == 1
    assert first.signals["bayes_q_fixed"] == 1
    assert second.signals == {model: 0 for model in EXPECTED_MODEL_NAMES}


def test_class_compute_direct_api_uses_fresh_sequential_calculator() -> None:
    bars = make_bars(
        100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60)
    )
    calculator = BayesianQCalculator()
    expected = [calculator.update(bar) for bar in bars]

    first = BayesianQCalculator.compute(bars)
    second = BayesianQCalculator.compute(bars)

    assert_states_equal(first, expected)
    assert_states_equal(second, expected)


def test_compute_matches_sequential_online_updates() -> None:
    bars = make_bars(
        100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60)
    )
    calculator = BayesianQCalculator()

    online_states = [calculator.update(bar) for bar in bars]

    assert_states_equal(online_states, compute(bars))
    assert all(tuple(state.signals) == EXPECTED_MODEL_NAMES for state in online_states)


def test_every_prefix_matches_the_same_prefix_of_full_compute() -> None:
    bars = make_bars(
        100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60)
    )
    full_states = compute(bars)

    for prefix_length in range(len(bars) + 1):
        assert_states_equal(compute(bars[:prefix_length]), full_states[:prefix_length])


def test_changing_future_bars_does_not_change_historical_states() -> None:
    bars = make_bars(
        100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60)
    )
    cutoff = 43
    expected_history = compute(bars)[:cutoff]
    future_bars = [
        make_bar(1000.0 + (i % 5) * 100.0, i) for i in range(cutoff, len(bars))
    ]

    mutated_states = compute(bars[:cutoff] + future_bars)

    assert_states_equal(mutated_states[:cutoff], expected_history)


def test_constant_prices_do_not_raise_or_create_any_model_event() -> None:
    states = compute(make_bars([42.0] * 60))

    assert all(state.signals == {model: 0 for model in EXPECTED_MODEL_NAMES} for state in states)
    assert all(not state.nqqe.ready for state in states)
    assert all(state.bayes.ready for state in states[38:])
