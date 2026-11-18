#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LightGBM横截面选股研究：严格复用策略08的数据、因子和组合规则。"""

import json
import math
import sys
from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lasso_factor_selection_research import (
    FACTOR_CN, FACTORS, LABEL_HORIZON, REBALANCE_GAP, REVIEW_END, TRAIN_END,
    TRAIN_SAMPLE_GAP,
    build_sample, cs_zscore, load_panel, period_metrics, run_backtest,
)

RESULT_DATE = "2026-11-14"
OUT_DIR = PROJECT_ROOT / "research" / "lightgbm-factor-data"
IMAGE_DIR = PROJECT_ROOT / "articles" / "images"
LASSO_DETAIL = PROJECT_ROOT / "research" / "lasso-data" / "Lasso因子选择回测明细-2026-11-06.csv"
REPORT_PATH = PROJECT_ROOT / "research" / f"LightGBM横截面选股回测报告-{RESULT_DATE}.md"


def frozen_model_params() -> dict:
    """2026-11-14预登记参数；禁止读取二次验证结果后修改。"""
    return {
        "objective": "regression",
        "n_estimators": 400,
        "learning_rate": 0.03,
        "num_leaves": 15,
        "max_depth": 6,
        "min_child_samples": 200,
        "subsample": 0.8,
        "subsample_freq": 1,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 5.0,
        "random_state": 42,
        "n_jobs": 8,
        "verbosity": -1,
        "deterministic": True,
        "force_col_wise": True,
    }


