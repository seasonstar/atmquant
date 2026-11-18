#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结 15m 参数的验证选参、双成本复检、同 root 1h 对照与图表。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import bayesian_q_analysis as one_hour
from scripts import bayesian_q_parameter_research as research
from scripts.batch_backtest_bayesian_q import _safe_symbol

DATA_DIR = research.OUTPUT_DIR
SOURCE_DIR = research.SOURCE_DIR
REPORT_PATH = PROJECT_ROOT / "research" / "贝叶斯BBSMA-nQQE回测报告-2026-11-12.md"
IMAGE_DIR = PROJECT_ROOT / "articles" / "images"
PERIODS = ("validation", "review")
COSTS = (1, 2)
REPORT_START = "<!-- TASK7_15M_START -->"
REPORT_END = "<!-- TASK7_15M_END -->"


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ValueError(f"缺少 {path}")
    return pd.read_csv(path)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(one_hour._json_value(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_one_tick(detail: pd.DataFrame, inventory: pd.DataFrame, failures: pd.DataFrame) -> dict:
    """每个合约/组合必须有 9 行或有明确失败，禁止用部分网格选参。"""

    if len(inventory) != 49 or inventory["root"].str.casefold().duplicated().any():
        raise ValueError("15m inventory 必须是 49 个唯一 root")
    one = detail[detail["slippage_ticks"].astype(int).eq(1)].copy()
    keys = ["root", "model", "param_set", "period"]
    if one.duplicated(keys).any():
        raise ValueError("15m 1-tick 明细存在重复 root/model/param_set/period")
    if set(one["model"]) - set(research.MODELS) or set(one["param_set"]) - set(research.PARAM_SETS):
        raise ValueError("15m 明细含非冻结模型或参数")
    if not one.empty and not one["signal_minutes"].astype(int).eq(15).all():
        raise ValueError("15m 明细混入其他信号周期")
    failed = set()
    if not failures.empty:
        runtime = failures[failures["slippage_ticks"].astype(str).eq("1")]
        failed = set(zip(runtime["vt_symbol"], runtime["param_set"]))
    missing = []
    for contract in inventory.itertuples():
        for param_set in research.PARAM_SETS:
            group = one[one["vt_symbol"].eq(contract.vt_symbol) & one["param_set"].eq(param_set)]
            actual = set(zip(group["model"], group["period"]))
            expected = {(m, p) for m in research.MODELS for p in research.base.PERIODS}
            if actual != expected and (contract.vt_symbol, param_set) not in failed:
                missing.append({"vt_symbol": contract.vt_symbol, "param_set": param_set,
                                "missing": sorted(expected - actual), "unexpected": sorted(actual - expected)})
    if missing:
        raise ValueError(f"1-tick 网格未完成，不能选参: {missing[:10]}")
    valid = {
        (vt, param) for vt, param in (
            (contract.vt_symbol, param)
            for contract in inventory.itertuples() for param in research.PARAM_SETS
        ) if (vt, param) not in failed
    }
    return {
        "inventory_roots": len(inventory), "expected_combinations": 49 * 4,
        "valid_combinations": len(valid), "failed_combinations": len(failed),
        "detail_rows_1tick": len(one), "expected_detail_rows_1tick": len(valid) * 9,
        "failure_records_1tick": len(failed),
        "insolvent_rows_1tick": int(one["solvency_status"].eq("insolvent").sum()),
        "unknown_solvency_rows_1tick": int((~one["solvency_status"].isin(
            ["solvent", "insolvent", "no_data"]
        )).sum()),
        "insolvent_records_1tick": one.loc[one["solvency_status"].eq("insolvent"), [
            "root", "vt_symbol", "model", "param_set", "period", "slippage_ticks",
            "solvency_status", "total_net_pnl", "sharpe_ratio",
            "nonpositive_balance_days", "nonpositive_pre_balance_days",
            "invalid_log_return_days", "min_balance", "min_pre_balance",
        ]].to_dict("records"),
    }


def freeze_selection(detail: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """先物理裁出 validation 行，再把该对象交给唯一选参入口。"""

    one = detail[detail["slippage_ticks"].astype(int).eq(1)]
    validation_only = one[one["period"].eq("validation")].copy()
    if validation_only["period"].ne("validation").any():
        raise AssertionError("review 泄漏到选参输入")
    selected = {}
    all_combinations = []
    for model in research.Q_MODELS:
        choice = research.select_parameters(validation_only, model)
        selected[model] = choice
        combinations = research.summarize_parameter_combinations(validation_only, model)
        all_combinations.extend(combinations)
    return {
        "selection_period": "validation", "review_used_for_selection": False,
        "selected": selected, "all_combinations": all_combinations,
        "ranking": "median Sharpe desc, median net pnl desc, improvement breadth desc, param_set lexical asc",
    }, pd.DataFrame(all_combinations)


def plot_validation(combinations: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    names = list(research.PARAM_SETS)
    for row, model in enumerate(research.Q_MODELS):
        group = combinations[combinations["model"].eq(model)].set_index("param_set").reindex(names)
        x = np.arange(len(names))
        axes[row, 0].bar(x, group["median_sharpe"], color=["#376795" if ok else "#b8bec7" for ok in group["activity_eligible"]])
        axes[row, 0].axhline(0, color="black", linewidth=0.7)
        axes[row, 0].set_title(f"{model}: validation median Sharpe")
        axes[row, 1].bar(x, group["median_net_pnl"], color=["#4b8b6e" if ok else "#b8bec7" for ok in group["activity_eligible"]])
        axes[row, 1].axhline(0, color="black", linewidth=0.7)
        axes[row, 1].set_title(f"{model}: validation median net pnl")
        for col in range(2):
            axes[row, col].set_xticks(x, names)
            axes[row, col].grid(axis="y", alpha=0.2)
    fig.suptitle("15m frozen parameter selection (validation only; grey=activity ineligible)")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _load_trades(vt_symbols: Sequence[str], param_set: str, costs: Sequence[int]) -> pd.DataFrame:
    frames = []
    missing = []
    for vt_symbol in vt_symbols:
        for cost in costs:
            for model in research.MODELS:
                path = DATA_DIR / (
                    f"trades_{_safe_symbol(vt_symbol)}_{param_set}_{model}_slippage{cost}.csv"
                )
                if not path.exists():
                    missing.append(str(path))
                elif path.stat().st_size:
                    frames.append(pd.read_csv(path))
    if missing:
        raise ValueError(f"冻结复检 trades 缺失: {missing[:10]}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def evaluate_frozen_review(
    detail: pd.DataFrame, inventory: pd.DataFrame, selected: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    gate_frames = []
    comparison_frames = []
    for model in research.Q_MODELS:
        choice = selected.get(model)
        if not choice:
            continue
        param_set = choice["param_set"]
        symbols = inventory["vt_symbol"].tolist()
        frozen = detail[
            detail["param_set"].eq(param_set)
            & detail["model"].isin(["nqqe", model])
            & detail["period"].eq("review")
        ].copy()
        missing_costs = set(COSTS) - set(frozen["slippage_ticks"].astype(int))
        if missing_costs:
            raise ValueError(f"{model}/{param_set} 缺冻结成本 {sorted(missing_costs)}")
        trades = _load_trades(symbols, param_set, COSTS)
        original_models = one_hour.BAYESIAN_Q_MODELS
        try:
            # 原函数默认遍历两族；单族冻结时限制其循环，仍复用完全相同的门槛公式。
            one_hour.BAYESIAN_Q_MODELS = (model,)
            gates, comparisons = one_hour.evaluate_filter_gates(
                frozen, trades, return_comparisons=True
            )
        finally:
            one_hour.BAYESIAN_Q_MODELS = original_models
        gates = gates[gates["model"].astype(str).eq(model)].copy()
        comparisons = comparisons[comparisons["model"].eq(model)].copy()
        gates["param_set"] = param_set
        comparisons["param_set"] = param_set
        gate_frames.append(gates)
        comparison_frames.append(comparisons)
    if not gate_frames:
        return pd.DataFrame(), pd.DataFrame()
    return pd.concat(gate_frames, ignore_index=True), pd.concat(comparison_frames, ignore_index=True)


def compare_same_roots(
    parameter_detail: pd.DataFrame, hourly_detail: pd.DataFrame,
    selected: Mapping[str, Any],
) -> pd.DataFrame:
    """15m/1h 只按同模型、同区间、同成本、同 root 交集计算中位数。"""

    rows = []
    for model in research.Q_MODELS:
        choice = selected.get(model)
        if not choice:
            continue
        param_set = choice["param_set"]
        for period in PERIODS:
            for cost in COSTS:
                fifteen = parameter_detail[
                    parameter_detail["model"].eq(model)
                    & parameter_detail["param_set"].eq(param_set)
                    & parameter_detail["period"].eq(period)
                    & parameter_detail["slippage_ticks"].astype(int).eq(cost)
                ]
                hourly = hourly_detail[
                    hourly_detail["model"].eq(model)
                    & hourly_detail["period"].eq(period)
                    & hourly_detail["slippage_ticks"].astype(int).eq(cost)
                ]
                pair = fifteen.merge(hourly, on="root", suffixes=("_15m", "_1h"), validate="one_to_one")
                if pair.empty:
                    raise ValueError(f"{model}/{period}/{cost} 同 root 交集为空")
                row = {
                    "model": model, "param_set": param_set, "period": period,
                    "slippage_ticks": cost, "n_roots": len(pair),
                    "15m_roots": fifteen["root"].nunique(), "1h_roots": hourly["root"].nunique(),
                    "15m_median_net_pnl": pair["total_net_pnl_15m"].median(skipna=False),
                    "1h_median_net_pnl": pair["total_net_pnl_1h"].median(skipna=False),
                    "15m_median_sharpe": pair["sharpe_ratio_15m"].median(skipna=False),
                    "1h_median_sharpe": pair["sharpe_ratio_1h"].median(skipna=False),
                    "15m_median_max_ddpercent": pair["max_ddpercent_15m"].median(skipna=False),
                    "1h_median_max_ddpercent": pair["max_ddpercent_1h"].median(skipna=False),
                }
                row["median_net_pnl_delta"] = row["15m_median_net_pnl"] - row["1h_median_net_pnl"]
                row["median_sharpe_delta"] = row["15m_median_sharpe"] - row["1h_median_sharpe"]
                row["validation_better_than_1h"] = bool(
                    period == "validation" and cost == 1
                    and row["median_net_pnl_delta"] > 0 and row["median_sharpe_delta"] > 0
                )
                rows.append(row)
    return pd.DataFrame(rows)


def decide_robust_better(
    selected: Mapping[str, Any], gates: pd.DataFrame, comparisons: pd.DataFrame,
) -> dict:
    outcomes = {}
    for model in research.Q_MODELS:
        if not selected.get(model):
            outcomes[model] = {"robust_better": False, "reason": "no_validation_eligible_combination"}
            continue
        family_gates = gates[gates["model"].astype(str).eq(model)]
        standard = family_gates[family_gates["slippage_ticks"].astype(int).eq(1)]
        validation = comparisons[
            comparisons["model"].eq(model) & comparisons["period"].eq("validation")
            & comparisons["slippage_ticks"].astype(int).eq(1)
        ]
        if len(standard) != 1 or len(validation) != 1:
            outcomes[model] = {"robust_better": False, "reason": "missing_frozen_review_or_comparison"}
            continue
        gate = standard.iloc[0]
        comparison = validation.iloc[0]
        conditions = {
            "review_filter_and_double_cost_pass": bool(gate["double_cost_pass"]),
            "validation_pnl_and_sharpe_better_than_1h": bool(comparison["validation_better_than_1h"]),
            "review_candidate_breadth_positive_pnl_sharpe": bool(gate["candidate"]),
        }
        outcomes[model] = {
            "robust_better": all(conditions.values()), "conditions": conditions,
            "review_double_cost_candidate": bool(gate["double_cost_candidate"]),
            "reason": "all_preregistered_conditions_pass" if all(conditions.values())
            else "at_least_one_preregistered_condition_failed",
        }
    return outcomes


def plot_review(comparisons: pd.DataFrame, outcomes: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    if comparisons.empty:
        for axis in axes.flat:
            axis.text(0.5, 0.5, "No validation-eligible frozen combination", ha="center", va="center")
            axis.axis("off")
        fig.suptitle("15m frozen review: no parameter combination selected")
        fig.tight_layout()
        fig.savefig(path, dpi=170)
        plt.close(fig)
        return
    for row, model in enumerate(research.Q_MODELS):
        group = comparisons[
            comparisons["model"].eq(model) & comparisons["slippage_ticks"].astype(int).eq(1)
        ].set_index("period").reindex(PERIODS)
        x = np.arange(2)
        width = 0.35
        if group.empty or group["15m_median_net_pnl"].isna().all():
            for col, metric in enumerate(("net pnl", "Sharpe")):
                axes[row, col].text(0.5, 0.5, "No eligible frozen combination", ha="center", va="center")
                axes[row, col].set_title(f"{model}: {metric}")
            continue
        for col, metric in enumerate(("net_pnl", "sharpe")):
            axes[row, col].bar(x - width / 2, group[f"15m_median_{metric}"], width, label="15m frozen")
            axes[row, col].bar(x + width / 2, group[f"1h_median_{metric}"], width, label="1h default")
            axes[row, col].axhline(0, color="black", linewidth=0.7)
            axes[row, col].set_xticks(x, PERIODS)
            axes[row, col].set_title(
                f"{model}: median {metric.replace('_', ' ')}; robust better={outcomes[model]['robust_better']}"
            )
            axes[row, col].grid(axis="y", alpha=0.2)
            axes[row, col].legend()
    fig.suptitle("15m frozen vs 1h default on identical root intersections (1 tick)")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _render_report(
    counts: Mapping[str, Any], combinations: pd.DataFrame, selected: Mapping[str, Any],
    gates: pd.DataFrame, comparisons: pd.DataFrame, outcomes: Mapping[str, Any],
    stress_failures: int,
) -> str:
    lines = [
        REPORT_START, "", "## 15 分钟四组参数研究与冻结复检（Task 7）", "",
        "本节是在既有 1h 六模型结果之后追加的独立实验。四组参数与三模型均预先冻结；"
        "选参只读取 validation，review 仅在每族唯一组合冻结后查看。复检段仍是二次验证，不是全新样本外。", "",
        f"- 1 tick：49 roots × 4 组合 × 3 模型 × 3 区间，完整网格应有 1764 行；"
        f"实际有效 {counts['detail_rows_1tick']} 行，有效合约/组合 {counts['valid_combinations']}/196，"
        f"失败组合 {counts['failed_combinations']}。",
        f"- 1 tick solvency：insolvent {counts['insolvent_rows_1tick']} 行，未知状态 "
        f"{counts['unknown_solvency_rows_1tick']} 行；非正权益对应 Sharpe 保留 NaN，未填零或删品种。",
        "- 具体非正权益记录：" + (
            "；".join(
                f"{r['vt_symbol']}/{r['model']}/{r['param_set']}/{r['period']}："
                f"min_balance={r['min_balance']:.6g}，invalid_log_days={r['invalid_log_return_days']}"
                for r in counts["insolvent_records_1tick"]
            ) if counts["insolvent_records_1tick"] else "无"
        ) + "。",
        f"- 2 tick 仅运行 validation 冻结组合；复检新增失败记录 {stress_failures}。", "",
        "### 验证段四组合完整披露", "",
        one_hour._markdown_table(combinations, [
            "model", "param_set", "n_roots", "active_roots", "required_active_roots",
            "q_open_entries", "nqqe_open_entries", "activity_eligible", "median_sharpe",
            "median_net_pnl", "improved_roots",
        ]), "",
        "### 冻结结果与同 root 对照", "",
    ]
    for model in research.Q_MODELS:
        choice = selected.get(model)
        lines.append(f"- **{model}**：" + (f"冻结 `{choice['param_set']}`。" if choice else "无组合满足 validation 活跃门槛，未冻结、未进入模拟盘候选。"))
    if not comparisons.empty:
        report_comparisons = comparisons.rename(columns={
            "15m_median_net_pnl": "fifteen_median_net_pnl",
            "1h_median_net_pnl": "one_hour_median_net_pnl",
            "15m_median_sharpe": "fifteen_median_sharpe",
            "1h_median_sharpe": "one_hour_median_sharpe",
        })
        lines.extend(["", one_hour._markdown_table(report_comparisons, [
            "model", "param_set", "period", "slippage_ticks", "n_roots",
            "fifteen_median_net_pnl", "one_hour_median_net_pnl", "median_net_pnl_delta",
            "fifteen_median_sharpe", "one_hour_median_sharpe", "median_sharpe_delta",
        ], headers=[
            "model", "param_set", "period", "slippage_ticks", "n_roots",
            "15m_median_net_pnl", "1h_median_net_pnl", "median_net_pnl_delta",
            "15m_median_sharpe", "1h_median_sharpe", "median_sharpe_delta",
        ])])
    if not gates.empty:
        lines.extend(["", "### Review 过滤与 candidate 门槛", "", one_hour._markdown_table(gates, [
            "model", "param_set", "slippage_ticks", "n_roots", "improved_net_pnl_roots",
            "required_roots", "review_active_roots", "review_open_entries",
            "nqqe_review_open_entries", "filter_pass", "profitable_roots",
            "candidate", "double_cost_same_direction", "double_cost_pass",
        ])])
    lines.extend(["", "### 判定", ""])
    for model, outcome in outcomes.items():
        lines.append(
            f"- **{model}**：robust_better={outcome['robust_better']}；{outcome['reason']}；"
            f"条件={outcome.get('conditions', {})}。"
        )
    if not any(item["robust_better"] for item in outcomes.values()):
        lines.extend(["", "没有 Bayesian Q 组合满足第 11.3 节全部条件，因此不能称 15 分钟稳定优于 1 小时默认组；保留原 1h 结论，不再围绕 review 调参。"])
    lines.extend(["", "图表：`articles/images/bayesian-q-timeframe-validation.png` 与 `bayesian-q-timeframe-review.png`。"
                  "机器可读结果位于 `research/bayesian-q-parameter-data/`。", "", REPORT_END, ""])
    return "\n".join(lines)


def append_report(block: str, path: Path = REPORT_PATH) -> None:
    text = path.read_text(encoding="utf-8")
    if REPORT_START in text and REPORT_END in text:
        before = text.split(REPORT_START, 1)[0].rstrip()
        after = text.split(REPORT_END, 1)[1].lstrip()
        text = before + "\n\n" + block + ("\n" + after if after else "")
    else:
        text = text.rstrip() + "\n\n" + block
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-only", action="store_true", help="仅验证完整性、冻结组合和生成验证图")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv)
    detail = _read(DATA_DIR / "batch_detail.csv")
    inventory = _read(DATA_DIR / "contract_inventory.csv")
    failures = _read(DATA_DIR / "contract_failures.csv")
    hourly = _read(SOURCE_DIR / "batch_detail.csv")
    counts = validate_one_tick(detail, inventory, failures)
    selection, combinations = freeze_selection(detail)
    combinations.to_csv(DATA_DIR / "validation_selection.csv", index=False)
    plot_validation(combinations, IMAGE_DIR / "bayesian-q-timeframe-validation.png")
    if args.freeze_only:
        _write_json(DATA_DIR / "selection.json", {"counts": counts, **selection})
        print(json.dumps(one_hour._json_value(selection["selected"]), ensure_ascii=False))
        return 0
    previous = json.loads((DATA_DIR / "selection.json").read_text(encoding="utf-8"))
    # 复检后重算 validation 冻结组合必须一致；NaN/JSON null 不影响组合身份。
    previous_frozen = {
        model: (choice or {}).get("param_set")
        for model, choice in previous["selected"].items()
    }
    current_frozen = {
        model: (choice or {}).get("param_set")
        for model, choice in selection["selected"].items()
    }
    if previous_frozen != current_frozen:
        raise ValueError("复检后的 validation 冻结结果发生变化，停止分析")
    selected = selection["selected"]
    expected_stress = {
        choice["param_set"] for choice in selected.values() if choice
    }
    two = detail[detail["slippage_ticks"].astype(int).eq(2)]
    if set(two["param_set"]) != expected_stress:
        raise ValueError(
            f"2-tick 只能包含冻结组合: 实际={sorted(set(two['param_set']))}，"
            f"冻结={sorted(expected_stress)}"
        )
    for param_set in expected_stress:
        stress = two[two["param_set"].eq(param_set)]
        for contract in inventory.itertuples():
            group = stress[stress["vt_symbol"].eq(contract.vt_symbol)]
            actual = set(zip(group["model"], group["period"]))
            expected = {(m, p) for m in research.MODELS for p in research.base.PERIODS}
            if actual != expected:
                raise ValueError(f"冻结 2-tick 网格不完整: {contract.vt_symbol}/{param_set}")
    gates, root_comparisons = evaluate_frozen_review(detail, inventory, selected)
    comparisons = compare_same_roots(detail, hourly, selected)
    outcomes = decide_robust_better(selected, gates, comparisons)
    gates.to_csv(DATA_DIR / "review_gates.csv", index=False)
    root_comparisons.to_csv(DATA_DIR / "review_root_comparisons.csv", index=False)
    comparisons.to_csv(DATA_DIR / "timeframe_comparisons.csv", index=False)
    plot_review(comparisons, outcomes, IMAGE_DIR / "bayesian-q-timeframe-review.png")
    stress_failures = 0 if failures.empty else int(failures["slippage_ticks"].astype(str).eq("2").sum())
    summary = {
        "counts": counts, **selection, "review_gates": gates.to_dict("records"),
        "timeframe_comparisons": comparisons.to_dict("records"), "outcomes": outcomes,
        "stress_failure_records": stress_failures,
        "no_further_tuning_after_review": True,
    }
    _write_json(DATA_DIR / "analysis_summary.json", summary)
    if not args.no_report:
        append_report(_render_report(
            counts, combinations, selected, gates, comparisons, outcomes, stress_failures
        ))
    print(json.dumps(one_hour._json_value(outcomes), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
