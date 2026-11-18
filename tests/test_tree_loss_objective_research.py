"""树模型损失函数改造研究的梯度、冻结与选型测试。"""

import numpy as np
import pandas as pd
import pytest

import scripts.tree_loss_objective_research as research
from scripts.lightgbm_factor_selection_research import frozen_model_params


def synthetic_training(n_dates: int = 400, n_stocks: int = 12) -> pd.DataFrame:
    dates = pd.bdate_range("2021-01-04", periods=n_dates)[::5]
    rng = np.random.default_rng(7)
    rows = []
    for day_index, date in enumerate(dates):
        shock = rng.normal(size=n_stocks)
        for stock_index in range(n_stocks):
            x = stock_index - (n_stocks - 1) / 2
            rows.append({
                "trade_date": date,
                "symbol": f"{stock_index:06d}",
                "mom5": x * 0.3 + shock[stock_index] + day_index * 0.002,
                "vol20": (stock_index % 4) - 1.5,
                "fwd10": 0.05 * shock[stock_index] + x * 0.004,
            })
    return pd.DataFrame(rows)


class TestDsLinexObjective:

    def test_matches_finhack_formula(self):
        y = np.array([-2.0, -0.5, 0.0, 0.7, 3.0])
        p = np.array([-1.0, 0.2, 0.0, -0.3, 1.5])
        grad, hess = research.ds_grad_hess(y, p)
        x = p - y
        np.testing.assert_allclose(grad, 100.0 * (np.exp(x) - 1.0))
        np.testing.assert_allclose(hess, 100.0 * np.exp(x))

    def test_punishes_overprediction_more_than_underprediction(self):
        y = np.zeros(2)
        p = np.array([1.0, -1.0])
        grad, _ = research.ds_grad_hess(y, p)
        assert grad[0] > 0 and grad[1] < 0
        assert abs(grad[0]) > abs(grad[1])

    def test_extreme_gap_stays_finite(self):
        grad, hess = research.ds_grad_hess(
            np.array([0.0, 4.0]), np.array([500.0, -500.0]),
        )
        assert np.isfinite(grad).all() and np.isfinite(hess).all()
        # 低估方向饱和在 -100
        np.testing.assert_allclose(grad[1], -100.0, atol=1e-6)


class TestWeightedMseObjective:

    def test_weight_emphasizes_large_moves(self):
        y = np.array([0.0, 2.0, -3.0])
        p = np.array([0.1, 1.0, -1.0])
        grad, hess = research.weighted_mse_grad_hess(y, p)
        w = 1.0 + 2.0 * np.abs(y)
        np.testing.assert_allclose(grad, 2.0 * w * (p - y))
        np.testing.assert_allclose(hess, 2.0 * w)
        assert hess[1] > hess[0] and hess[2] > hess[0]

    def test_zero_label_reduces_to_plain_mse(self):
        y = np.zeros(4)
        p = np.array([-2.0, -0.4, 0.3, 1.7])
        grad, hess = research.weighted_mse_grad_hess(y, p)
        np.testing.assert_allclose(grad, 2.0 * p)
        np.testing.assert_allclose(hess, 2.0)


class TestDateGroupSizes:

    def test_counts_contiguous_sorted_dates(self):
        dates = pd.to_datetime(["2024-01-02"] * 3 + ["2024-01-03"] * 2 + ["2024-01-04"] * 4)
        sizes = research.date_group_sizes(dates.to_numpy())
        np.testing.assert_array_equal(sizes, [3, 2, 4])

    def test_rejects_unsorted_dates(self):
        dates = pd.to_datetime(["2024-01-03", "2024-01-02"])
        with pytest.raises(ValueError, match="sorted"):
            research.date_group_sizes(dates.to_numpy())


