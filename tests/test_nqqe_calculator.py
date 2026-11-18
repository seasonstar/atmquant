# -*- coding: utf-8 -*-
"""nQQE 的独立手算、递推、交叉与前缀一致性测试。"""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
import math

import pytest

from core.indicators.calculators.nqqe_calculator import (
    NqqeCalculator,
    NqqeState,
    calculate_qqes,
    compute,
    legacy_crossover,
    legacy_crossunder,
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


def assert_states_equal(actual, expected) -> None:
    assert len(actual) == len(expected)
    for index, (actual_state, expected_state) in enumerate(zip(actual, expected)):
        assert isinstance(actual_state, NqqeState)
        for field in fields(NqqeState):
            actual_value = getattr(actual_state, field.name)
            expected_value = getattr(expected_state, field.name)
            if isinstance(expected_value, (bool, str)):
                assert actual_value == expected_value, (index, field.name)
            elif math.isnan(expected_value):
                assert math.isnan(actual_value), (index, field.name)
            else:
                assert actual_value == pytest.approx(expected_value), (
                    index,
                    field.name,
                )


def test_wilder_rsi_and_ema_seeds_match_hand_calculation() -> None:
    # 14 次 +1 后，首个涨/跌 RMA 分别为 1/0，故 RSI=QQEF=100。
    # 第 16 根跌 1：avgGain=13/14、avgLoss=1/14，RSI=100-100/(1+13)=650/7。
    # EMA5 的 alpha=1/3，因此 QQEF=100+(650/7-100)/3=2050/21。
    states = compute(make_bars(list(range(1, 16)) + [14, 13]))

    assert all(math.isnan(state.rsi) for state in states[:14])
    assert all(math.isnan(state.qqef) for state in states[:14])
    assert states[14].rsi == pytest.approx(100.0)
    assert states[14].qqef == pytest.approx(100.0)
    assert states[14].qqes == 0.0
    assert not states[14].ready  # 首个有效 TR 尚未出现，ATRRSI 仍为 na。
    assert not states[14].crossover
    assert not states[14].crossunder

    assert states[15].rsi == pytest.approx(92.85714285714286)
    assert states[15].qqef == pytest.approx(97.61904761904762)
    assert states[15].ready

    # 第 17 根再跌 1：avgGain=169/196、avgLoss=27/196，RSI=4225/49；
    # QQEF=2050/21+(4225/49-2050/21)/3=41375/441。
    assert states[16].rsi == pytest.approx(86.22448979591837)
    assert states[16].qqef == pytest.approx(93.82086167800453)


def test_wwma_atrrsi_qqes_recursion_and_crossunder_match_hand_calculation() -> None:
    states = compute(make_bars(list(range(1, 16)) + [14, 13]))

    # 第 16 根 TR=50/21，WWMA=TR/14=25/147，ATRRSI=WWMA/14=25/2058。
    # QDN=2050/21-4.236*(25/2058)，经第三分支写入 QQES。
    assert states[15].qqes == pytest.approx(97.56758989310009)
    assert not states[15].crossunder

    # 第 17 根 TR=1675/441：
    # WWMA=(1675/441)/14+(13/14)*(25/147)=1325/3087；
    # ATRRSI=WWMA/14+(13/14)*(25/2058)=3625/86436。
    # QUP=41375/441+4.236*(3625/86436)，且 QUP<prev，故走第一分支。
    assert states[16].qqes == pytest.approx(93.9985133509186)
    assert states[16].crossunder
    assert not states[16].crossover
    assert states[16].trend == "up"  # 交叉不修改仅由 QQEF>60 决定的趋势。


def test_crossover_accepts_previous_equality_and_uses_zero_qqes_seed() -> None:
    # 14 次 -1 后 RSI=QQEF=0、QQES=0。随后涨 1：
    # RSI=50/7，QQEF=50/21，ATRRSI=25/2058，QQES=QDN。
    # 当前 QQEF>QQES，且前值 0<=0，必须在同一根触发上穿。
    states = compute(make_bars(list(range(15, 0, -1)) + [2]))

    assert states[14].rsi == 0.0
    assert states[14].qqef == 0.0
    assert states[14].qqes == 0.0
    assert not states[14].crossover
    assert states[15].qqef == pytest.approx(2.380952380952381)
    assert states[15].qqes == pytest.approx(2.329494655004859)
    assert states[15].crossover
    assert not states[15].crossunder
    assert states[15].trend == "down"  # 上穿事件不覆盖 QQEF<40 的趋势描述。


@pytest.mark.parametrize(
    (
        "qqef",
        "previous_qqef",
        "atrrsi",
        "previous_qqes",
        "expected",
        "branch",
    ),
    [
        (55.0, 50.0, 1.0, 60.0, 59.236, "QUP < prev"),
        (55.0, 45.0, 10.0, 50.0, 12.64, "QQEF upward cross"),
        (55.0, 60.0, 1.0, 50.0, 50.764, "QDN > prev"),
        (45.0, 55.0, 10.0, 50.0, 87.36, "QQEF downward cross"),
        (55.0, 60.0, 10.0, 50.0, 50.0, "fallback"),
        (10.0, 20.0, 1.0, 0.0, 5.764, "nz(prev) zero"),
    ],
)
def test_qqes_four_branches_fallback_and_zero_previous(
    qqef, previous_qqef, atrrsi, previous_qqes, expected, branch
) -> None:
    assert calculate_qqes(qqef, previous_qqef, atrrsi, previous_qqes) == (
        pytest.approx(expected)
    ), branch


def test_qqes_equality_and_nan_comparisons_fall_back_without_raising() -> None:
    # ATRRSI=0 时 QUP=QDN=QQEF=prev，严格 </> 均不成立。
    assert calculate_qqes(50.0, 50.0, 0.0, 50.0) == 50.0
    # QDN=prev 时第三分支也不能按 >= 误触发；结果沿用 prev。
    assert calculate_qqes(55.0, 60.0, 5.0 / 4.236, 50.0) == pytest.approx(50.0)
    assert calculate_qqes(math.nan, math.nan, math.nan, math.nan) == 0.0
    assert calculate_qqes(math.nan, math.nan, math.nan, 12.5) == 12.5


@pytest.mark.parametrize(
    ("previous_qqef", "previous_qqes", "expected"),
    [(49.0, 50.0, True), (50.0, 50.0, True), (51.0, 50.0, False)],
)
def test_legacy_crossover_uses_less_than_or_equal_previous(
    previous_qqef, previous_qqes, expected
) -> None:
    assert legacy_crossover(51.0, 50.0, previous_qqef, previous_qqes) is expected


@pytest.mark.parametrize(
    ("previous_qqef", "previous_qqes", "expected"),
    [(51.0, 50.0, True), (50.0, 50.0, True), (49.0, 50.0, False)],
)
def test_legacy_crossunder_uses_greater_than_or_equal_previous(
    previous_qqef, previous_qqes, expected
) -> None:
    assert legacy_crossunder(49.0, 50.0, previous_qqef, previous_qqes) is expected


@pytest.mark.parametrize(
    "values",
    [
        (math.nan, 50.0, 49.0, 50.0),
        (51.0, math.nan, 49.0, 50.0),
        (51.0, 50.0, math.nan, 50.0),
        (51.0, 50.0, 49.0, math.nan),
    ],
)
def test_nan_never_creates_cross_events(values) -> None:
    assert not legacy_crossover(*values)
    assert not legacy_crossunder(*values)


def test_class_compute_direct_api_uses_fresh_sequential_calculator() -> None:
    bars = make_bars(list(range(1, 16)) + [14, 13])
    calculator = NqqeCalculator()
    expected = [calculator.update(bar) for bar in bars]

    first = NqqeCalculator.compute(bars)
    second = NqqeCalculator.compute(bars)

    assert_states_equal(first, expected)
    assert_states_equal(second, expected)
    assert first[15].qqes == pytest.approx(97.56758989310009)
    assert first[16].crossunder


def test_compute_matches_sequential_online_updates() -> None:
    bars = make_bars(
        100.0 + 4.0 * math.sin(i * 0.37) + (i % 7) * 0.1 for i in range(60)
    )
    calculator = NqqeCalculator()

    online_states = [calculator.update(bar) for bar in bars]

    assert_states_equal(online_states, compute(bars))


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


def test_constant_prices_keep_rsi_na_and_never_create_events() -> None:
    states = compute(make_bars([42.0] * 60))

    assert all(math.isnan(state.rsi) for state in states)
    assert all(math.isnan(state.qqef) for state in states)
    assert all(state.qqes == 0.0 for state in states)
    assert all(state.trend == "neutral" for state in states)
    assert all(not state.ready for state in states)
    assert all(not (state.crossover or state.crossunder) for state in states)
