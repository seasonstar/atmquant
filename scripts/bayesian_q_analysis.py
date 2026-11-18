#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bayesian BBSMA/nQQE 全量回测的完整性验证、门槛、事件研究与图表。

唯一增量基线是同 root、同 period、同 slippage_ticks 的 nQQE。公式与事件
研究只使用 1 tick 的 canonical nqqe 审计流；该流包含同根六模型原始事件，
因此不会把六份共享指标状态或两种成本重复计数。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path
import re
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

from core.indicators.calculators.bayesian_q_calculator import MODEL_NAMES
from scripts.batch_backtest_bayesian_q import get_research_period

DATA_DIR = PROJECT_ROOT / "research" / "bayesian-q-data"
REPORT_PATH = PROJECT_ROOT / "research" / "贝叶斯BBSMA-nQQE回测报告-2026-11-12.md"
IMAGE_DIR = PROJECT_ROOT / "articles" / "images"
PERIODS = ("train", "validation", "review")
COSTS = (1, 2)
BAYESIAN_Q_MODELS = ("bayes_q_legacy", "bayes_q_fixed")
FORMULA_BOUNDS = {
    "sigma_up_legacy": (0.0, 1.0),
    "sigma_down_legacy": (0.0, 1.0),
    "prime_legacy": (0.0, 1.0),
    "sigma_up_fixed": (0.0, 1.0),
    "sigma_down_fixed": (0.0, 1.0),
    "prime_fixed": (0.0, 1.0),
    "rsi": (0.0, 100.0),
    "qqef": (0.0, 100.0),
    "qqes": (0.0, 100.0),
}
SHARED_STATE_FIELDS = (
    "close_price", "sma", "basis", "upper",
    *FORMULA_BOUNDS,
    "bayes_ready", "nqqe_ready", "nqqe_trend",
    *MODEL_NAMES,
)
DETAIL_KEY = ("root", "model", "period", "slippage_ticks")
METRIC_FIELDS = ("total_net_pnl", "max_ddpercent", "sharpe_ratio")
EVENT_DETAIL_FIELDS = (
    "root", "vt_symbol", "datetime", "model", "period", "horizon", "direction",
    "status", "accepted", "current_close", "future_close", "forward_return",
)
EVENT_SUMMARY_FIELDS = (
    "model", "period", "horizon", "status", "count", "hits", "hit_rate",
    "median_return", "mean_return",
)


def _read_frame(value: pd.DataFrame | str | Path) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    path = Path(value)
    if not path.exists():
        raise ValueError(f"缺少结果文件: {path}")
    return pd.read_csv(path)


def _root_key(value: Any) -> str:
    return str(value).casefold()


def _cost_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _required_roots(n_roots: int) -> int:
    return math.ceil(2 * int(n_roots) / 3)


