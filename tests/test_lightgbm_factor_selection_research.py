"""LightGBM横截面研究的时间边界与模型冻结测试。"""

import json

import numpy as np
import pandas as pd
import pytest

import scripts.lightgbm_factor_selection_research as research
from scripts.lightgbm_factor_selection_research import (
    FACTORS,
    feature_importance_table,
    fit_final_lightgbm,
    fit_lightgbm_cv,
    frozen_model_params,
    make_training_cv,
    median_best_iteration,
    predict_scores,
    select_frozen_baselines,
)


def synthetic_training() -> pd.DataFrame:
    dates = pd.bdate_range("2021-01-04", periods=400)[::5]
    rows = []
    for day_index, date in enumerate(dates):
        for stock_index in range(6):
            x = stock_index - 2.5
            rows.append({
                "trade_date": date,
                "symbol": f"{stock_index:06d}",
                "mom5": x + day_index * 0.001,
                "vol20": (stock_index % 3) - 1,
                "fwd10": x * 0.01,
            })
    return pd.DataFrame(rows)


def test_frozen_model_params_limit_capacity_and_seed():
    params = frozen_model_params()
    assert params["objective"] == "regression"
    assert params["n_estimators"] == 400
    assert params["learning_rate"] == 0.03
    assert params["num_leaves"] == 15
    assert params["max_depth"] == 6
    assert params["min_child_samples"] == 200
    assert params["random_state"] == 42


def test_training_cv_purges_ten_market_days_before_each_validation_fold():
    frame = synthetic_training()
    splits = make_training_cv(frame)
    dates = np.array(pd.bdate_range(
        frame["trade_date"].min(), frame["trade_date"].max(),
    ))
    assert len(splits) == 5
    for train_indices, valid_indices in splits:
        train_dates = frame.iloc[train_indices]["trade_date"]
        valid_dates = frame.iloc[valid_indices]["trade_date"]
        assert train_dates.max() < valid_dates.min()
        train_tail = np.where(dates == train_dates.max())[0][0]
        valid_start = np.where(dates == valid_dates.min())[0][0]
        assert 10 < valid_start - train_tail <= 15


def test_median_best_iteration_is_frozen_without_test_data():
    assert median_best_iteration([10, 20, 30]) == 20
    assert median_best_iteration([10, 20]) == 15
    with pytest.raises(ValueError, match="best_iteration"):
        median_best_iteration([0, 20])


def test_cv_and_final_fit_return_deterministic_scores():
    frame = synthetic_training()
    features = ["mom5", "vol20"]
    overrides = {
        "n_estimators": 20,
        "min_child_samples": 4,
        "num_leaves": 4,
        "n_jobs": 1,
    }
    iterations = fit_lightgbm_cv(frame, features, params=overrides, n_splits=2)
    assert len(iterations) == 2
    tree_count = median_best_iteration(iterations)
    model = fit_final_lightgbm(frame, features, tree_count, params=overrides)
    assert model.n_estimators == tree_count
    first = predict_scores(model, frame, features)
    second = predict_scores(model, frame, features)
    np.testing.assert_allclose(first, second)
    assert len(first) == len(frame)
    assert np.isfinite(first).all()


def test_predict_scores_rejects_missing_features():
    frame = synthetic_training()
    model = fit_final_lightgbm(
        frame, ["mom5", "vol20"], 2,
        params={"n_jobs": 1, "min_child_samples": 4},
    )
    with pytest.raises(ValueError, match="vol20"):
        predict_scores(model, frame.drop(columns="vol20"), ["mom5", "vol20"])


def test_frozen_baseline_excludes_ols_and_matches_lgbm_dates():
    dates = pd.to_datetime(["2024-01-02", "2024-02-01"])
    rows = []
    for model in ["ols_score", "lasso_score", "equal_weight"]:
        for date in dates:
            rows.append({
                "date": date, "period": "validation", "model": model,
                "gross": 0.02, "cost": 0.0035, "net": 0.0165,
                "ic": np.nan, "holdings": "",
            })
    baseline = select_frozen_baselines(pd.DataFrame(rows), dates)
    assert set(baseline["model"]) == {"lasso_score", "equal_weight"}
    assert len(baseline) == 4
    assert baseline["date"].min() == dates[0]


def test_importance_table_uses_fitted_booster():
    frame = synthetic_training()
    features = ["mom5", "vol20"]
    fitted_model = fit_final_lightgbm(
        frame, features, 3,
        params={"n_jobs": 1, "min_child_samples": 4},
    )
    importance = feature_importance_table(fitted_model, features)
    assert importance["factor"].tolist() == features
    assert np.isclose(importance["gain_pct"].sum(), 100.0)
    assert np.isfinite(importance["gain"]).all()