def make_training_cv(train: pd.DataFrame, n_splits: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    if train.empty or "trade_date" not in train:
        raise ValueError("Training data must contain trade_date")
    dates = np.array(sorted(train["trade_date"].unique()))
    codes = pd.Categorical(train["trade_date"], categories=dates).codes
    indices = np.arange(len(train))
    splits = []
    for tr_date_idx, va_date_idx in TimeSeriesSplit(
        n_splits=n_splits, gap=int(np.ceil(LABEL_HORIZON / TRAIN_SAMPLE_GAP)),
    ).split(dates):
        tr_mask = np.isin(codes, tr_date_idx)
        va_mask = np.isin(codes, va_date_idx)
        splits.append((indices[tr_mask], indices[va_mask]))
    return splits


def fit_lightgbm_cv(
    train: pd.DataFrame,
    features: list[str],
    params: dict | None = None,
    n_splits: int = 5,
) -> list[int]:
    """只在传入的训练段做early stopping，不保留各折模型。"""
    iterations = []
    for fold, (tr_idx, va_idx) in enumerate(make_training_cv(train, n_splits), start=1):
        fold_params = frozen_model_params() | (params or {})
        model = lgb.LGBMRegressor(**fold_params)
        model.fit(
            train.iloc[tr_idx][features], train.iloc[tr_idx][f"fwd{LABEL_HORIZON}"],
            eval_X=train.iloc[va_idx][features],
            eval_y=train.iloc[va_idx][f"fwd{LABEL_HORIZON}"],
            eval_metric="l2",
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        iterations.append(int(model.best_iteration_ or model.n_estimators))
        print(f"CV fold {fold}/{n_splits}: best_iteration={iterations[-1]}", flush=True)
    return iterations


def median_best_iteration(iterations: list[int]) -> int:
    if not iterations or any(int(value) <= 0 for value in iterations):
        raise ValueError("Every best_iteration must be positive")
    return int(np.median(iterations))


def fit_final_lightgbm(
    train: pd.DataFrame,
    features: list[str],
    tree_count: int,
    params: dict | None = None,
) -> lgb.LGBMRegressor:
    if tree_count <= 0:
        raise ValueError("tree_count must be positive")
    model_params = frozen_model_params() | (params or {})
    model_params["n_estimators"] = tree_count
    model = lgb.LGBMRegressor(**model_params)
    model.fit(train[features], train[f"fwd{LABEL_HORIZON}"])
    return model


def predict_scores(
    model: lgb.LGBMRegressor,
    inference: pd.DataFrame,
    features: list[str],
) -> np.ndarray:
    missing = set(features) - set(inference.columns)
    if missing:
        raise ValueError(f"Missing features: {sorted(missing)}")
    return model.predict(inference[features], num_iteration=model.n_estimators)


def feature_importance_table(model: lgb.LGBMRegressor, features: list[str]) -> pd.DataFrame:
    gain = model.booster_.feature_importance(importance_type="gain")
    return pd.DataFrame({
        "factor": features,
        "factor_cn": [FACTOR_CN.get(factor, factor) for factor in features],
        "split": model.booster_.feature_importance(importance_type="split"),
        "gain": gain,
        "gain_pct": gain / gain.sum() * 100 if gain.sum() else np.zeros(len(gain)),
    }).sort_values("gain", ascending=False).reset_index(drop=True)


def select_frozen_baselines(baseline: pd.DataFrame, dates: pd.Index) -> pd.DataFrame:
    selected = baseline[
        baseline["model"].isin(["lasso_score", "equal_weight"])
        & baseline["date"].isin(set(dates))
    ].copy()
    return selected[["date", "period", "model", "gross", "cost", "net", "ic", "holdings"]]


def exclude_incomplete_cohorts(inference: pd.DataFrame, market_dates) -> pd.DataFrame:
    """整组调仓必须在研究截止日前完成T+1至T+21的持有。"""
    dates = pd.DatetimeIndex(pd.to_datetime(market_dates)).sort_values().unique()
    cutoff_position = dates.searchsorted(REVIEW_END, side="right") - 1
    complete_dates = set()
    for date in inference.loc[inference["is_rebal"], "trade_date"].unique():
        position = dates.get_loc(date)
        if position + REBALANCE_GAP + 1 <= cutoff_position:
            complete_dates.add(date)
    out = inference.copy()
    incomplete = out["is_rebal"] & ~out["trade_date"].isin(complete_dates)
    out.loc[incomplete, "hold_ret"] = np.nan
    out.loc[incomplete, "is_rebal"] = False
    return out


def serialize_summary(summary: dict) -> str:
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if isinstance(value, (float, np.floating)):
            return float(value) if math.isfinite(value) else None
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.bool_):
            return bool(value)
        return value
    return json.dumps(clean(summary), ensure_ascii=False, indent=2, allow_nan=False)


def prepare_samples(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    market_dates = sorted(panel.loc[
        (panel["trade_date"] >= "2021-01-01") & (panel["trade_date"] <= TRAIN_END),
        "trade_date",
    ].unique())
    purge_start = market_dates[-LABEL_HORIZON]
    sample = build_sample(panel).dropna(subset=FACTORS, how="any").copy()
    sample = cs_zscore(sample, FACTORS)
    train = sample[sample["trade_date"] < purge_start].dropna(
        subset=[f"fwd{LABEL_HORIZON}"],
    ).copy()
    train = cs_zscore(train, [f"fwd{LABEL_HORIZON}"])
    train = train.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    inference = sample[sample["is_rebal"]].copy().reset_index(drop=True)
    inference = exclude_incomplete_cohorts(inference, panel["trade_date"].unique())
    return train, inference, pd.Timestamp(purge_start)


def save_figures(all_results: pd.DataFrame, importance: pd.DataFrame) -> None:
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
    for ax, period, title in [
        (axes[0], "validation", "2024验证段（含成本）"),
        (axes[1], "review", "2025-01至2026-10二次验证（含成本）"),
    ]:
        for model, label, color in [
            ("lightgbm_score", "LightGBM", "#C65D3B"),
            ("lasso_score", "Lasso", "#287D6D"),
            ("equal_weight", "全A等权", "#777777"),
        ]:
            part = all_results[(all_results["model"] == model) & (all_results["period"] == period)].sort_values("date")
            ax.plot(part["date"], (1 + part["net"]).cumprod(), label=label, color=color, linewidth=2)
        ax.axhline(1, color="#999999", linewidth=0.8)
        ax.set_title(title)
        ax.legend(frameon=False)
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / "lightgbm-equity.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
    for ax, period, title in [
        (axes[0], "validation", "2024验证段（含成本）"),
        (axes[1], "review", "2025-01至2026-10二次验证（含成本）"),
    ]:
        for model, label, color in [
            ("lightgbm_score", "LightGBM", "#C65D3B"),
            ("equal_weight", "全A等权", "#287D6D"),
        ]:
            part = all_results[(all_results["model"] == model) & (all_results["period"] == period)].sort_values("date")
            ax.plot(part["date"], (1 + part["net"]).cumprod(), label=label, color=color, linewidth=2)
        ax.axhline(1, color="#999999", linewidth=0.8)
        ax.set_title(title)
        ax.legend(frameon=False)
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / "lightgbm-equity-public.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6.5))
    top = importance.nlargest(12, "gain").sort_values("gain")
    ax.barh(top["factor_cn"], top["gain_pct"], color="#287D6D")
    ax.set_title("LightGBM因子分裂增益占比（前12名）")
    ax.set_xlabel("占总增益比例（%）")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / "lightgbm-importance.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_report(summary: dict, importance: pd.DataFrame, iterations: list[int], report_path: Path) -> None:
    lines = [
        "# LightGBM横截面选股回测报告",
        f"> 生成：{RESULT_DATE}；预登记参数见研究方案与脚本。",
        "> 2025-01至2026-10是策略08已使用区间的二次验证，不是全新样本外。",
        "> 本版修正CV抽样日单位、初始净值回撤和完整调仓截止口径；Lasso与等权按相同日期和明细重算。",
        "> 剔除2026-10-19无法在2026-10-31前完成T+21退出的整组调仓。",
        "> 原库缺2021-2025退市股，有幸存者偏差；未完整处理涨跌停与冲击成本。",
        "", "## 训练与冻结",
        f"- 训练样本：{summary['train_rows']}行，{summary['train_dates']}个交易日，31因子。",
        f"- 各折最佳树数：{iterations}；冻结中位数：{summary['tree_count']}。",
        f"- 训练标签清除起点：{summary['purge_start']}及之后。",
        "", "## 因子分裂增益（不是因果贡献或收益率）",
        "| 因子 | 分裂次数 | 增益占比 |", "|---|---:|---:|",
    ]
    for row in importance.head(12).itertuples():
        lines.append(f"| {row.factor_cn} | {row.split} | {row.gain_pct:.2f}% |")
    lines += [
        "", "## 主配置：top20月调仓，含成本",
        "| 模型 | 分段 | 区间收益 | 年化 | 最大回撤 | 夏普 | 平均IC | 毛利累计 | 成本简单合计 | 次数 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, label in [("lightgbm", "LightGBM"), ("lasso", "Lasso"), ("equal_weight", "全A等权")]:
        for period in ["train", "validation", "review"]:
            m = summary["metrics"][model][period]
            lines.append(
                f"| {label} | {period} | {m['total']:.2%} | {m['annual']:.2%} | "
                f"{m['max_drawdown']:.2%} | {m['sharpe']:.2f} | {m['mean_ic']:.4f} | "
                f"{m['gross_total']:.2%} | {m['cost_sum']:.2%} | {m['rebalances']} |"
            )
    lines += [
        "", "## 双倍成本与预登记判断",
        f"- LightGBM二次验证双倍成本：{summary['stress_review_lightgbm']['total']:.2%}。",
        f"- 同时改善IC、净收益、夏普且回撤不恶化：{summary['success']['all_pass']}。",
        f"- 明细：{json.dumps(summary['success'], ensure_ascii=False)}",
        "", "## 结论边界",
        "- 本轮只有一个预登记LightGBM配置，不扫描因子、持仓数或二次验证参数。",
        "- 因子重要性是训练数据中的分裂增益，不代表因子独立有效性、因果方向或样本外贡献。",
        "- 个股行情提前结束时仍沿用第08篇最后可得价近似；这是一项成交与退市处理限制。",
        "- 静态训练模型用于同框架对照，不等于可持续实盘部署；本结果不自动进入模拟盘。",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(lines), encoding="utf-8",
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("加载第08篇全A面板...", flush=True)
    panel, _ = load_panel()
    print("计算并标准化同一批31因子...", flush=True)
    train, inference, purge_start = prepare_samples(panel)
    del panel
    print(f"训练 {train.shape}；调仓 {inference.shape}；purge={purge_start.date()}", flush=True)
    iterations = fit_lightgbm_cv(train, FACTORS)
    tree_count = median_best_iteration(iterations)
    print(f"冻结树数={tree_count}，拟合最终LightGBM...", flush=True)
    model = fit_final_lightgbm(train, FACTORS, tree_count)
    model.booster_.save_model(str(OUT_DIR / f"LightGBM冻结模型-{RESULT_DATE}.txt"))
    inference["lightgbm_score"] = predict_scores(model, inference, FACTORS)

    bt_lgbm = run_backtest(inference, "lightgbm_score")
    bt_stress = run_backtest(inference, "lightgbm_score", cost_mult=2.0)
    baseline = pd.read_csv(LASSO_DETAIL, parse_dates=["date"])
    baseline = select_frozen_baselines(baseline, bt_lgbm["date"])
    all_results = pd.concat([bt_lgbm, baseline], ignore_index=True)
    assert not all_results[["date", "model"]].duplicated().any()
    assert set(all_results["model"]) == {"lightgbm_score", "lasso_score", "equal_weight"}
    for baseline_name in ["lasso_score", "equal_weight"]:
        left = bt_lgbm[["date", "period"]].sort_values("date").reset_index(drop=True)
        right = baseline[baseline["model"] == baseline_name][["date", "period"]].sort_values("date").reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right)

    summary = {
        "date": RESULT_DATE,
        "evidence_status": "secondary_validation_only_for_review",
        "model_params": frozen_model_params(),
        "train_rows": len(train), "train_dates": train["trade_date"].nunique(),
        "train_date_min": str(train["trade_date"].min().date()),
        "train_date_max": str(train["trade_date"].max().date()),
        "purge_start": str(purge_start.date()),
        "cv_best_iterations": iterations, "tree_count": tree_count,
        "metrics": {},
        "stress_review_lightgbm": period_metrics(bt_stress[bt_stress["period"] == "review"]),
        "survivorship_bias": "原库缺2021-2025退市股，结果偏乐观",
    }
    for name, frame in [("lightgbm", bt_lgbm), ("lasso", baseline[baseline["model"] == "lasso_score"]), ("equal_weight", baseline[baseline["model"] == "equal_weight"])]:
        summary["metrics"][name] = {
            period: period_metrics(frame[frame["period"] == period])
            for period in ["train", "validation", "review"]
        }
    lgbm_review = summary["metrics"]["lightgbm"]["review"]
    lasso_review = summary["metrics"]["lasso"]["review"]
    summary["success"] = {
        "ic_not_below_lasso": lgbm_review["mean_ic"] >= lasso_review["mean_ic"],
        "return_not_below_lasso": lgbm_review["total"] >= lasso_review["total"],
        "sharpe_not_below_lasso": lgbm_review["sharpe"] >= lasso_review["sharpe"],
        "drawdown_not_worse": lgbm_review["max_drawdown"] >= lasso_review["max_drawdown"],
    }
    summary["success"]["all_pass"] = all(summary["success"].values())

    importance = feature_importance_table(model, FACTORS)
    bt_lgbm.to_csv(OUT_DIR / f"LightGBM横截面回测明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    bt_stress.to_csv(OUT_DIR / f"LightGBM双倍成本明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    all_results.to_csv(OUT_DIR / f"LightGBM与Lasso全对照-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    importance.to_csv(OUT_DIR / f"LightGBM因子重要性-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / f"LightGBM核心结果-{RESULT_DATE}.json").write_text(
        serialize_summary(summary), encoding="utf-8",
    )
    model.booster_.save_model(str(OUT_DIR / f"LightGBM冻结模型-{RESULT_DATE}.txt"))
    write_report(summary, importance, iterations, REPORT_PATH)
    save_figures(all_results, importance)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"已保存：{OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
