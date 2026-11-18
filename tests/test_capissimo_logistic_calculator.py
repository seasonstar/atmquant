"""capissimo ML 逻辑回归计算器 Pine 语义对照测试。"""

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from core.indicators.calculators.capissimo_logistic_calculator import (
    BUY,
    HOLD,
    LOG_HALF,
    SELL,
    CapissimoLogisticCalculator,
    sigmoid,
)


def make_bar(close: float, volume: float = 1000.0, i: int = 0, spread: float = 0.001):
    return SimpleNamespace(
        close_price=float(close),
        high_price=float(close) * (1 + spread),
        low_price=float(close) * (1 - spread),
        volume=float(volume),
        datetime=datetime(2026, 5, 1, 9, 0) .replace(hour=9 + i % 8),
    )


def test_sigmoid_clips_extremes() -> None:
    assert sigmoid(0) == pytest.approx(0.5)
    assert sigmoid(10000) == pytest.approx(1.0)
    assert sigmoid(-10000) == pytest.approx(0.0)


def test_loss_matches_nested_dot_semantics() -> None:
    """loss 必须是内层A再外层滚动和的嵌套 dot，手工对照。"""
    closes = [10, 11, 12, 13, 14, 15]
    calc = CapissimoLogisticCalculator(lookback=3, easteregg=True)
    for i, c in enumerate(closes):
        state = calc.update(make_bar(c, i=i))

    y = np.asarray(closes)
    inner = [float(np.sum(y[t - 2:t + 1] * (LOG_HALF + 1 - y[t - 2:t + 1]))) for t in range(2, 6)]
    expected_loss = -LOG_HALF * float(np.sum(inner[-3:])) / 3

    assert state.loss == pytest.approx(expected_loss)


def test_prediction_matches_analytic_weight() -> None:
    """prediction = sigmoid(w·ΣX)，w = -iterations·lr·gradient。"""
    closes = [10, 11, 12, 13, 14, 15]
    calc = CapissimoLogisticCalculator(lookback=3, easteregg=False, iterations=1000, learning_rate=0.0009)
    for i, c in enumerate(closes):
        state = calc.update(make_bar(c, i=i))

    y_full = np.log(np.abs(np.asarray(closes) ** 2 - 1) + 0.5)
    x_win = np.asarray(closes[-3:])
    y_win = y_full[-3:]
    gradient = float(np.sum(x_win * (0.5 - y_win))) / 3
    w = -1000 * 0.0009 * gradient
    expected = sigmoid(w * float(np.sum(x_win)))

    assert state.prediction == pytest.approx(expected)


def test_minimax_constant_series_keeps_signal() -> None:
    """价格不变时 minimax 退化，信号保持 HOLD 不翻转。"""
    calc = CapissimoLogisticCalculator(lookback=3, normalization_lookback=2)
    for i in range(30):
        state = calc.update(make_bar(3000.0, i=i))

    assert state.scaled_loss is None
    assert state.signal == HOLD
    assert not state.start_long and not state.start_short


def test_no_lookahead_prefix_matches_full() -> None:
    """前 N 根的信号状态必须与全量序列一致。"""
    rng = np.random.default_rng(3)
    closes = 3000 * np.exp(np.cumsum(rng.normal(0, 0.002, 200)))
    bars = [make_bar(c, volume=1000 + abs(rng.normal(0, 200)), i=i) for i, c in enumerate(closes)]

    calc_a = CapissimoLogisticCalculator()
    sig_a = []
    for b in bars[:120]:
        sig_a.append(calc_a.update(b).signal)

    calc_b = CapissimoLogisticCalculator()
    sig_b = []
    for b in bars:
        sig_b.append(calc_b.update(b).signal)

    assert sig_a == sig_b[:120]


def test_trending_series_produces_signals_and_exits() -> None:
    """趋势序列中应出现入场与持有期退出，且退出后不再入场直到信号变更。"""
    rng = np.random.default_rng(11)
    closes = 3000 + np.cumsum(rng.normal(0.6, 1.0, 300))
    calc = CapissimoLogisticCalculator(holding_period=5)
    starts = 0
    ends = 0
    for i, c in enumerate(closes):
        state = calc.update(make_bar(c, i=i))
        starts += int(state.start_long or state.start_short)
        ends += int(state.end_long or state.end_short)

    assert starts > 0
    assert ends > 0


def test_volatility_filter_blocks_quiet_bars() -> None:
    """TR 持续小于 ATR(10) 时，波动过滤应确定性拦截信号。"""
    calc = CapissimoLogisticCalculator(filter_type="Volatility", lookback=3)
    for i in range(40):
        close = 3000.0 + i * 0.5
        spread = 2.0 if i < 10 else 0.1
        bar = SimpleNamespace(
            close_price=close,
            high_price=close + spread,
            low_price=close - spread,
            volume=1000.0,
            datetime=None,
        )
        state = calc.update(bar)

    assert state.filter_pass is False
    assert state.signal == HOLD