def test_main_writes_complete_comparison_after_baseline_iteration(tmp_path, monkeypatch):
    train = synthetic_training()
    for factor in FACTORS:
        if factor not in train:
            train[factor] = 0.0
    inference = pd.concat([
        pd.DataFrame({
            "trade_date": pd.Timestamp(date),
            "symbol": [f"{index:06d}" for index in range(90)],
            "is_rebal": True,
            "hold_ret": np.linspace(-0.01, 0.02, 90),
            "fwd10": np.linspace(-0.02, 0.03, 90),
            **{factor: np.arange(90) / 90 for factor in FACTORS},
        })
        for date in ["2023-01-03", "2024-01-02", "2025-01-02"]
    ], ignore_index=True)
    baseline_rows = []
    for date in inference["trade_date"].unique():
        for model in ["ols_score", "lasso_score", "equal_weight"]:
            baseline_rows.append({
                "date": date,
                "period": "train" if date.year == 2023 else "validation" if date.year == 2024 else "review",
                "model": model,
                "gross": 0.01, "cost": 0.0035, "net": 0.0065,
                "ic": 0.1, "holdings": "",
            })
    baseline_path = tmp_path / "baseline.csv"
    pd.DataFrame(baseline_rows).to_csv(baseline_path, index=False)
    monkeypatch.setattr(research, "OUT_DIR", tmp_path)
    monkeypatch.setattr(research, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(research, "LASSO_DETAIL", baseline_path)
    report_path = tmp_path / "report.md"
    monkeypatch.setattr(research, "REPORT_PATH", report_path, raising=False)
    formal_report = research.PROJECT_ROOT / "research" / "LightGBM横截面选股回测报告-2026-11-14.md"
    original_report = formal_report.read_bytes() if formal_report.exists() else None
    monkeypatch.setattr(research, "load_panel", lambda: (pd.DataFrame(), pd.DataFrame()))
    monkeypatch.setattr(
        research, "prepare_samples",
        lambda panel: (train, inference, pd.Timestamp("2023-12-18")),
    )
    monkeypatch.setattr(research, "fit_lightgbm_cv", lambda *args: [3, 3])
    monkeypatch.setattr(research, "frozen_model_params", lambda: {
        "objective": "regression", "n_estimators": 3, "num_leaves": 4,
        "min_child_samples": 4, "n_jobs": 1, "random_state": 42, "verbosity": -1,
    })
    try:
        research.main()
    finally:
        if original_report is not None and formal_report.read_bytes() != original_report:
            formal_report.write_bytes(original_report)
    comparison = pd.read_csv(tmp_path / "LightGBM与Lasso全对照-2026-11-14.csv")
    assert set(comparison["model"]) == {"lightgbm_score", "lasso_score", "equal_weight"}
    assert "ols_score" not in set(comparison["model"])
    assert (tmp_path / "LightGBM核心结果-2026-11-14.json").exists()
    assert (tmp_path / "LightGBM冻结模型-2026-11-14.txt").exists()
    assert report_path.exists()
    assert f"{len(train)}行" in report_path.read_text(encoding="utf-8")
    saved_summary = json.loads((tmp_path / "LightGBM核心结果-2026-11-14.json").read_text(encoding="utf-8"))
    assert saved_summary["train_rows"] == len(train)


def test_drawdown_includes_loss_from_initial_capital():
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-02-01"]),
        "net": [-0.20, 0.10], "gross": [-0.20, 0.10],
        "cost": [0.0, 0.0], "ic": [0.1, 0.1],
    })
    metrics = research.period_metrics(frame)
    assert metrics["max_drawdown"] == pytest.approx(-0.20)


def test_incomplete_terminal_cohort_is_removed():
    market_dates = pd.bdate_range("2026-08-03", "2026-11-04")
    frame = pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-09-18", "2026-10-19"]),
        "is_rebal": [True, True], "hold_ret": [0.05, 0.05],
    })
    filtered = research.exclude_incomplete_cohorts(frame, market_dates)
    assert filtered["is_rebal"].tolist() == [True, False]
    assert filtered["hold_ret"].iloc[0] == 0.05
    assert np.isnan(filtered["hold_ret"].iloc[1])


def test_summary_json_uses_null_instead_of_bare_nan():
    text = research.serialize_summary({"metric": float("nan"), "value": 1.0})
    parsed = json.loads(text)
    assert parsed == {"metric": None, "value": 1.0}
    assert "NaN" not in text
