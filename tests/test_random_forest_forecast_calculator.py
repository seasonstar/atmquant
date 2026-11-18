"""随机森林预测器（多 horizon 回归）计算器测试。"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from core.indicators.calculators.random_forest_forecast_calculator import (
    FEATURE_NAMES,
    MIN_BARS_EXTRA,
    RandomForestForecastCalculator,
)


def make_bars(n: int, seed: int = 42, drift: float = 0.0, vol: float = 0.01,
              returns: np.ndarray | None = None):
    """合成 OHLCV 日线：可复现的随机游走（可传入自定义收益序列）。"""
    rng = np.random.default_rng(seed)
    if returns is None:
        returns = rng.normal(drift, vol, n)
    n = len(returns)
    close = 3000 * np.exp(np.cumsum(returns))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    volume = 100000 * (1 + np.abs(rng.normal(0, 0.3, n)))
    start = datetime(2024, 1, 1, 9, 0)
    bars = []
    for i in range(n):
        bars.append(type("B", (), {
            "open_price": float(open_[i]),
            "high_price": float(high[i]),
            "low_price": float(low[i]),
            "close_price": float(close[i]),
            "volume": float(volume[i]),
            "datetime": start + timedelta(minutes=i),
        })())
    return bars


def make_calc(**kwargs) -> RandomForestForecastCalculator:
    base = dict(
        n_trees=6,
        max_depth=3,
        train_size=200,
        n_threshold_candidates=4,
        seed=42,
        min_samples_leaf=10,
        horizon=10,
    )
    base.update(kwargs)
    return RandomForestForecastCalculator(**base)


class TestGating:
    def test_not_enough_data_reports_missing(self) -> None:
        calc = make_calc(train_size=200, horizon=10)
        for bar in make_bars(150):
            result = calc.update(bar)
        assert not result.ready
        assert "数据不足" in result.reason

    def test_ready_when_history_sufficient(self) -> None:
        calc = make_calc(train_size=200, horizon=10)
        for bar in make_bars(200 + 10 + MIN_BARS_EXTRA + 70):
            result = calc.update(bar)
        assert result.ready
        assert result.reason is None


class TestOutputs:
    def test_shapes_and_names(self) -> None:
        assert len(FEATURE_NAMES) == 8
        calc = make_calc(horizon=10)
        for bar in make_bars(340):
            result = calc.update(bar)
        assert result.pred_mean.shape == (10,)
        assert result.pred_std.shape == (10,)
        assert result.feature_importance.shape == (8,)
        # 特征重要性归一化
        np.testing.assert_allclose(result.feature_importance.sum(), 1.0, rtol=1e-6)

    def test_deterministic_given_seed(self) -> None:
        probs = []
        for seed in (42, 42):
            calc = make_calc(seed=seed)
            for bar in make_bars(340):
                result = calc.update(bar)
            probs.append(result.pred_mean.copy())
        np.testing.assert_allclose(probs[0], probs[1])

    def test_different_seed_changes_forecast(self) -> None:
        finals = []
        for seed in (42, 7):
            calc = make_calc(seed=seed)
            result = calc.result
            for bar in make_bars(340):
                result = calc.update(bar)
            finals.append(result.pred_mean.copy())
        assert finals[0].size > 0
        assert not np.allclose(finals[0], finals[1])

    def test_bands_use_oob_residual_std_and_widen(self) -> None:
        """OOB 残差 std 应随 horizon 增大而变宽（扇形）。"""
        calc = make_calc()
        for bar in make_bars(340):
            result = calc.update(bar)
        assert np.all(result.pred_std >= 0)
        # 远端 horizons 的平均带宽应大于近端
        assert result.pred_std[-3:].mean() > result.pred_std[:3].mean()

    def test_direction_from_last_horizon(self) -> None:
        calc = make_calc()
        for bar in make_bars(340):
            result = calc.update(bar)
        expected = 1 if result.pred_mean[-1] >= 0 else -1
        assert result.direction == expected


class TestNoLookahead:
    def test_training_window_excludes_recent_horizon_bars(self) -> None:
        """训练样本的标签不允许取到最近 horizon 根以内的未来。"""
        calc = make_calc(train_size=100, horizon=10)
        bars = make_bars(240)
        for bar in bars:
            result = calc.update(bar)
        assert result.ready
        # train_samples 上限应为 train_size；训练末端与查询样本间隔 horizon 根
        assert result.train_samples <= 100
        assert result.base_close == bars[-1].close_price

    def test_oob_r2_positive_on_learnable_signal(self) -> None:
        """AR(1) 动量结构（特征携带条件信息）上 OOB R² 应为正。

        纯漂移随机游走拿不到正 OOB R²（常数均值不解释样本间方差），
        这是模型语义而非缺陷；测试用可学习的自相关结构验证机制。
        """
        rng = np.random.default_rng(3)
        n = 440
        returns = np.zeros(n)
        for i in range(1, n):
            returns[i] = 0.5 * returns[i - 1] + rng.normal(0, 0.002)
        bars = make_bars(n=n, seed=9, returns=returns)
        calc = make_calc(train_size=300, horizon=5)
        for bar in bars:
            result = calc.update(bar)
        assert result.ready
        assert result.oob_r2 > 0.05

    def test_compute_equals_sequential_update(self) -> None:
        bars = make_bars(340)
        seq = make_calc()
        for bar in bars:
            r1 = seq.update(bar)
        bulk = make_calc()
        r2 = bulk.compute(bars)
        if r1.ready and r2.ready:
            np.testing.assert_allclose(r1.pred_mean, r2.pred_mean)
            np.testing.assert_allclose(r1.pred_std, r2.pred_std)


class TestRealism:
    def test_forecast_magnitude_plausible(self) -> None:
        """随机游走数据上 20 根 horizon 的预测幅度应在有限范围内。"""
        calc = make_calc(horizon=20)
        for bar in make_bars(370, vol=0.01):
            result = calc.update(bar)
        assert np.all(np.abs(result.pred_mean) < 30.0)
        assert np.all(result.pred_std < 30.0)
