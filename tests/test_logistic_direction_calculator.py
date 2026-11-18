"""逻辑回归方向计算器测试。"""

from types import SimpleNamespace

import numpy as np
import pytest

from core.indicators.calculators.logistic_direction_calculator import (
    FEATURE_NAMES,
    LogisticDirectionCalculator,
)


def make_bars(closes, volumes=None, seed: int = 0) -> list:
    """由收盘价序列构造合成K线。"""
    rng = np.random.default_rng(seed)
    if volumes is None:
        volumes = 1000 + np.abs(rng.normal(0, 200, len(closes)))
    bars = []
    for i, close in enumerate(closes):
        open_price = closes[i - 1] if i else close
        high = max(open_price, close) * 1.001
        low = min(open_price, close) * 0.999
        bars.append(SimpleNamespace(
            close_price=float(close),
            high_price=float(high),
            low_price=float(low),
            volume=float(volumes[i]),
        ))
    return bars


def make_random_walk(n: int, seed: int = 42) -> list:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0, 0.002, n)
    closes = 3000 * np.exp(np.cumsum(returns))
    return make_bars(closes, seed=seed)


def test_no_lookahead_prefix_matches_full_series() -> None:
    """前 N 根的概率输出必须与喂入全量序列时完全一致。"""
    bars = make_random_walk(600)
    cut = 400

    prefix_calc = LogisticDirectionCalculator(train_window=240)
    prefix_probs = [prefix_calc.update(bar).prob_up for bar in bars[:cut]]

    full_calc = LogisticDirectionCalculator(train_window=240)
    full_probs = [full_calc.update(bar).prob_up for bar in bars]

    for prefix, full in zip(prefix_probs, full_probs[:cut]):
        if prefix is None:
            assert full is None
        else:
            assert full == pytest.approx(prefix)


def test_probability_requires_feature_window_then_model() -> None:
    """特征窗口不足时输出 None，首次训练后开始输出概率。"""
    calc = LogisticDirectionCalculator(train_window=120, retrain_interval=10)
    bars = make_random_walk(300)
    probs = [calc.update(bar).prob_up for bar in bars]

    assert all(prob is None for prob in probs[:64])
    first_valid = next(i for i, prob in enumerate(probs) if prob is not None)
    assert first_valid >= 64
    assert all(0.0 <= prob <= 1.0 for prob in probs[first_valid:])


def test_retrain_interval_controls_train_count() -> None:
    """重训次数与K线数和间隔一致。"""
    calc = LogisticDirectionCalculator(train_window=120, retrain_interval=20)
    for bar in make_random_walk(320):
        calc.update(bar)

    assert calc.state.train_count > 0
    assert calc.state.train_count <= (320 - 64) // 20 + 1
    assert calc.state.train_samples <= 120


def test_constant_price_does_not_crash() -> None:
    """价格不变时标签全同，训练被跳过但不报错。"""
    calc = LogisticDirectionCalculator(train_window=120)
    bars = make_bars([3000.0] * 200, volumes=[1000.0] * 200)
    for bar in bars:
        state = calc.update(bar)

    assert state.prob_up is None
    assert state.train_count == 0


def test_regime_switch_learns_direction() -> None:
    """先跌后涨的混合结构里，模型应在上涨段给出高于 0.5 的概率。"""
    rng = np.random.default_rng(7)
    down = -0.0015 + rng.normal(0, 0.001, 260)
    up = 0.0015 + rng.normal(0, 0.001, 140)
    closes = 3000 * np.exp(np.cumsum(np.concatenate([down, up])))
    bars = make_bars(closes, seed=7)

    calc = LogisticDirectionCalculator(train_window=200, retrain_interval=10)
    for bar in bars:
        state = calc.update(bar)

    assert state.prob_up is not None
    assert state.prob_up > 0.5


def test_feature_names_count_matches_vector() -> None:
    """特征名数量与实际特征向量长度一致。"""
    calc = LogisticDirectionCalculator()
    bars = make_random_walk(100)
    for bar in bars:
        calc.update(bar)

    vector = calc._feature_vector(99)
    assert len(FEATURE_NAMES) == len(vector)
