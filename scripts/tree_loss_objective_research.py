#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""树模型损失函数改造研究：唯一自由度是LightGBM的objective，其余沿用策略09冻结协议。

预登记（2026-11-17，见 research/树模型损失函数研究方案-2026-11-17.md）：
- 对照：09冻结MSE版LightGBM明细，只读不重训；
- 三臂：A1负逐日截面IC损失、A2幅度加权MSE(w=1+2|y|)、A3 FinHack-ds(LINEX)；
- 选型：验证段平均IC最高者（平局取净收益），只看2024；
- 判定：选定臂在二次验证段对对照四门槛（IC/净收益/夏普不低、回撤不劣）；
- 2025-01至2026-10已被08、09使用，本轮为第三次重复使用。
"""

import json
import sys
from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lightgbm_factor_selection_research import (
    FACTORS, LABEL_HORIZON, median_best_iteration, prepare_samples, serialize_summary,
)
from scripts.lasso_factor_selection_research import period_metrics, run_backtest

RESULT_DATE = "2026-11-17"
OUT_DIR = PROJECT_ROOT / "research" / "tree-loss-data"
IMAGE_DIR = PROJECT_ROOT / "articles" / "images"
CONTROL_DETAIL = PROJECT_ROOT / "research" / "lightgbm-factor-data" / "LightGBM横截面回测明细-2026-11-14.csv"
FULL_COMPARE = PROJECT_ROOT / "research" / "lightgbm-factor-data" / "LightGBM与Lasso全对照-2026-11-14.csv"
REPORT_PATH = PROJECT_ROOT / "research" / f"树模型损失函数回测报告-{RESULT_DATE}.md"

ARMS = ("ic", "wmse", "ds")
ARM_CN = {"ic": "IC损失", "wmse": "幅度加权MSE", "ds": "FinHack-ds(LINEX)"}
SCORE_COL = {arm: f"{arm}_score" for arm in ARMS}
CONTROL_COL = "lightgbm_score"


# ---------------------------------------------------------------- 损失函数

def ds_grad_hess(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """FinHack ds损失（LINEX）：L=100(e^x-x-1)，x=pred-true；指数截断±30仅防溢出。"""
    x = np.clip(np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float), -30.0, 30.0)
    exp_x = np.exp(x)
    return 100.0 * (exp_x - 1.0), 100.0 * exp_x


def weighted_mse_grad_hess(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """幅度加权MSE：w=1+2|y|，y为逐日z-score标签。"""
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    w = 1.0 + 2.0 * np.abs(y)
    return 2.0 * w * (p - y), 2.0 * w


def date_group_sizes(dates: np.ndarray) -> np.ndarray:
    """按连续日期段返回各组行数；要求升序。"""
    values = pd.to_datetime(pd.Series(dates)).to_numpy()
    if len(values) > 1 and np.any(values[1:] < values[:-1]):
        raise ValueError("dates must be sorted ascending")
    change = np.flatnonzero(values[1:] != values[:-1]) + 1
    boundaries = np.concatenate([[0], change, [len(values)]])
    return np.diff(boundaries)


def _group_slices(group_sizes: np.ndarray) -> list[tuple[int, int]]:
    ends = np.cumsum(group_sizes)
    starts = ends - group_sizes
    return [(int(s), int(e)) for s, e in zip(starts, ends)]


def ic_loss_grad(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    group_sizes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """L=-Σ_g corr_g(p,y) 的梯度；hess恒为1；s_p下限1e-6，组内RMS归一只作数值稳定。"""
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    grad = np.zeros_like(p)
    for start, stop in _group_slices(group_sizes):
        y_g, p_g = y[start:stop], p[start:stop]
        y_c, p_c = y_g - y_g.mean(), p_g - p_g.mean()
        s_y = float(np.sqrt((y_c ** 2).sum()))
        s_p = max(float(np.sqrt((p_c ** 2).sum())), 1e-6)
        rho = float((y_c * p_c).sum()) / (s_y * s_p)
        raw = -(y_c / (s_p * s_y) - rho * p_c / (s_p ** 2))
        scale = max(1.0, float(np.sqrt((raw ** 2).mean())))
        grad[start:stop] = raw / scale
    return grad, np.ones_like(p)


def make_arm_objective(arm: str, train_frame: pd.DataFrame):
    """返回sklearn API的objective callable（lightgbm>=4签名：y_true, y_pred）；
    ic臂闭包绑定训练帧的逐日组边界（y_true行序与数据集行序一致）。"""
    if arm == "ic":
        sizes = date_group_sizes(train_frame["trade_date"].to_numpy())

        def ic_objective(y_true, y_pred):
            return ic_loss_grad(y_true, y_pred, sizes)

        return ic_objective
    if arm == "wmse":
        def wmse_objective(y_true, y_pred):
            return weighted_mse_grad_hess(y_true, y_pred)
        return wmse_objective
    if arm == "ds":
        def ds_objective(y_true, y_pred):
            return ds_grad_hess(y_true, y_pred)
        return ds_objective
    raise ValueError(f"unknown arm: {arm}")


def arm_params(arm: str, train_frame: pd.DataFrame) -> dict:
    """09冻结参数原样，仅替换objective；任何其他键被改动都会被测试拦下。"""
    from scripts.lightgbm_factor_selection_research import frozen_model_params
    params = dict(frozen_model_params())
    params["objective"] = make_arm_objective(arm, train_frame)
    return params


# ---------------------------------------------------------------- 训练

def fit_arm_cv(
    train: pd.DataFrame,
    arm: str,
    features: list[str] | None = None,
    n_splits: int = 5,
    params_override: dict | None = None,
) -> list[int]:
    """训练内5折扩张窗口early stopping（l2口径），与09协议一致。"""
    features = features or FACTORS
    from scripts.lightgbm_factor_selection_research import make_training_cv
    iterations = []
    for fold, (tr_idx, va_idx) in enumerate(make_training_cv(train, n_splits), start=1):
        fold_frame = train.iloc[tr_idx]
        params = arm_params(arm, fold_frame) | (params_override or {})
        model = lgb.LGBMRegressor(**params)
        model.fit(
            fold_frame[features], fold_frame[f"fwd{LABEL_HORIZON}"],
            eval_X=train.iloc[va_idx][features], eval_y=train.iloc[va_idx][f"fwd{LABEL_HORIZON}"],
            eval_metric="l2",
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        iterations.append(int(model.best_iteration_ or model.n_estimators))
        print(f"[{arm}] CV fold {fold}/{n_splits}: best_iteration={iterations[-1]}", flush=True)
    return iterations


def fit_arm_final(
    train: pd.DataFrame,
    arm: str,
    tree_count: int,
    features: list[str] | None = None,
    params_override: dict | None = None,
) -> lgb.LGBMRegressor:
    if tree_count <= 0:
        raise ValueError("tree_count must be positive")
    features = features or FACTORS
    params = arm_params(arm, train) | (params_override or {})
    params["n_estimators"] = tree_count
    model = lgb.LGBMRegressor(**params)
    model.fit(train[features], train[f"fwd{LABEL_HORIZON}"])
    return model


def predict_arm_scores(
    model: lgb.LGBMRegressor,
    inference: pd.DataFrame,
    features: list[str] | None = None,
) -> np.ndarray:
    features = features or FACTORS
    missing = set(features) - set(inference.columns)
    if missing:
        raise ValueError(f"Missing features: {sorted(missing)}")
    return model.predict(inference[features], num_iteration=model.n_estimators)


# ---------------------------------------------------------------- 对照与判定

def read_control_detail(path: Path, model: str, dates: pd.DatetimeIndex) -> pd.DataFrame:
    detail = pd.read_csv(path, parse_dates=["date"])
    out = detail[detail["model"] == model].copy()
    missing = set(pd.DatetimeIndex(dates)) - set(out["date"])
    assert not missing, f"对照明细缺少日期：{sorted(missing)[:5]}（日期对账失败）"
    out = out[out["date"].isin(set(pd.DatetimeIndex(dates)))]
    return out[["date", "period", "model", "gross", "cost", "net", "ic", "holdings"]].reset_index(drop=True)


def select_arm(validation_metrics: dict[str, dict]) -> str:
    """验证段平均IC最高者；精确平局取净收益高者。只允许三臂参与。"""
    candidates = {arm: validation_metrics[arm] for arm in ARMS if arm in validation_metrics}
    assert set(candidates) == set(ARMS), "选型必须且只能覆盖三个损失臂"
    return max(candidates, key=lambda arm: (candidates[arm]["mean_ic"], candidates[arm]["total"]))


def success_gates(candidate: dict, control: dict) -> dict:
    gates = {
        "ic_not_below_control": candidate["mean_ic"] >= control["mean_ic"],
        "return_not_below_control": candidate["total"] >= control["total"],
        "sharpe_not_below_control": candidate["sharpe"] >= control["sharpe"],
        "drawdown_not_worse": candidate["max_drawdown"] >= control["max_drawdown"],
    }
    gates["all_pass"] = all(gates.values())
    return gates


# ---------------------------------------------------------------- 图表与报告

def save_figures(all_results: pd.DataFrame, selected: str) -> None:
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    styles = [
        (CONTROL_COL, "默认MSE（对照）", "#777777"),
        (SCORE_COL["ic"], "IC损失", "#C65D3B"),
        (SCORE_COL["wmse"], "幅度加权MSE", "#D6A419"),
        (SCORE_COL["ds"], "FinHack-ds", "#287D6D"),
        ("equal_weight", "全A等权", "#4A6FA5"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
    for ax, period, title in [
        (axes[0], "validation", "2024验证段（含成本）"),
        (axes[1], "review", "2025-01至2026-10三次验证（含成本）"),
    ]:
        for model, label, color in styles:
            part = all_results[(all_results["model"] == model) & (all_results["period"] == period)].sort_values("date")
            ax.plot(part["date"], (1 + part["net"]).cumprod(), label=label, color=color, linewidth=2)
        ax.axhline(1, color="#999999", linewidth=0.8)
        ax.set_title(title)
        ax.legend(frameon=False, fontsize=9)
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / "tree-loss-equity.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    winner_styles = [
        (SCORE_COL[selected], f"{ARM_CN[selected]}（选定臂）", "#C65D3B"),
        (CONTROL_COL, "默认MSE（对照）", "#777777"),
        ("equal_weight", "全A等权", "#4A6FA5"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
    for ax, period, title in [
        (axes[0], "validation", "2024验证段（含成本）"),
        (axes[1], "review", "2025-01至2026-10三次验证（含成本）"),
    ]:
        for model, label, color in winner_styles:
            part = all_results[(all_results["model"] == model) & (all_results["period"] == period)].sort_values("date")
            ax.plot(part["date"], (1 + part["net"]).cumprod(), label=label, color=color, linewidth=2)
        ax.axhline(1, color="#999999", linewidth=0.8)
        ax.set_title(title)
        ax.legend(frameon=False)
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / "tree-loss-equity-public.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_report(summary: dict, report_path: Path) -> None:
    lines = [
        "# 树模型损失函数改造回测报告",
        f"> 生成：{RESULT_DATE}；预登记方案见 research/树模型损失函数研究方案-{RESULT_DATE}.md。",
        "> 对照组为第09篇冻结MSE版LightGBM明细，只读未重训。",
        "> 2025-01至2026-10已被策略08、09使用，本轮为第三次重复使用，只作重复验证。",
        "> 原库缺2021-2025退市股，有幸存者偏差；未完整处理涨跌停与冲击成本。",
        "", "## 训练与冻结",
        f"- 训练样本：{summary['train_rows']}行，{summary['train_dates']}个交易日，31因子；与09同源。",
    ]
    for arm in ARMS:
        lines.append(
            f"- {ARM_CN[arm]}：各折最佳树数{summary['cv_best_iterations'][arm]}，冻结中位数{summary['tree_counts'][arm]}。"
        )
    lines += [
        "", "## 主配置：top20月调仓，含成本",
        "| 模型 | 分段 | 区间收益 | 年化 | 最大回撤 | 夏普 | 平均IC | 毛利累计 | 成本简单合计 | 次数 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = [(CONTROL_COL, "默认MSE（对照）")] + [(SCORE_COL[a], ARM_CN[a]) for a in ARMS] + [("equal_weight", "全A等权")]
    for model, label in labels:
        for period in ["train", "validation", "review"]:
            m = summary["metrics"][model][period]
            ic_text = "null" if m["mean_ic"] is None else f"{m['mean_ic']:.4f}"
            lines.append(
                f"| {label} | {period} | {m['total']:.2%} | {m['annual']:.2%} | "
                f"{m['max_drawdown']:.2%} | {m['sharpe']:.2f} | {ic_text} | "
                f"{m['gross_total']:.2%} | {m['cost_sum']:.2%} | {m['rebalances']} |"
            )
    lines += [
        "", "## 预登记选型与判定",
        f"- 验证段选型（仅三臂，IC优先、净收益平局）：{ARM_CN[summary['selected_arm']]}。",
    ]
    for arm in ARMS:
        lines.append(
            f"- 验证段 {ARM_CN[arm]}：IC {summary['validation_selection'][arm]['mean_ic']:.4f}，净收益 {summary['validation_selection'][arm]['total']:.2%}。"
        )
    gates = summary["success"]
    lines.append(
        f"- 选定臂三次验证四门槛：IC不低于对照={gates['ic_not_below_control']}，净收益={gates['return_not_below_control']}，"
        f"夏普={gates['sharpe_not_below_control']}，回撤不劣={gates['drawdown_not_worse']}，全部通过={gates['all_pass']}。"
    )
    if "stress_review_selected" in summary:
        lines.append(f"- 选定臂三次验证双倍成本：{summary['stress_review_selected']['total']:.2%}。")
    lines += [
        "", "## 结论边界",
        "- 本轮唯一自由度是objective；三臂在三次验证段的数字全部披露，但只有预选臂参与判定，不得事后改选。",
        "- IC损失含hess=1与组内RMS归一的数值处理；ds损失沿用本项目z-score标签而非FinHack原始收益标签，均已在方案中预登记。",
        "- 静态训练模型用于同框架对照，不等于可持续实盘部署；本结果不自动进入模拟盘。",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 主流程

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    from scripts.lasso_factor_selection_research import load_panel
    print("加载第08篇全A面板...", flush=True)
    panel, _ = load_panel()
    train, inference, purge_start = prepare_samples(panel)
    del panel
    print(f"训练 {train.shape}；调仓 {inference.shape}；purge={purge_start.date()}", flush=True)

    # 训练前快失败：新推理调仓日必须与09冻结明细完全一致
    rebal_dates = pd.DatetimeIndex(sorted(inference.loc[inference["is_rebal"], "trade_date"].unique()))
    control_dates = pd.read_csv(CONTROL_DETAIL, parse_dates=["date"])
    control_dates = pd.DatetimeIndex(sorted(control_dates[control_dates["model"] == CONTROL_COL]["date"].unique()))
    assert set(rebal_dates) == set(control_dates), "调仓日期与09冻结明细不一致，中止训练"

    tree_counts, cv_iterations = {}, {}
    for arm in ARMS:
        print(f"训练损失臂 {ARM_CN[arm]} ...", flush=True)
        iterations = fit_arm_cv(train, arm)
        tree_counts[arm] = median_best_iteration(iterations)
        cv_iterations[arm] = iterations
        model = fit_arm_final(train, arm, tree_counts[arm])
        model.booster_.save_model(str(OUT_DIR / f"{arm}_冻结模型-{RESULT_DATE}.txt"))
        inference[SCORE_COL[arm]] = predict_arm_scores(model, inference)
        print(f"[{arm}] 冻结树数={tree_counts[arm]}", flush=True)

    arm_results, stress_results = {}, {}
    for arm in ARMS:
        arm_results[arm] = run_backtest(inference, SCORE_COL[arm])
        stress_results[arm] = run_backtest(inference, SCORE_COL[arm], cost_mult=2.0)

    control = read_control_detail(CONTROL_DETAIL, CONTROL_COL, arm_results["ic"]["date"])
    equal_weight = read_control_detail(FULL_COMPARE, "equal_weight", arm_results["ic"]["date"])
    for frame in [control, equal_weight]:
        left = arm_results["ic"][["date", "period"]].sort_values("date").reset_index(drop=True)
        right = frame[["date", "period"]].sort_values("date").reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right)

    metrics = {}
    model_frames = {SCORE_COL[arm]: arm_results[arm] for arm in ARMS}
    model_frames[CONTROL_COL] = control
    model_frames["equal_weight"] = equal_weight
    for model, frame in model_frames.items():
        metrics[model] = {
            period: period_metrics(frame[frame["period"] == period])
            for period in ["train", "validation", "review"]
        }

    validation_selection = {
        arm: {
            "mean_ic": metrics[SCORE_COL[arm]]["validation"]["mean_ic"],
            "total": metrics[SCORE_COL[arm]]["validation"]["total"],
        }
        for arm in ARMS
    }
    selected = select_arm(
        {arm: {"mean_ic": v["mean_ic"], "total": v["total"]} for arm, v in validation_selection.items()}
    )
    gates = success_gates(
        metrics[SCORE_COL[selected]]["review"], metrics[CONTROL_COL]["review"],
    )

    all_results = pd.concat([*arm_results.values(), control, equal_weight], ignore_index=True)
    assert not all_results[["date", "model"]].duplicated().any()

    summary = {
        "date": RESULT_DATE,
        "evidence_status": "third_use_review_segment",
        "arms": list(ARMS), "arm_cn": dict(ARM_CN),
        "train_rows": len(train), "train_dates": train["trade_date"].nunique(),
        "purge_start": str(purge_start.date()),
        "cv_best_iterations": cv_iterations, "tree_counts": tree_counts,
        "metrics": metrics,
        "validation_selection": validation_selection,
        "selected_arm": selected,
        "success": gates,
        "stress_review_selected": period_metrics(stress_results[selected][stress_results[selected]["period"] == "review"]),
        "survivorship_bias": "原库缺2021-2025退市股，结果偏乐观",
    }
    for arm in ARMS:
        arm_results[arm].to_csv(OUT_DIR / f"{arm}_回测明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
        stress_results[arm].to_csv(OUT_DIR / f"{arm}_双倍成本明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    all_results.to_csv(OUT_DIR / f"全对照明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / f"核心结果-{RESULT_DATE}.json").write_text(serialize_summary(summary), encoding="utf-8")
    write_report(summary, REPORT_PATH)
    save_figures(all_results, selected)
    print(json.dumps({k: summary[k] for k in ["selected_arm", "success", "tree_counts"]}, ensure_ascii=False, indent=2), flush=True)
    print(f"已保存：{OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