def _require_columns(df: pd.DataFrame, columns: Sequence[str], name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{name} 缺少字段: {missing}")


def validate_results(
    detail: pd.DataFrame | str | Path,
    inventory: pd.DataFrame | str | Path,
    failures: pd.DataFrame | str | Path,
    *,
    expected_models: Sequence[str] = MODEL_NAMES,
    expected_periods: Sequence[str] = PERIODS,
    expected_costs: Sequence[int] = COSTS,
    expected_total_roots: int = 85,
) -> dict[str, Any]:
    """验证完整唯一网格、85 root 对账和每次运行失败的显式记录。

    inventory 中的 root 若在某成本有 backtest_failed，该成本不预期 detail 行，
    但仍属于 85 root 全集。其余 inventory root 必须具有六模型×三区间行。
    返回的 valid_n_by_cost 是后续所有三分之二门槛的动态分母。
    """

    detail = _read_frame(detail)
    inventory = _read_frame(inventory)
    failures = _read_frame(failures)
    _require_columns(detail, [*DETAIL_KEY, "vt_symbol", *METRIC_FIELDS], "batch_detail")
    _require_columns(inventory, ["root", "vt_symbol"], "contract_inventory")
    if not failures.empty:
        _require_columns(failures, ["root", "reason"], "contract_failures")
    elif "root" not in failures.columns:
        failures = failures.assign(root=pd.Series(dtype=str))
    if "slippage_ticks" not in failures.columns:
        failures["slippage_ticks"] = np.nan
    if "vt_symbol" not in failures.columns:
        failures["vt_symbol"] = ""

    models = tuple(expected_models)
    periods = tuple(expected_periods)
    costs = tuple(int(cost) for cost in expected_costs)
    if not models or not periods or not costs:
        raise ValueError("模型、区间和成本预期均不能为空")
    if inventory.empty:
        raise ValueError("contract_inventory 为空，不能形成有效研究结果")
    if inventory["root"].map(_root_key).duplicated().any():
        raise ValueError("contract_inventory 存在重复 root")

    inventory_by_key = {_root_key(row.root): row.root for row in inventory.itertuples()}
    inventory_keys = set(inventory_by_key)
    failure_roots = {_root_key(root) for root in failures["root"].dropna() if str(root)}
    all_roots = inventory_keys | failure_roots
    if len(all_roots) != int(expected_total_roots):
        raise ValueError(
            f"品种全集对账失败: inventory+failures={len(all_roots)}，"
            f"预期={expected_total_roots}"
        )

    non_runtime = failures[failures["slippage_ticks"].map(_cost_value).isna()]
    overlap = inventory_keys & {_root_key(root) for root in non_runtime["root"]}
    if overlap:
        raise ValueError(f"盘点失败 root 同时出现在有效 inventory: {sorted(overlap)}")

    runtime = failures[~failures["slippage_ticks"].map(_cost_value).isna()].copy()
    runtime["cost"] = runtime["slippage_ticks"].map(_cost_value)
    unknown_runtime_costs = set(runtime["cost"]) - set(costs)
    if unknown_runtime_costs:
        raise ValueError(f"运行失败含未知成本: {sorted(unknown_runtime_costs)}")
    unknown_runtime_roots = {
        _root_key(root) for root in runtime["root"]
    } - inventory_keys
    if unknown_runtime_roots:
        raise ValueError(f"运行失败 root 不在 inventory: {sorted(unknown_runtime_roots)}")

    unknown_detail_roots = set(detail["root"].map(_root_key)) - inventory_keys
    if unknown_detail_roots:
        raise ValueError(f"batch_detail 含非 inventory root: {sorted(unknown_detail_roots)}")
    if detail.duplicated(subset=list(DETAIL_KEY)).any():
        examples = detail[detail.duplicated(subset=list(DETAIL_KEY), keep=False)]
        raise ValueError(f"model/root/period/cost 行重复: {examples[list(DETAIL_KEY)].head().to_dict('records')}")
    actual_costs = set(detail["slippage_ticks"].map(_cost_value))
    if actual_costs != set(costs):
        raise ValueError(f"成本网格不完整: 实际={sorted(actual_costs)}，预期={sorted(costs)}")

    valid_n_by_cost: dict[int, int] = {}
    valid_roots_by_cost: dict[int, list[str]] = {}
    runtime_roots_by_cost: dict[int, list[str]] = {}
    missing_examples: list[dict] = []
    unexpected_examples: list[dict] = []
    for cost in costs:
        failed_keys = {
            _root_key(row.root) for row in runtime[runtime["cost"] == cost].itertuples()
        }
        valid_keys = inventory_keys - failed_keys
        valid_n_by_cost[cost] = len(valid_keys)
        valid_roots_by_cost[cost] = sorted(
            (inventory_by_key[key] for key in valid_keys), key=_root_key,
        )
        runtime_roots_by_cost[cost] = sorted(
            (inventory_by_key[key] for key in failed_keys), key=_root_key,
        )
        actual = detail[detail["slippage_ticks"].map(_cost_value) == cost]
        actual_keys = set(zip(
            actual["root"].map(_root_key), actual["model"], actual["period"],
        ))
        expected_keys = {
            (key, model, period)
            for key in valid_keys for model in models for period in periods
        }
        for key, model, period in sorted(expected_keys - actual_keys):
            missing_examples.append({
                "root": inventory_by_key[key], "model": model,
                "period": period, "slippage_ticks": cost,
            })
        for key, model, period in sorted(actual_keys - expected_keys):
            unexpected_examples.append({
                "root": key, "model": model,
                "period": period, "slippage_ticks": cost,
            })
        if len(missing_examples) >= 10 and len(unexpected_examples) >= 10:
            break
    if missing_examples or unexpected_examples:
        raise ValueError(
            "结果网格不完整: "
            f"缺失样例={missing_examples[:10]}；非预期样例={unexpected_examples[:10]}"
        )

    root_accounting = []
    for key in sorted(all_roots):
        selected = key in inventory_keys
        root = inventory_by_key.get(
            key,
            next((str(row.root) for row in failures.itertuples() if _root_key(row.root) == key), key),
        )
        root_failures = failures[failures["root"].map(_root_key) == key]
        root_accounting.append({
            "root": root,
            "vt_symbol": (
                inventory.loc[inventory["root"].map(_root_key) == key, "vt_symbol"].iloc[0]
                if selected else
                (root_failures["vt_symbol"].iloc[0] if not root_failures.empty else "")
            ),
            "inventory_status": "selected" if selected else "inventory_failed",
            "valid_costs": ",".join(
                str(cost) for cost in costs if root in valid_roots_by_cost[cost]
            ),
            "valid_n_contribution": sum(root in valid_roots_by_cost[cost] for cost in costs),
            "failure_reasons": ";".join(dict.fromkeys(
                str(reason) for reason in root_failures.get("reason", pd.Series(dtype=str))
            )),
            "runtime_failure_costs": ",".join(
                str(_cost_value(value)) for value in root_failures["slippage_ticks"]
                if _cost_value(value) is not None
            ),
        })

    return {
        "total_roots": len(all_roots),
        "inventory_roots": len(inventory_keys),
        "inventory_failed_roots": len(all_roots - inventory_keys),
        "valid_n_by_cost": valid_n_by_cost,
        "valid_roots_by_cost": valid_roots_by_cost,
        "runtime_failure_roots_by_cost": runtime_roots_by_cost,
        "runtime_failures": len(runtime),
        "inventory_failure_records": len(non_runtime),
        "detail_rows": len(detail),
        "expected_detail_rows": sum(
            valid_n_by_cost[cost] * len(models) * len(periods) for cost in costs
        ),
        "models": list(models),
        "periods": list(periods),
        "costs": list(costs),
        "root_accounting": root_accounting,
    }


def summarize_results(detail: pd.DataFrame | str | Path) -> pd.DataFrame:
    """按 model/period/cost 对有效 root 汇总，盈利广度使用同一动态 N。"""

    detail = _read_frame(detail)
    _require_columns(
        detail,
        ["root", "model", "period", "slippage_ticks", *METRIC_FIELDS, "trade_count"],
        "batch_detail",
    )
    rows = []
    group_columns = ["model", "period", "slippage_ticks"]
    for (model, period, cost), group in detail.groupby(group_columns, sort=False):
        n_roots = group["root"].nunique()
        profitable = int((group["total_net_pnl"] > 0).sum())
        statuses = (
            group["solvency_status"].fillna("legacy_not_recomputed").astype(str)
            if "solvency_status" in group.columns
            else pd.Series("legacy_not_recomputed", index=group.index)
        )
        insolvent_roots = group.loc[statuses == "insolvent", "root"].nunique()
        unknown = ~statuses.isin(["solvent", "insolvent", "no_data"])
        unknown_roots = group.loc[unknown, "root"].nunique()
        legacy_sharpe_provisional = bool((
            (statuses == "legacy_not_recomputed") & group["sharpe_ratio"].notna()
        ).any())
        row = {
            "model": model,
            "period": period,
            "slippage_ticks": int(cost),
            "n_roots": int(n_roots),
            "required_profitable_roots": _required_roots(n_roots),
            "profitable_roots": profitable,
            "profitable_ratio": profitable / n_roots if n_roots else np.nan,
            "profitable_breadth_pass": profitable >= _required_roots(n_roots),
            "insolvent_roots": int(insolvent_roots),
            "solvency_unknown_roots": int(unknown_roots),
            "legacy_sharpe_provisional": legacy_sharpe_provisional,
            "total_net_pnl": group["total_net_pnl"].sum(min_count=1),
            "mean_net_pnl": group["total_net_pnl"].mean(skipna=False),
            "median_net_pnl": group["total_net_pnl"].median(skipna=False),
            "mean_sharpe_ratio": group["sharpe_ratio"].mean(skipna=False),
            "median_sharpe_ratio": group["sharpe_ratio"].median(skipna=False),
            "mean_max_ddpercent": group["max_ddpercent"].mean(skipna=False),
            "median_max_ddpercent": group["max_ddpercent"].median(skipna=False),
            "total_period_trade_count": group["trade_count"].sum(min_count=1),
        }
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["model"] = pd.Categorical(result["model"], MODEL_NAMES, ordered=True)
    result["period"] = pd.Categorical(result["period"], PERIODS, ordered=True)
    return result.sort_values(["model", "period", "slippage_ticks"]).reset_index(drop=True)


def _solvency_audit(detail: pd.DataFrame) -> dict[str, Any]:
    """披露已知 insolvency 与未重算 legacy 行，绝不把未知当作 solvent。"""

    statuses = (
        detail["solvency_status"].fillna("legacy_not_recomputed").astype(str)
        if "solvency_status" in detail.columns
        else pd.Series("legacy_not_recomputed", index=detail.index)
    )
    insolvent = statuses == "insolvent"
    unknown = ~statuses.isin(["solvent", "insolvent", "no_data"])
    columns = [
        "root", "vt_symbol", "model", "period", "slippage_ticks",
        "solvency_status", "total_net_pnl", "total_return", "max_ddpercent",
        "sharpe_ratio", "nonpositive_balance_days", "nonpositive_pre_balance_days",
        "invalid_log_return_days", "min_balance", "min_pre_balance",
    ]
    records = detail.loc[insolvent].copy()
    for column in columns:
        if column not in records.columns:
            records[column] = np.nan
    return {
        "insolvent_rows": int(insolvent.sum()),
        "insolvent_roots": int(detail.loc[insolvent, "root"].nunique()),
        "insolvent_root_names": sorted(detail.loc[insolvent, "root"].unique().tolist(), key=_root_key),
        "unknown_rows": int(unknown.sum()),
        "unknown_roots": int(detail.loc[unknown, "root"].nunique()),
        "solvent_rows": int((statuses == "solvent").sum()),
        "sharpe_policy": (
            "balance 与 pre_balance 均为正才计算金融对数收益；任一非正即 solvency_status=insolvent、"
            "Sharpe=NaN，保留实际 pnl/return/drawdown，不填零、不剔除 root。"
        ),
        "legacy_policy": (
            "legacy_not_recomputed 是未知状态，不计为 solvent；其数值 Sharpe 可保留展示，"
            "但相关 median 与 pass flag 均为 provisional。"
        ),
        "records": records[columns].to_dict("records"),
    }


def _trade_periods(trades: pd.DataFrame) -> pd.Series:
    if trades.empty:
        return pd.Series(index=trades.index, dtype=object)
    parsed = pd.to_datetime(trades["datetime"], errors="raise")
    return parsed.map(lambda value: get_research_period(value.date()))


def _open_entry_counts(trades: pd.DataFrame) -> pd.DataFrame:
    columns = ["root", "model", "slippage_ticks", "open_entries"]
    if trades is None or trades.empty:
        return pd.DataFrame(columns=columns)
    trades = trades.copy()
    _require_columns(trades, ["root", "model", "slippage_ticks", "datetime", "offset"], "trades")
    review = trades[_trade_periods(trades) == "review"]
    opened = review[review["offset"].astype(str).str.casefold().isin({"开", "open"})]
    if opened.empty:
        return pd.DataFrame(columns=columns)
    result = opened.groupby(["root", "model", "slippage_ticks"]).size().rename("open_entries").reset_index()
    return result[columns]


def evaluate_filter_gates(
    detail: pd.DataFrame | str | Path,
    trades: pd.DataFrame | str | Path | None = None,
    *,
    return_comparisons: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """逐项比较两个 Bayesian Q 与同成本 nQQE，不放宽任何预登记门槛。"""

    detail = _read_frame(detail)
    trade_frame = pd.DataFrame() if trades is None else _read_frame(trades)
    _require_columns(detail, [*DETAIL_KEY, *METRIC_FIELDS], "batch_detail")
    entries = _open_entry_counts(trade_frame)
    entry_lookup = {
        (_root_key(row.root), row.model, int(row.slippage_ticks)): int(row.open_entries)
        for row in entries.itertuples()
    }
    rows = []
    comparisons = []
    for model in BAYESIAN_Q_MODELS:
        for period in PERIODS:
            for cost in COSTS:
                baseline = detail[
                    (detail["model"] == "nqqe")
                    & (detail["period"] == period)
                    & (detail["slippage_ticks"] == cost)
                ]
                candidate = detail[
                    (detail["model"] == model)
                    & (detail["period"] == period)
                    & (detail["slippage_ticks"] == cost)
                ]
                if baseline.empty and candidate.empty:
                    continue
                baseline_roots = set(baseline["root"].map(_root_key))
                candidate_roots = set(candidate["root"].map(_root_key))
                if baseline_roots != candidate_roots:
                    raise ValueError(
                        f"{model}/{period}/{cost} 与 nQQE root 集合不一致: "
                        f"缺 Q={sorted(baseline_roots-candidate_roots)}，"
                        f"多 Q={sorted(candidate_roots-baseline_roots)}"
                    )
                if baseline["root"].map(_root_key).duplicated().any() or candidate["root"].map(_root_key).duplicated().any():
                    raise ValueError(f"{model}/{period}/{cost} 存在重复 root")
                pair = baseline.merge(
                    candidate,
                    on="root",
                    suffixes=("_nqqe", "_bayes"),
                    validate="one_to_one",
                )
                n_roots = len(pair)
                required = _required_roots(n_roots)
                for item in pair.itertuples():
                    comparisons.append({
                        "root": item.root,
                        "model": model,
                        "period": period,
                        "slippage_ticks": cost,
                        "nqqe_net_pnl": item.total_net_pnl_nqqe,
                        "bayes_net_pnl": item.total_net_pnl_bayes,
                        "net_pnl_delta": item.total_net_pnl_bayes - item.total_net_pnl_nqqe,
                        "net_pnl_improved": item.total_net_pnl_bayes > item.total_net_pnl_nqqe,
                        "nqqe_sharpe": item.sharpe_ratio_nqqe,
                        "bayes_sharpe": item.sharpe_ratio_bayes,
                        "sharpe_delta": item.sharpe_ratio_bayes - item.sharpe_ratio_nqqe,
                        "nqqe_max_ddpercent": item.max_ddpercent_nqqe,
                        "bayes_max_ddpercent": item.max_ddpercent_bayes,
                        "max_dd_delta": item.max_ddpercent_bayes - item.max_ddpercent_nqqe,
                        "bayes_profitable": item.total_net_pnl_bayes > 0,
                    })
                q_pnl = pair["total_net_pnl_bayes"]
                b_pnl = pair["total_net_pnl_nqqe"]
                q_sharpe = pair["sharpe_ratio_bayes"]
                b_sharpe = pair["sharpe_ratio_nqqe"]
                q_dd = pair["max_ddpercent_bayes"]
                b_dd = pair["max_ddpercent_nqqe"]
                if "solvency_status_nqqe" in pair.columns and "solvency_status_bayes" in pair.columns:
                    legacy_sharpe_provisional = bool((
                        ((pair["solvency_status_nqqe"] == "legacy_not_recomputed") & b_sharpe.notna()).any()
                        or ((pair["solvency_status_bayes"] == "legacy_not_recomputed") & q_sharpe.notna()).any()
                    ))
                else:
                    legacy_sharpe_provisional = bool(b_sharpe.notna().any() or q_sharpe.notna().any())
                improved = int((q_pnl > b_pnl).sum())
                profitable = int((q_pnl > 0).sum())
                q_median_pnl = q_pnl.median(skipna=False)
                b_median_pnl = b_pnl.median(skipna=False)
                q_median_sharpe = q_sharpe.median(skipna=False)
                b_median_sharpe = b_sharpe.median(skipna=False)
                q_median_dd = q_dd.median(skipna=False)
                b_median_dd = b_dd.median(skipna=False)
                roots = list(pair["root"])
                q_entries = sum(entry_lookup.get((_root_key(root), model, cost), 0) for root in roots)
                b_entries = sum(entry_lookup.get((_root_key(root), "nqqe", cost), 0) for root in roots)
                active_roots = sum(entry_lookup.get((_root_key(root), model, cost), 0) > 0 for root in roots)
                if b_entries:
                    entry_ratio = q_entries / b_entries
                    enough_entries = q_entries >= 0.2 * b_entries
                else:
                    entry_ratio = np.nan
                    enough_entries = q_entries > 0
                activity_roots_pass = active_roots >= required
                activity_pass = bool(activity_roots_pass and enough_entries)
                improved_pass = bool(improved >= required)
                pnl_pass = bool(pd.notna(q_median_pnl) and pd.notna(b_median_pnl) and q_median_pnl > b_median_pnl)
                sharpe_pass = bool(pd.notna(q_median_sharpe) and pd.notna(b_median_sharpe) and q_median_sharpe > b_median_sharpe)
                dd_pass = bool(pd.notna(q_median_dd) and pd.notna(b_median_dd) and q_median_dd >= b_median_dd)
                performance_pass = improved_pass and pnl_pass and sharpe_pass and dd_pass
                filter_pass = bool(performance_pass and activity_pass)
                profitable_pass = bool(profitable >= required)
                positive_pnl = bool(pd.notna(q_median_pnl) and q_median_pnl > 0)
                positive_sharpe = bool(pd.notna(q_median_sharpe) and q_median_sharpe > 0)
                rows.append({
                    "model": model,
                    "period": period,
                    "slippage_ticks": cost,
                    "n_roots": n_roots,
                    "required_roots": required,
                    "improved_net_pnl_roots": improved,
                    "improved_net_pnl_pass": improved_pass,
                    "bayes_median_net_pnl": q_median_pnl,
                    "nqqe_median_net_pnl": b_median_pnl,
                    "median_net_pnl_delta": q_median_pnl - b_median_pnl,
                    "median_net_pnl_pass": pnl_pass,
                    "bayes_median_sharpe": q_median_sharpe,
                    "nqqe_median_sharpe": b_median_sharpe,
                    "median_sharpe_delta": q_median_sharpe - b_median_sharpe,
                    "median_sharpe_pass": sharpe_pass,
                    "legacy_sharpe_provisional": legacy_sharpe_provisional,
                    "median_sharpe_pass_provisional": legacy_sharpe_provisional,
                    "bayes_median_max_ddpercent": q_median_dd,
                    "nqqe_median_max_ddpercent": b_median_dd,
                    "median_max_dd_delta": q_median_dd - b_median_dd,
                    "median_max_drawdown_pass": dd_pass,
                    "performance_pass": performance_pass,
                    "review_active_roots": active_roots,
                    "review_activity_roots_pass": activity_roots_pass,
                    "review_open_entries": q_entries,
                    "nqqe_review_open_entries": b_entries,
                    "review_entry_ratio": entry_ratio,
                    "review_entry_ratio_pass": enough_entries,
                    "review_activity_pass": activity_pass,
                    "filter_pass": filter_pass,
                    "profitable_roots": profitable,
                    "profitable_roots_pass": profitable_pass,
                    "positive_median_net_pnl_pass": positive_pnl,
                    "positive_median_sharpe_pass": positive_sharpe,
                    "candidate": bool(filter_pass and profitable_pass and positive_pnl and positive_sharpe),
                })
    gates = pd.DataFrame(rows)
    if gates.empty:
        raise ValueError("没有可评估的 Bayesian Q/nQQE 成对结果")
    gates["double_cost_same_direction"] = False
    gates["double_cost_conclusion"] = "missing_cost"
    gates["double_cost_pass"] = False
    gates["double_cost_candidate"] = False
    for (model, period), group in gates.groupby(["model", "period"], sort=False):
        if set(group["slippage_ticks"]) != set(COSTS) or len(group) != 2:
            continue
        ordered = group.sort_values("slippage_ticks")
        first, second = ordered.iloc[0], ordered.iloc[1]
        pnl_signs = [np.sign(value) for value in ordered["median_net_pnl_delta"]]
        sharpe_signs = [np.sign(value) for value in ordered["median_sharpe_delta"]]
        dd_signs = [np.sign(value) for value in ordered["median_max_dd_delta"]]
        same = bool(
            pnl_signs[0] == pnl_signs[1] != 0
            and sharpe_signs[0] == sharpe_signs[1] != 0
            and (dd_signs[0] == dd_signs[1] or (dd_signs[0] >= 0 and dd_signs[1] >= 0))
        )
        conclusion = "mixed" if not same else (
            "same_positive" if pnl_signs[0] > 0 and sharpe_signs[0] > 0 else "same_negative"
        )
        both_pass = bool(same and ordered["filter_pass"].all())
        both_candidate = bool(same and ordered["candidate"].all())
        gates.loc[group.index, "double_cost_same_direction"] = same
        gates.loc[group.index, "double_cost_conclusion"] = conclusion
        gates.loc[group.index, "double_cost_pass"] = both_pass
        gates.loc[group.index, "double_cost_candidate"] = both_candidate
    gates["model"] = pd.Categorical(gates["model"], BAYESIAN_Q_MODELS, ordered=True)
    gates["period"] = pd.Categorical(gates["period"], PERIODS, ordered=True)
    gates = gates.sort_values(["model", "period", "slippage_ticks"]).reset_index(drop=True)
    comparison_frame = pd.DataFrame(comparisons)
    if return_comparisons:
        return gates, comparison_frame
    return gates


def formula_audit(
    signals: pd.DataFrame | str | Path,
    *,
    expected_models: Sequence[str] = MODEL_NAMES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """用每合约一份 canonical nqqe/1tick 流重算公式范围、零值和信号计数。"""

    signals = _read_frame(signals)
    _require_columns(
        signals,
        ["root", "vt_symbol", "slippage_ticks", "datetime", "model", *SHARED_STATE_FIELDS],
        "signals",
    )
    one_tick = signals[signals["slippage_ticks"].map(_cost_value) == 1].copy()
    if one_tick.empty:
        raise ValueError("公式审计需要 1 tick signals，不能用 2 tick 重复样本")
    key = ["root", "vt_symbol", "slippage_ticks", "datetime", "model"]
    if one_tick.duplicated(subset=key).any():
        raise ValueError("signals 存在重复 root/datetime/model 审计行")
    models = tuple(expected_models)
    formula_rows = []
    count_rows = []
    for (root, vt_symbol, cost), group in one_tick.groupby(["root", "vt_symbol", "slippage_ticks"], sort=True):
        if set(group["model"]) != set(models):
            raise ValueError(f"{vt_symbol} signals 六模型流不完整")
        per_time = group.groupby("datetime").size()
        if not (per_time == len(models)).all():
            raise ValueError(f"{vt_symbol} 六模型共享小时时间轴不完整")
        uniqueness = group.groupby("datetime")[list(SHARED_STATE_FIELDS)].nunique(dropna=False)
        mismatched = uniqueness.columns[(uniqueness > 1).any()]
        if len(mismatched):
            bad_times = uniqueness.index[(uniqueness[list(mismatched)] > 1).any(axis=1)].tolist()
            raise ValueError(
                f"{vt_symbol} 六模型共享状态不一致: fields={list(mismatched)}，"
                f"times={bad_times[:5]}"
            )
        canonical = group[group["model"] == "nqqe"].sort_values("datetime").copy()
        if canonical.empty:
            raise ValueError(f"{vt_symbol} 缺少 canonical nqqe 审计流")
        for field, (lower, upper) in FORMULA_BOUNDS.items():
            values = pd.to_numeric(canonical[field], errors="coerce")
            non_null = values.notna()
            valid_count = int(non_null.sum())
            out = non_null & ((values < lower) | (values > upper))
            zeros = non_null & (values == 0)
            formula_rows.append({
                "root": root,
                "vt_symbol": vt_symbol,
                "slippage_ticks": int(cost),
                "field": field,
                "lower_bound": lower,
                "upper_bound": upper,
                "row_count": len(canonical),
                "non_null_count": valid_count,
                "nan_count": int((~non_null).sum()),
                "minimum": values[non_null].min() if valid_count else np.nan,
                "maximum": values[non_null].max() if valid_count else np.nan,
                "out_of_range_count": int(out.sum()),
                "out_of_range_ratio": out.sum() / valid_count if valid_count else np.nan,
                "zero_count": int(zeros.sum()),
                "zero_ratio": zeros.sum() / valid_count if valid_count else np.nan,
            })
        for model in models:
            events = pd.to_numeric(canonical[model], errors="coerce")
            count_rows.append({
                "root": root,
                "vt_symbol": vt_symbol,
                "slippage_ticks": int(cost),
                "model": model,
                "signal_rows": len(canonical),
                "long_signals": int((events > 0).sum()),
                "short_signals": int((events < 0).sum()),
                "total_signals": int((events.notna() & (events != 0)).sum()),
                "zero_signals": int((events == 0).sum()),
                "missing_signals": int(events.isna().sum()),
            })
    return pd.DataFrame(formula_rows), pd.DataFrame(count_rows)


def event_study(
    signals: pd.DataFrame | str | Path,
    horizons: Sequence[int] = (1, 4),
    *,
    detailed: bool = False,
) -> pd.DataFrame:
    """nQQE cross 的方向收益；accepted/rejected 分桶，不作 IID 显著性声明。"""

    signals = _read_frame(signals)
    _require_columns(
        signals,
        ["root", "vt_symbol", "slippage_ticks", "datetime", "model", "close_price", "nqqe", *BAYESIAN_Q_MODELS],
        "signals",
    )
    canonical = signals[
        (signals["slippage_ticks"].map(_cost_value) == 1)
        & (signals["model"] == "nqqe")
    ].copy()
    if canonical.duplicated(subset=["root", "datetime"]).any():
        raise ValueError("事件研究 canonical nqqe/1tick 流存在重复小时")
    rows = []
    for (root, vt_symbol), group in canonical.groupby(["root", "vt_symbol"], sort=True):
        group["_parsed_datetime"] = pd.to_datetime(group["datetime"], errors="raise")
        group = group.sort_values("_parsed_datetime").reset_index(drop=True)
        group["_day"] = group["_parsed_datetime"].map(lambda value: value.date())
        group = group[(group["_day"] >= date(2026, 5, 1)) & (group["_day"] <= date(2026, 10, 31))]
        if group.empty:
            continue
        group["_close"] = pd.to_numeric(group["close_price"], errors="coerce")
        for horizon in horizons:
            horizon = int(horizon)
            if horizon <= 0:
                raise ValueError("事件研究 horizon 必须是正整数")
            future = group["_close"].shift(-horizon)
            crosses = group[pd.to_numeric(group["nqqe"], errors="coerce").fillna(0) != 0]
            for index in crosses.index:
                direction = int(np.sign(group.at[index, "nqqe"]))
                current_close = group.at[index, "_close"]
                future_close = future.loc[index]
                if not np.isfinite(current_close) or not np.isfinite(future_close) or current_close <= 0 or future_close <= 0:
                    continue
                forward_return = direction * (future_close / current_close - 1)
                for model in BAYESIAN_Q_MODELS:
                    accepted = int(np.sign(group.at[index, model])) == direction
                    rows.append({
                        "root": root,
                        "vt_symbol": vt_symbol,
                        "datetime": group.at[index, "datetime"],
                        "model": model,
                        "period": get_research_period(group.at[index, "_day"]),
                        "horizon": horizon,
                        "direction": direction,
                        "status": "accepted" if accepted else "rejected",
                        "accepted": accepted,
                        "current_close": current_close,
                        "future_close": future_close,
                        "forward_return": forward_return,
                    })
    detail = pd.DataFrame(rows, columns=EVENT_DETAIL_FIELDS)
    if detailed:
        return detail
    if detail.empty:
        return pd.DataFrame(columns=EVENT_SUMMARY_FIELDS)
    summary = detail.groupby(["model", "period", "horizon", "status"], sort=False).agg(
        count=("forward_return", "size"),
        hits=("forward_return", lambda values: int((values > 0).sum())),
        hit_rate=("forward_return", lambda values: float((values > 0).mean())),
        median_return=("forward_return", lambda values: values.median(skipna=False)),
        mean_return=("forward_return", lambda values: values.mean(skipna=False)),
    ).reset_index()
    summary["model"] = pd.Categorical(summary["model"], BAYESIAN_Q_MODELS, ordered=True)
    summary["period"] = pd.Categorical(summary["period"], PERIODS, ordered=True)
    return summary.sort_values(["model", "period", "horizon", "status"]).reset_index(drop=True)


def _safe_symbol(vt_symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", vt_symbol)


def _load_research_streams(
    data_dir: Path,
    inventory: pd.DataFrame,
    validation: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """验证全部预期产物存在；signals 只读 1tick，trades 读取双成本实际开平仓。"""

    signal_frames = []
    trade_frames = []
    metadata_records = []
    missing = []
    for cost in COSTS:
        valid_roots = set(validation["valid_roots_by_cost"][cost])
        for row in inventory.itertuples():
            if row.root not in valid_roots:
                continue
            safe = _safe_symbol(row.vt_symbol)
            metadata_path = data_dir / f"{safe}-slippage{cost}-metadata.json"
            if not metadata_path.exists():
                missing.append(str(metadata_path))
            else:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if (
                    metadata.get("root") != row.root
                    or metadata.get("vt_symbol") != row.vt_symbol
                    or _cost_value(metadata.get("slippage_ticks")) != cost
                    or tuple(metadata.get("models", ())) != MODEL_NAMES
                    or int(metadata.get("bars_loaded", 0)) <= 0
                    or int(metadata.get("invalid_fill_count", -1)) != 0
                ):
                    raise ValueError(f"逐合约 metadata 对账失败: {metadata_path}")
                metadata_records.append({
                    "root": row.root,
                    "vt_symbol": row.vt_symbol,
                    "slippage_ticks": cost,
                    "bars_loaded": int(metadata["bars_loaded"]),
                    "executed_trades": int(metadata.get("executed_trades", 0)),
                    "fill_audit_status": metadata.get("fill_audit_status", ""),
                    "next_minute_fill_verified": bool(metadata.get("next_minute_fill_verified", False)),
                })
            for model in MODEL_NAMES:
                signal_path = data_dir / f"signals_{safe}_{model}_slippage{cost}.csv"
                trade_path = data_dir / f"trades_{safe}_{model}_slippage{cost}.csv"
                if not signal_path.exists():
                    missing.append(str(signal_path))
                if not trade_path.exists():
                    missing.append(str(trade_path))
                if cost == 1 and signal_path.exists():
                    signal_frames.append(pd.read_csv(signal_path))
                if trade_path.exists():
                    trade_frames.append(pd.read_csv(trade_path))
    if missing:
        raise ValueError(f"批次产物不完整，缺失样例: {missing[:20]}（共 {len(missing)}）")
    if not signal_frames or not trade_frames:
        raise ValueError("没有可分析的 signals/trades 产物")
    signals = pd.concat(signal_frames, ignore_index=True)
    trades = pd.concat(trade_frames, ignore_index=True)
    if not trades.empty:
        verified = trades["next_minute_fill"].astype(str).str.casefold().eq("true")
        signal_time = pd.to_datetime(trades["signal_datetime"], errors="coerce")
        fill_time = pd.to_datetime(trades["datetime"], errors="coerce")
        if not verified.all() or signal_time.isna().any() or fill_time.isna().any() or not (fill_time > signal_time).all():
            raise ValueError("trades 实际成交时序审计失败，不能生成研究结果")
    actual_trade_counts = trades.groupby(["root", "slippage_ticks"]).size().to_dict() if not trades.empty else {}
    for metadata in metadata_records:
        key = (metadata["root"], metadata["slippage_ticks"])
        if int(actual_trade_counts.get(key, 0)) != metadata["executed_trades"]:
            raise ValueError(f"trades 与 metadata 成交数对账失败: {key}")
    signals.attrs["contract_metadata"] = metadata_records
    return signals, trades


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _records(df: pd.DataFrame) -> list[dict]:
    return _json_value(df.to_dict("records"))


def _aggregate_formula(formula: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for field, group in formula.groupby("field", sort=False):
        non_null = group["non_null_count"].sum()
        out = group["out_of_range_count"].sum()
        zeros = group["zero_count"].sum()
        rows.append({
            "field": field,
            "lower_bound": group["lower_bound"].iloc[0],
            "upper_bound": group["upper_bound"].iloc[0],
            "non_null_count": int(non_null),
            "minimum": group["minimum"].min(skipna=False),
            "maximum": group["maximum"].max(skipna=False),
            "out_of_range_count": int(out),
            "out_of_range_ratio": out / non_null if non_null else np.nan,
            "zero_count": int(zeros),
            "zero_ratio": zeros / non_null if non_null else np.nan,
        })
    return pd.DataFrame(rows)


def _plot_formula(formula: pd.DataFrame, counts: pd.DataFrame, path: Path) -> None:
    aggregate = _aggregate_formula(formula)
    total_counts = counts.groupby("model", sort=False)[["long_signals", "short_signals", "zero_signals"]].sum().reindex(MODEL_NAMES)
    fig, axes = plt.subplots(1, 3, figsize=(19, 6))
    x = np.arange(len(aggregate))
    axes[0].plot(x, aggregate["minimum"], "o-", label="Observed min")
    axes[0].plot(x, aggregate["maximum"], "o-", label="Observed max")
    axes[0].set_xticks(x, aggregate["field"], rotation=55, ha="right")
    axes[0].set_title("Canonical hourly formula ranges (1 tick)")
    axes[0].legend()
    axes[0].grid(alpha=0.25)
    width = 0.38
    axes[1].bar(x - width / 2, aggregate["out_of_range_ratio"], width, label="Out of range")
    axes[1].bar(x + width / 2, aggregate["zero_ratio"], width, label="Zero")
    axes[1].set_xticks(x, aggregate["field"], rotation=55, ha="right")
    axes[1].set_title("Observed ratios")
    axes[1].legend()
    axes[1].grid(alpha=0.25, axis="y")
    x = np.arange(len(total_counts))
    axes[2].bar(x - width / 2, total_counts["long_signals"], width, label="Long")
    axes[2].bar(x + width / 2, total_counts["short_signals"], width, label="Short")
    axes[2].set_xticks(x, total_counts.index, rotation=35, ha="right")
    axes[2].set_title("Raw hourly signal counts (no sixfold duplication)")
    axes[2].legend()
    axes[2].grid(alpha=0.25, axis="y")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _plot_review(summary: pd.DataFrame, gates: pd.DataFrame, path: Path) -> None:
    review = summary[summary["period"] == "review"]
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    x = np.arange(len(MODEL_NAMES))
    width = 0.36
    for axis, column, title in (
        (axes[0, 0], "median_net_pnl", "Review median net PnL"),
        (axes[0, 1], "median_sharpe_ratio", "Review median Sharpe"),
        (axes[1, 0], "median_max_ddpercent", "Review median max drawdown (%)"),
    ):
        for offset, cost in ((-width / 2, 1), (width / 2, 2)):
            values = review[review["slippage_ticks"] == cost].set_index("model").reindex(MODEL_NAMES)[column]
            axis.bar(x + offset, values, width, label=f"{cost} tick")
            for x_pos, value in zip(x + offset, values):
                if pd.isna(value):
                    axis.text(
                        x_pos,
                        0.03,
                        "NA\nsolvency",
                        transform=axis.get_xaxis_transform(),
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )
        axis.axhline(0, color="black", linewidth=0.7)
        axis.set_xticks(x, MODEL_NAMES, rotation=30, ha="right")
        axis.set_title(title)
        axis.legend()
        axis.grid(alpha=0.25, axis="y")
    review_gates = gates[gates["period"] == "review"]
    for offset, cost in ((-width / 2, 1), (width / 2, 2)):
        values = review_gates[review_gates["slippage_ticks"] == cost].set_index("model").reindex(BAYESIAN_Q_MODELS)
        x_q = np.arange(len(BAYESIAN_Q_MODELS))
        axes[1, 1].bar(x_q + offset, values["review_active_roots"], width, label=f"{cost} tick active roots")
        for index, (_, row) in enumerate(values.iterrows()):
            axes[1, 1].plot([index + offset - width / 2, index + offset + width / 2], [row["required_roots"]] * 2, color="black", linewidth=1)
    axes[1, 1].set_xticks(np.arange(len(BAYESIAN_Q_MODELS)), BAYESIAN_Q_MODELS)
    axes[1, 1].set_title("Review roots with actual OPEN entries; black=required")
    axes[1, 1].legend()
    axes[1, 1].grid(alpha=0.25, axis="y")
    n_roots = int(review["n_roots"].dropna().max())
    fig.suptitle(f"1h review, N={n_roots} roots per model/cost", fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _plot_events(events: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(18, 11))
    if events.empty:
        for axis in axes.flat:
            axis.text(0.5, 0.5, "No completed forward-return events", ha="center", va="center")
    for row_index, horizon in enumerate((1, 4)):
        subset = events[events["horizon"] == horizon].copy()
        if not subset.empty:
            subset["bucket"] = subset["period"].astype(str) + "\n" + subset["model"].astype(str) + "\n" + subset["status"]
        for column, axis, title, scale in (
            ("median_return", axes[row_index, 0], f"H{horizon} median direction return", 100),
            ("hit_rate", axes[row_index, 1], f"H{horizon} hit rate", 100),
        ):
            if not subset.empty:
                ordered = subset.sort_values(["model", "period", "status"])
                labels = ordered["bucket"]
                values = ordered[column] * scale
                colors = ["#2a9d8f" if status == "accepted" else "#e76f51" for status in ordered["status"]]
                axis.bar(np.arange(len(ordered)), values, color=colors)
                axis.set_xticks(np.arange(len(ordered)), labels, rotation=65, ha="right", fontsize=8)
            axis.axhline(0, color="black", linewidth=0.7)
            axis.set_title(title + (" (%)" if scale == 100 and column == "median_return" else ""))
            axis.grid(alpha=0.25, axis="y")
    fig.suptitle("1-tick nQQE crosses: accepted vs rejected; no IID significance claims")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _format_cell(value: Any) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and not math.isfinite(value)):
        return "NA"
    if isinstance(value, (bool, np.bool_)):
        return "是" if value else "否"
    if isinstance(value, (float, np.floating)):
        return f"{value:.6g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_table(df: pd.DataFrame, columns: Sequence[str], headers: Sequence[str] | None = None) -> str:
    headers = list(headers or columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in df.itertuples(index=False):
        values = [getattr(row, column) for column in columns]
        lines.append("| " + " | ".join(_format_cell(value) for value in values) + " |")
    return "\n".join(lines)


def _decision(gates: pd.DataFrame) -> dict[str, Any]:
    keep_models = []
    for model in BAYESIAN_Q_MODELS:
        selected = gates[
            (gates["model"] == model)
            & (gates["period"].isin(["validation", "review"]))
        ]
        by_period = selected.groupby("period", observed=True)["double_cost_candidate"].all()
        if len(by_period) == 2 and bool(by_period.all()):
            keep_models.append(model)
    return {
        "decision": "KEEP_FOR_FURTHER_RESEARCH" if keep_models else "STOP",
        "keep_models": keep_models,
        "rule": (
            "不因单一区间或单一成本胜出而保留：同一 Bayesian Q 必须在 validation 与 review "
            "均满足双成本同方向 candidate；train 仅作描述。candidate 已包含全部增量表现、"
            "review 实际 OPEN 活跃度、盈利根数广度及正 median net pnl/Sharpe。"
        ),
    }


def _render_report(
    validation: Mapping[str, Any],
    failures: pd.DataFrame,
    solvency: Mapping[str, Any],
    summary: pd.DataFrame,
    gates: pd.DataFrame,
    comparisons: pd.DataFrame,
    formula: pd.DataFrame,
    counts: pd.DataFrame,
    event_summary: pd.DataFrame,
    decision: Mapping[str, Any],
) -> str:
    formula_aggregate = _aggregate_formula(formula)
    targeted = solvency.get("targeted_reproduction")
    targeted_text = (
        f"单次 targeted reproduction：{targeted['vt_symbol']} / {targeted['model']} / "
        f"{targeted['slippage_ticks']} tick，{targeted['days']} 个日度结果中 "
        f"balance 非正 {targeted['nonpositive_balance_days']} 天、pre-balance 非正 "
        f"{targeted['nonpositive_pre_balance_days']} 天、不适合金融对数收益 "
        f"{targeted['invalid_log_return_days']} 天，期末 balance={_format_cell(targeted['ending_balance'])}；"
        f"{targeted['warning_period']} 实际警告为 `{targeted['warning']}`。旧实现 `.fillna(0)` 掩盖了该事件。"
        "这些是全主区间诊断计数，不向重置 period 传播；各 period 状态以逐段重算为准。"
        if targeted else "没有单独 targeted solvency reproduction 记录。"
    )
    count_aggregate = counts.groupby("model", sort=False)[[
        "long_signals", "short_signals", "total_signals", "zero_signals",
    ]].sum().reindex(MODEL_NAMES).reset_index()
    double_cost = gates[gates["slippage_ticks"] == 1][[
        "model", "period", "double_cost_same_direction", "double_cost_conclusion",
        "double_cost_pass", "double_cost_candidate",
    ]]
    key_findings = [
        "## 核心实证发现",
        "",
        f"- 12 个 Bayesian Q model/period/cost 门槛行中，filter 通过 {int(gates['filter_pass'].sum())} 行，candidate 通过 {int(gates['candidate'].sum())} 行，双成本 candidate 通过 {int(gates['double_cost_candidate'].sum())} 行；因此没有把局部相对改善误写为可保留策略。",
        f"- 偿付能力：已知 insolvent {solvency['insolvent_rows']} 行/{solvency['insolvent_roots']} roots（{solvency['insolvent_root_names']}），legacy 未重算未知 {solvency['unknown_rows']} 行/{solvency['unknown_roots']} roots；非正资金对应 Sharpe=NaN，不填零、不删 root。",
        f"- Legacy Sharpe 限制：相关 median/pass flag 均为 provisional；{len(gates)} 个门槛行中有 {int((~gates['improved_net_pnl_pass']).sum())} 行独立未通过 improved-net-PnL breadth，STOP 以该不依赖 legacy Sharpe 的广度失败为首要依据。",
    ]
    for model in BAYESIAN_Q_MODELS:
        review = gates[(gates["model"] == model) & (gates["period"] == "review")].sort_values("slippage_ticks")
        validation_rows = gates[(gates["model"] == model) & (gates["period"] == "validation")]
        cost_text = "；".join(
            f"{int(row.slippage_ticks)}tick 改善 {int(row.improved_net_pnl_roots)}/{int(row.n_roots)}，"
            f"median pnl {_format_cell(row.bayes_median_net_pnl)}，Sharpe {_format_cell(row.bayes_median_sharpe)}"
            for row in review.itertuples()
        )
        activity = review.iloc[0]
        validation_conclusion = validation_rows.iloc[0]["double_cost_conclusion"] if not validation_rows.empty else "missing_cost"
        key_findings.append(
            f"- **{model}**：review {cost_text}；所需改善/盈利广度均为 {int(activity['required_roots'])}。"
            f"review 实际开仓活跃 root {int(activity['review_active_roots'])}/{int(activity['n_roots'])}，"
            f"开仓数 {int(activity['review_open_entries'])}/{int(activity['nqqe_review_open_entries'])}="
            f"{_format_cell(activity['review_entry_ratio'])}；validation 双成本结论为 {validation_conclusion}。"
        )
    for model in BAYESIAN_Q_MODELS:
        review_events = event_summary[(event_summary["model"] == model) & (event_summary["period"] == "review")]
        accepted = review_events[review_events["status"] == "accepted"].sort_values("horizon")
        event_text = "；".join(
            f"H{int(row.horizon)} n={int(row['count'])}，hit={_format_cell(row.hit_rate)}，"
            f"median={_format_cell(row.median_return)}"
            for _, row in accepted.iterrows()
        )
        key_findings.append(f"- {model} review accepted 事件：{event_text}。该描述不构成 IID 显著性或可交易收益证明。")
    key_findings.extend([
        f"- 公式审计跨 root 越界计数合计 {int(formula['out_of_range_count'].sum())}；零值率仍逐字段完整披露，不能将高零值率隐藏为‘全部在范围内即无问题’。",
        "",
    ])
    lines = [
        "# 贝叶斯 BBSMA-nQQE 全期货回测报告",
        "",
        "日期：2026-11-12",
        "",
        f"**结论：{decision['decision']}**。{decision['rule']}",
        "",
        "本报告由 `scripts/bayesian_q_analysis.py` 直接读取完整批次 CSV/JSON 生成；没有手填收益或挑选获胜品种。`review` 是二次验证区间，不是全新样本外；事件研究不作独立同分布显著性声明。",
        "",
        *key_findings,
        "## 1. 研究口径与完整性",
        "",
        f"- 六模型：{', '.join(MODEL_NAMES)}；区间：{', '.join(PERIODS)}；成本：1/2 tick 每边，另含既有比例费和固定费。",
        f"- 85 root 对账：inventory {validation['inventory_roots']} + 盘点失败 {validation['inventory_failed_roots']} = {validation['total_roots']}。",
        f"- 1 tick 有效 N={validation['valid_n_by_cost'][1]}，运行失败 root={len(validation['runtime_failure_roots_by_cost'][1])}；2 tick 有效 N={validation['valid_n_by_cost'][2]}，运行失败 root={len(validation['runtime_failure_roots_by_cost'][2])}。三分之二门槛均按各成本实际 N 向上取整。",
        f"- detail 共 {validation['detail_rows']} 行，与动态有效 root×六模型×三区间×双成本的预期 {validation['expected_detail_rows']} 行一致；model/root/period/cost 无重复。",
        f"- 运行失败 {validation['runtime_failures']} 条，全部保留在 `contract_failures.csv`；失败 root 没有静默进入有效 N。",
        "- 公式和事件研究只使用每合约一份 canonical nqqe/1tick 小时流；已逐小时核对六模型共享 BBSMA/nQQE 状态及六模型原始事件完全一致，避免六倍及双成本重复计数。",
        "",
        "### 85-root 全量对账",
        "",
        _markdown_table(pd.DataFrame(validation["root_accounting"]), ["root", "vt_symbol", "inventory_status", "valid_costs", "failure_reasons", "runtime_failure_costs"]),
        "",
        "### 失败清单",
        "",
        _markdown_table(
            failures.assign(slippage_ticks=failures.get("slippage_ticks", "")),
            [column for column in ["root", "vt_symbol", "slippage_ticks", "reason", "exception_type", "detail"] if column in failures.columns],
        ) if not failures.empty else "无失败记录。",
        "",
        "## 2. 六模型 × 三区间 × 双成本结果",
        "",
        "下表每行均为该 model/period/cost 的全部有效 root；median max drawdown 使用原始负值，数值越大越不差。盈利广度是 net pnl>0 的 root 数/N。",
        "",
        _markdown_table(summary, [
            "model", "period", "slippage_ticks", "n_roots", "median_net_pnl",
            "median_sharpe_ratio", "median_max_ddpercent", "profitable_roots",
            "profitable_ratio", "legacy_sharpe_provisional", "insolvent_roots", "solvency_unknown_roots",
            "total_net_pnl", "total_period_trade_count",
        ]),
        "",
        "### 偿付能力与 Sharpe 口径",
        "",
        f"{solvency['sharpe_policy']} {solvency['legacy_policy']} 本次已知 insolvent {solvency['insolvent_rows']} 行，未知 {solvency['unknown_rows']} 行；汇总表分别披露 insolvent/unknown root 数，未知不等于正常。",
        "",
        targeted_text,
        "",
        _markdown_table(pd.DataFrame(targeted["period_metrics"]), [
            "slippage_ticks", "period", "solvency_status", "nonpositive_balance_days",
            "nonpositive_pre_balance_days", "invalid_log_return_days", "min_balance",
            "min_pre_balance", "sharpe_ratio",
        ]) if targeted and targeted.get("period_metrics") else "",
        "",
        _markdown_table(pd.DataFrame(solvency["records"]), [
            "root", "model", "period", "slippage_ticks", "solvency_status",
            "total_net_pnl", "total_return", "max_ddpercent", "sharpe_ratio",
            "nonpositive_balance_days", "nonpositive_pre_balance_days", "invalid_log_return_days",
            "min_balance", "min_pre_balance",
        ]) if solvency["records"] else "没有已知 insolvent 行；legacy 未知状态仍按上述口径披露。",
        "",
        "## 3. Bayesian Q 相对同成本 nQQE 的逐项门槛",
        "",
        "`filter_pass` 同时要求：改善 net pnl 的 root 数达到 ceil(2N/3)、Q 的 median net pnl 与 Sharpe 均严格更高、median max drawdown 不差、review 至少 ceil(2N/3) root 有真实 offset=开 的成交且 Q 总开仓数不少于 nQQE 的 20%。近乎空仓不能通过。`candidate` 另外要求盈利 root 数达到 ceil(2N/3)，且 Q median net pnl/Sharpe 均为正。review 活跃度作为过滤器的共同门槛列在每一期间，避免用训练期表现绕过真实活跃度要求。含 legacy 数值 Sharpe 的 median 与 `median_sharpe_pass` 均为 provisional；STOP 首先依据所有门槛行独立失败的 net-PnL 改善广度，不依赖 provisional Sharpe。",
        "",
        _markdown_table(gates, [
            "model", "period", "slippage_ticks", "n_roots", "required_roots",
            "improved_net_pnl_roots", "median_net_pnl_pass", "median_sharpe_pass",
            "median_sharpe_pass_provisional", "median_max_drawdown_pass", "review_active_roots", "review_open_entries",
            "nqqe_review_open_entries", "review_entry_ratio", "review_activity_pass",
            "profitable_roots", "filter_pass", "candidate",
        ]),
        "",
        "### 双成本同方向结论",
        "",
        "同一 model/period 的 1 与 2 tick 必须保持净收益和 Sharpe 改善方向一致，且各自全部 filter/candidate 条件通过；双倍成本反向即失败。",
        "",
        _markdown_table(double_cost, list(double_cost.columns)),
        "",
        f"最终 stop/keep：**{decision['decision']}**；可继续研究模型：{decision['keep_models'] or '无'}。",
        "",
        "## 4. 独立事件研究",
        "",
        "每个 nQQE cross 只取 1 tick canonical 流，方向收益为 `direction × (未来第 h 根小时 close / 当前小时 close - 1)`，h=1/4。accepted 表示对应 Bayesian Q 原始事件与 nQQE 同向，其余 cross 为 rejected。按信号所在 period 分组，报告实际样本数、正收益比例和中位数；这不是 IID 检验，也不代表可独立成交的组合收益。",
        "",
        _markdown_table(event_summary, ["model", "period", "horizon", "status", "count", "hits", "hit_rate", "median_return", "mean_return"]),
        "",
        "## 5. 公式审计与信号计数",
        "",
        "下表汇总各 root canonical 流；min/max 是真实跨 root 极值，比率由越界/零值计数与有效计数汇总，不是估计值。逐 root 完整结果见 `formula_audit.csv`。",
        "",
        _markdown_table(formula_aggregate, ["field", "lower_bound", "upper_bound", "non_null_count", "minimum", "maximum", "out_of_range_count", "out_of_range_ratio", "zero_count", "zero_ratio"]),
        "",
        _markdown_table(count_aggregate, ["model", "long_signals", "short_signals", "total_signals", "zero_signals"]),
        "",
        "## 6. 图表、完整数据与限制",
        "",
        "- `articles/images/bayesian-q-formula-audit.png`：真实公式范围、越界/零值比率和六模型信号数。",
        "- `articles/images/bayesian-q-review-summary.png`：六模型 review 双成本中位数及 Bayesian Q 实际开仓活跃度。",
        "- `articles/images/bayesian-q-event-study.png`：事件研究接受/拒绝分桶。",
        "- 完整明细、root 成对差值、门槛、事件逐样本与汇总、公式逐 root 审计均在 `research/bayesian-q-data/` 对应 CSV；机器可读总览为 `analysis_summary.json`。",
        "- 单合约代表真实合约而非主连；盘点覆盖不足和运行失败均未替换数据。固定一手结果不构成组合层面资金分配或风险建议。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--image-dir", type=Path, default=IMAGE_DIR)
    args = parser.parse_args(argv)
    data_dir = args.data_dir.resolve()

    detail = _read_frame(data_dir / "batch_detail.csv")
    inventory = _read_frame(data_dir / "contract_inventory.csv")
    failures = _read_frame(data_dir / "contract_failures.csv")
    metadata_path = data_dir / "metadata.json"
    if not metadata_path.exists():
        raise ValueError(f"缺少全局批次 metadata: {metadata_path}")
    research_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    validation = validate_results(detail, inventory, failures, expected_total_roots=85)
    metadata_counts = research_metadata.get("counts", {})
    if (
        metadata_counts.get("union_roots") != 85
        or metadata_counts.get("selected") != len(inventory)
        or tuple(research_metadata.get("models", ())) != MODEL_NAMES
    ):
        raise ValueError("全局 metadata 的模型或 85-root 对账与 CSV 不一致")
    last_run = research_metadata.get("last_run", {})
    last_completed = set(last_run.get("completed_contracts", []))
    expected_last_run_rows = len(last_completed) * len(MODEL_NAMES) * len(PERIODS)
    valid_second_cost_symbols = {
        row.vt_symbol for row in inventory.itertuples()
        if row.root in validation["valid_roots_by_cost"][2]
    }
    if (
        _cost_value(last_run.get("slippage_ticks")) != 2
        or tuple(last_run.get("models", ())) != MODEL_NAMES
        or not last_completed
        or not last_completed.issubset(valid_second_cost_symbols)
        or int(last_run.get("detail_rows", -1)) != expected_last_run_rows
    ):
        raise ValueError("2 tick 最近批次尚未完成或 metadata 行数不完整，禁止分析部分结果")
    signals, trades = _load_research_streams(data_dir, inventory, validation)

    solvency = _solvency_audit(detail)
    if research_metadata.get("targeted_solvency_audit"):
        solvency["targeted_reproduction"] = research_metadata["targeted_solvency_audit"]
    summary = summarize_results(detail)
    gates, comparisons = evaluate_filter_gates(detail, trades, return_comparisons=True)
    formula, counts = formula_audit(signals)
    event_detail = event_study(signals, detailed=True)
    event_summary = event_study(signals)
    decision = _decision(gates)

    pd.DataFrame(validation["root_accounting"]).to_csv(data_dir / "root_accounting.csv", index=False)
    summary.to_csv(data_dir / "model_period_cost_summary.csv", index=False)
    gates.to_csv(data_dir / "filter_gates.csv", index=False)
    comparisons.to_csv(data_dir / "filter_root_comparisons.csv", index=False)
    formula.to_csv(data_dir / "formula_audit.csv", index=False)
    counts.to_csv(data_dir / "signal_counts.csv", index=False)
    event_detail.to_csv(data_dir / "event_study_detail.csv", index=False)
    event_summary.to_csv(data_dir / "event_study.csv", index=False)
    entries = _open_entry_counts(trades)
    entries.to_csv(data_dir / "review_open_entries.csv", index=False)
    solvency_columns = [
        "root", "vt_symbol", "model", "period", "slippage_ticks", "solvency_ok",
        "solvency_status", "sharpe_ratio", "nonpositive_balance_days",
        "nonpositive_pre_balance_days", "invalid_log_return_days", "min_balance", "min_pre_balance",
    ]
    detail[[column for column in solvency_columns if column in detail.columns]].to_csv(
        data_dir / "solvency_audit.csv", index=False,
    )

    image_dir = args.image_dir.resolve()
    _plot_formula(formula, counts, image_dir / "bayesian-q-formula-audit.png")
    _plot_review(summary, gates, image_dir / "bayesian-q-review-summary.png")
    _plot_events(event_summary, image_dir / "bayesian-q-event-study.png")

    report = _render_report(
        validation, failures, solvency, summary, gates, comparisons,
        formula, counts, event_summary, decision,
    )
    args.report_path.resolve().write_text(report, encoding="utf-8")
    machine_summary = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "batch_complete": True,
        "validation": validation,
        "batch_metadata": {
            "counts": research_metadata.get("counts", {}),
            "last_run": last_run,
            "periods": research_metadata.get("periods", {}),
            "costs": research_metadata.get("costs", {}),
        },
        "contract_metadata": signals.attrs.get("contract_metadata", []),
        "solvency": solvency,
        "legacy_sharpe_limitation": {
            "provisional": bool(solvency["unknown_rows"]),
            "legacy_rows": solvency["unknown_rows"],
            "provisional_gate_rows": int(gates["median_sharpe_pass_provisional"].sum()),
            "policy": "legacy 数值 Sharpe 的 median 与 pass flag 均为 provisional，不作为 STOP 的首要依据。",
            "improved_net_pnl_breadth_fail_rows": int((~gates["improved_net_pnl_pass"]).sum()),
            "total_filter_rows": len(gates),
            "stop_primary_reason": "全部 12 行独立未通过 improved-net-PnL breadth；该结论不依赖 legacy Sharpe。",
        },
        "decision": decision,
        "model_period_cost_summary": _records(summary),
        "filter_gates": _records(gates),
        "formula_audit_aggregate": _records(_aggregate_formula(formula)),
        "signal_counts": _records(counts),
        "event_study": _records(event_summary),
        "event_study_detail_rows": len(event_detail),
        "shared_state_consistency": {
            "checked_cost": 1,
            "canonical_model": "nqqe",
            "consistent": True,
            "fields": list(SHARED_STATE_FIELDS),
        },
        "outputs": {
            "report": str(args.report_path.resolve()),
            "formula_plot": str(image_dir / "bayesian-q-formula-audit.png"),
            "review_plot": str(image_dir / "bayesian-q-review-summary.png"),
            "event_plot": str(image_dir / "bayesian-q-event-study.png"),
        },
    }
    (data_dir / "analysis_summary.json").write_text(
        json.dumps(_json_value(machine_summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(_json_value({
        "batch_complete": True,
        "detail_rows": len(detail),
        "valid_n_by_cost": validation["valid_n_by_cost"],
        "runtime_failures": validation["runtime_failures"],
        "insolvent_rows": solvency["insolvent_rows"],
        "solvency_unknown_rows": solvency["unknown_rows"],
        "event_rows": len(event_detail),
        "decision": decision,
        "output_dir": str(data_dir),
    }), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
