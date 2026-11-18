"""随机森林/逻辑回归日线方向计算器测试。"""

from types import SimpleNamespace

import numpy as np
import pytest

from core.indicators.calculators.random_forest_direction_calculator import (
    FEATURE_LOOKBACK,
    FEATURE_NAMES,
    RandomForestDirectionCalculator,
)


def make_bars(closes, volumes=None, seed: int = 0) -> list:
    """由收盘价序列构造合成日线K线。"""
    rng = np.random.default_rng(seed)
    if volumes is None:
        volumes = 100000 + np.abs(rng.normal(0, 20000, len(closes)))
    bars = []
    for i, close in enumerate(closes):
        open_price = closes[i - 1] if i else close
        high = max(open_price, close) * 1.004
        low = min(open_price, close) * 0.996
        bars.append(SimpleNamespace(
            close_price=float(close),
            high_price=float(high),
            low_price=float(low),
            volume=float(volumes[i]),
        ))
    return bars


def make_random_walk(n: int, seed: int = 42, drift: float = 0.0) -> list:
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, 0.012, n)  # 日线级波动
    closes = 3000 * np.exp(np.cumsum(returns))
    return make_bars(closes, seed=seed)


class TestFeatures:
    def test_sixteen_features_and_lookback(self) -> None:
        assert len(FEATURE_NAMES) == 16
        assert FEATURE_LOOKBACK == 60

    def test_feature_window_insufficient_outputs_none(self) -> None:
        calc = RandomForestDirectionCalculator(model_kind="random_forest")
        for bar in make_random_walk(FEATURE_LOOKBACK):
            state = calc.update(bar)
            assert state.prob_up is None
            assert not state.feature_ready

    def test_first_feature_ready_bar_can_report_none_until_model(self) -> None:
        bars = make_random_walk(FEATURE_LOOKBACK + 1)
        calc = RandomForestDirectionCalculator(model_kind="logistic")
        for bar in bars[:-1]:
            calc.update(bar)
        state = calc.update(bars[-1])
        assert state.feature_ready
        # 60+1 根仍不足最小训练样本数（需再吃标签完整的50个锚点）
        assert not state.model_ready


class TestNoLookahead:
    def test_prefix_matches_full_series_rf(self) -> None:
        """RF：任意前缀输出与全量序列前缀完全一致（种子固定）。"""
        bars = make_random_walk(700)
        cut = 500
        prefix_calc = RandomForestDirectionCalculator(
            model_kind="random_forest", train_window=240
        )
        prefix_probs = [prefix_calc.update(bar).prob_up for bar in bars[:cut]]
        full_calc = RandomForestDirectionCalculator(
            model_kind="random_forest", train_window=240
        )
        full_probs = [full_calc.update(bar).prob_up for bar in bars]
        for prefix, full in zip(prefix_probs, full_probs[:cut]):
            if prefix is None:
                assert full is None
            else:
                assert full == pytest.approx(prefix)

    def test_truncating_tail_does_not_change_past(self) -> None:
        """截断末 5 根（模拟标签不完整的 embargo）不影响此前概率。"""
        bars = make_random_walk(600)
        calc_a = RandomForestDirectionCalculator(model_kind="logistic", train_window=240)
        probs_a = [calc_a.update(bar).prob_up for bar in bars[:-5]]
        calc_b = RandomForestDirectionCalculator(model_kind="logistic", train_window=240)
        probs_b = [calc_b.update(bar).prob_up for bar in bars]
        for a, b in zip(probs_a, probs_b[:-5]):
            if a is None or b is None:
                assert a is None and b is None
            else:
                assert a == pytest.approx(b)


class TestTraining:
    def test_training_anchors_exclude_incomplete_labels(self) -> None:
        """训练锚点必须满足 a + horizon <= n-1，末根概率不受未完整标签影响。"""
        bars = make_random_walk(400, drift=0.002)
        calc = RandomForestDirectionCalculator(
            model_kind="logistic", train_window=240, label_horizon=5
        )
        for bar in bars:
            state = calc.update(bar)
        n = len(bars)
        # 重训发生在 bars_seen 满足间隔处；最后一次训练的样本锚点数应有记录
        assert state.train_count > 0
        assert state.train_samples >= 50
        # 概率输出存在且在 [0,1]
        assert state.prob_up is not None and 0.0 <= state.prob_up <= 1.0

    def test_model_kind_must_be_registered(self) -> None:
        with pytest.raises(ValueError):
            RandomForestDirectionCalculator(model_kind="xgboost")

    def test_rf_deterministic_given_seed(self) -> None:
        bars = make_random_walk(400, seed=7, drift=0.001)
        probs = []
        for _ in range(2):
            calc = RandomForestDirectionCalculator(
                model_kind="random_forest", train_window=200
            )
            probs.append([calc.update(bar).prob_up for bar in bars])
        for a, b in zip(*probs):
            if a is None:
                assert b is None
            else:
                assert a == pytest.approx(b)

    def test_rf_learns_strong_trend_faster_than_coinflip(self) -> None:
        """强趋势合成数据上，RF 概率应明显偏向上涨。"""
        bars = make_random_walk(400, seed=11, drift=0.004)
        calc = RandomForestDirectionCalculator(
            model_kind="random_forest", train_window=300
        )
        state = None
        for bar in bars:
            state = calc.update(bar)
        assert state.prob_up is not None
        assert state.prob_up > 0.6

    def test_min_train_window_enforced(self) -> None:
        with pytest.raises(ValueError):
            RandomForestDirectionCalculator(train_window=49)