class TestIcObjective:

    def group_setup(self):
        y = np.array([1.5, -0.5, 0.2, 2.0, -1.0, 0.5, 0.0, -2.0, 1.0, 3.0])
        p = np.array([0.4, -1.2, 0.1, 1.5, 0.3, -0.4, 0.0, -1.1, 2.0, -0.5])
        sizes = np.array([5, 5])
        return y, p, sizes

    def raw_corr_grad(self, y, p):
        """教科书式负相关梯度，独立于实现重写。"""
        yc = y - y.mean()
        pc = p - p.mean()
        s_y = np.sqrt((yc ** 2).sum())
        s_p = np.sqrt((pc ** 2).sum())
        rho = (yc * pc).sum() / (s_y * s_p)
        return -(yc / (s_p * s_y) - rho * pc / (s_p ** 2))

    def test_gradient_direction_matches_negative_correlation(self):
        y, p, sizes = self.group_setup()
        grad, hess = research.ic_loss_grad(y, p, sizes)
        for start, stop in [(0, 5), (5, 10)]:
            expected = self.raw_corr_grad(y[start:stop], p[start:stop])
            got = grad[start:stop]
            cos = float(np.dot(expected, got) / (np.linalg.norm(expected) * np.linalg.norm(got)))
            assert cos > 0.999
        np.testing.assert_allclose(hess, 1.0)

    def test_group_rms_normalized_to_one(self):
        y, p, sizes = self.group_setup()
        grad, _ = research.ic_loss_grad(y, p, sizes)
        for start, stop in [(0, 5), (5, 10)]:
            rms = float(np.sqrt((grad[start:stop] ** 2).mean()))
            if rms > 1.0:
                assert 0.999 < rms <= 1.001

    def test_constant_predictions_stay_finite(self):
        y = np.array([2.0, -1.0, 0.5, -3.0])
        p = np.zeros(4)
        grad, hess = research.ic_loss_grad(y, p, np.array([4]))
        assert np.isfinite(grad).all()
        np.testing.assert_allclose(hess, 1.0)


def test_arm_params_change_only_objective():
    frame = synthetic_training(10)
    baseline = frozen_model_params()
    for arm in research.ARMS:
        params = research.arm_params(arm, frame)
        assert params.keys() == baseline.keys()
        for key, value in baseline.items():
            if key != "objective":
                assert params[key] == value, f"{arm} 修改了 {key}"


def test_select_arm_uses_validation_ic_with_net_tiebreak():
    validation = {
        "ic": {"mean_ic": 0.05, "total": 0.10},
        "wmse": {"mean_ic": 0.06, "total": -0.02},
        "ds": {"mean_ic": 0.04, "total": 0.30},
    }
    assert research.select_arm(validation) == "wmse"
    validation["ic"]["mean_ic"] = 0.06
    assert research.select_arm(validation) == "ic"
    validation["ds"]["mean_ic"] = 0.06
    validation["ds"]["total"] = 0.31
    validation["ic"]["total"] = 0.10
    # 三臂IC并列时按净收益高者
    assert research.select_arm(validation) == "ds"


def test_success_gates_require_all_four():
    candidate = {"mean_ic": 0.10, "total": 0.30, "sharpe": 1.2, "max_drawdown": -0.20}
    control = {"mean_ic": 0.11, "total": 0.25, "sharpe": 1.0, "max_drawdown": -0.25}
    gates = research.success_gates(candidate, control)
    assert gates["ic_not_below_control"] is False
    assert gates["return_not_below_control"] is True
    assert gates["sharpe_not_below_control"] is True
    assert gates["drawdown_not_worse"] is True
    assert gates["all_pass"] is False


def test_fit_arm_cv_and_final_are_deterministic():
    frame = synthetic_training()
    overrides = {
        "n_estimators": 15, "min_child_samples": 4, "num_leaves": 4,
        "max_depth": 3, "n_jobs": 1,
    }
    scores = {}
    features = ["mom5", "vol20"]
    for arm in research.ARMS:
        iterations = research.fit_arm_cv(frame, arm, features, params_override=overrides)
        assert len(iterations) == 5 and all(v > 0 for v in iterations)
        model = research.fit_arm_final(frame, arm, 8, features, params_override=overrides)
        scores[arm] = research.predict_arm_scores(model, frame, features)
    for arm, values in scores.items():
        assert np.isfinite(values).all(), f"{arm} 出现非有限分数"
    # 自定义损失臂与MSE不同源，但复跑同臂必须逐位一致
    again = research.predict_arm_scores(
        research.fit_arm_final(frame, "ds", 8, features, params_override=overrides),
        frame, features,
    )
    np.testing.assert_array_equal(scores["ds"], again)


def test_read_control_detail_filters_and_aligns_dates(tmp_path):
    detail = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-02-01"]),
        "period": ["validation", "validation", "validation"],
        "model": ["lightgbm_score", "equal_weight", "lightgbm_score"],
        "gross": [0.05, 0.03, 0.02],
        "cost": [0.0035, 0.0035, 0.0035],
        "net": [0.0465, 0.0265, 0.0165],
        "ic": [0.1, np.nan, 0.05],
        "holdings": ["A,B", "A,B", "C,D"],
    })
    path = tmp_path / "detail.csv"
    detail.to_csv(path, index=False)
    dates = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-02-01"]))
    out = research.read_control_detail(path, "lightgbm_score", dates)
    assert list(out["model"].unique()) == ["lightgbm_score"]
    assert set(out["date"]) == set(dates)
    with pytest.raises(AssertionError, match="日期"):
        research.read_control_detail(
            path, "lightgbm_score", dates.union(pd.DatetimeIndex([pd.Timestamp("2024-03-01")])),
        )
