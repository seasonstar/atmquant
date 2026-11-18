#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""15 分钟四组冻结参数的 1-tick 研究与唯一组合 2-tick 复检。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import traceback
from typing import Any, Mapping, Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.strategies.bayesian_q_strategy import BayesianQStrategy
from scripts import batch_backtest_bayesian_q as base

OUTPUT_DIR = PROJECT_ROOT / "research" / "bayesian-q-parameter-data"
SOURCE_DIR = PROJECT_ROOT / "research" / "bayesian-q-data"
MODELS = ("nqqe", "bayes_q_legacy", "bayes_q_fixed")
Q_MODELS = ("bayes_q_legacy", "bayes_q_fixed")
PARAM_SETS = {
    "default": {"signal_minutes": 15, "bb_period": 20, "bb_stddev_mult": 2.5, "bayes_lookback": 20, "lower_threshold": 0.15, "rsi_period": 14, "rsi_smoothing": 5, "atrrsi_multiplier": 4.236},
    "fast": {"signal_minutes": 15, "bb_period": 14, "bb_stddev_mult": 2.5, "bayes_lookback": 14, "lower_threshold": 0.15, "rsi_period": 10, "rsi_smoothing": 3, "atrrsi_multiplier": 4.236},
    "slow": {"signal_minutes": 15, "bb_period": 34, "bb_stddev_mult": 2.5, "bayes_lookback": 34, "lower_threshold": 0.15, "rsi_period": 21, "rsi_smoothing": 7, "atrrsi_multiplier": 4.236},
    "strict": {"signal_minutes": 15, "bb_period": 20, "bb_stddev_mult": 2.5, "bayes_lookback": 20, "lower_threshold": 0.25, "rsi_period": 14, "rsi_smoothing": 5, "atrrsi_multiplier": 4.236},
}
DETAIL_FIELDS = ["root", "vt_symbol", "model", "param_set", "signal_minutes", *[f for f in base.DETAIL_FIELDS if f not in {"root", "vt_symbol", "model"}], "open_entries"]
TRADE_FIELDS = ["root", "vt_symbol", "model", "param_set", "signal_minutes", *[f for f in base.TRADE_FIELDS if f not in {"root", "vt_symbol", "model"}]]
FAILURE_FIELDS = [*base.FAILURE_FIELDS, "param_set", "signal_minutes"]


def _open_entries(trades: Sequence[Mapping[str, Any]], period: str) -> int:
    return sum(str(row.get("offset", "")).casefold() in {"open", "开"} and base.get_research_period(datetime.fromisoformat(str(row["datetime"])).date()) == period for row in trades)


def _run_model(contract: Mapping[str, Any], model: str, param_set: str, slippage_ticks: int, warmup_bars: list, bars: list) -> tuple[list[dict], list[dict]]:
    """复用 1h 批量的真实引擎、成本、成交审计与逐段 solvency 指标。"""
    engine = base._make_engine(contract, slippage_ticks)
    messages: list[str] = []
    engine.output = lambda text: messages.append(str(text))
    engine.load_bar = lambda *args, **kwargs: warmup_bars
    setting = {"model": model, "fixed_size": 1, **PARAM_SETS[param_set]}
    engine.add_strategy(BayesianQStrategy, dict(setting))
    actual = engine.strategy.get_parameters()
    for key, expected in setting.items():
        if actual.get(key) != expected:
            raise RuntimeError(f"{contract['vt_symbol']} 参数 {key} 被外部配置覆盖: 期望 {expected!r}，实际 {actual.get(key)!r}")
    engine.history_data = bars
    engine.run_backtesting()
    base.ensure_backtest_completed(messages, engine.strategy, bars[-1])
    result_df = engine.calculate_result()
    base.add_fixed_fees(result_df, list(engine.trades.values()), contract["fixed_fee"])
    trade_rows = base._trade_rows(contract, model, slippage_ticks, engine)
    fill_audit = base._audit_trade_fills(trade_rows, vt_symbol=contract["vt_symbol"], model=model)
    for row in trade_rows:
        row.update(param_set=param_set, signal_minutes=15)
    expected_first, expected_final = base._expected_session_bounds(contract)
    first_signal = engine.strategy.first_signal_datetime
    last_trade = trade_rows[-1]["datetime"] if trade_rows else ""
    rows = []
    for period in base.PERIODS:
        period_df = result_df[[base.get_research_period(day) == period for day in result_df.index]]
        rows.append({
            "root": contract["root"], "vt_symbol": contract["vt_symbol"], "model": model,
            "param_set": param_set, "signal_minutes": 15, "period": period,
            "slippage_ticks": slippage_ticks, "fixed_size": 1, "size": contract["size"],
            "pricetick": contract["pricetick"], "rate": contract["rate"],
            "fixed_fee": contract["fixed_fee"], "price_slippage": contract["pricetick"] * slippage_ticks,
            "warmup_bars": len(warmup_bars), "bars_loaded": len(bars),
            "first_bar": str(bars[0].datetime), "last_bar": str(bars[-1].datetime),
            "expected_first_bar": expected_first.isoformat(), "expected_final_bar": expected_final.isoformat(),
            "first_signal": base._iso(first_signal), "final_position": int(engine.strategy.pos),
            "audit_records": len(engine.strategy.audit_records), "executed_trades": len(trade_rows),
            "traded_volume": sum(row["volume"] for row in trade_rows), "last_trade_datetime": last_trade,
            **fill_audit, **base.calculate_period_metrics(period_df),
            "open_entries": _open_entries(trade_rows, period),
        })
    return rows, trade_rows


def _write_frame(path: Path, records: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    frame = pd.DataFrame(records)
    columns = list(dict.fromkeys([*fields, *frame.columns]))
    frame.reindex(columns=columns).to_csv(path, index=False)


def _append_detail(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    new = pd.DataFrame(rows).reindex(columns=DETAIL_FIELDS)
    if path.exists() and path.stat().st_size:
        old = pd.read_csv(path)
        combined = pd.concat([old, new], ignore_index=True) if not old.empty else new
    else:
        combined = new
    combined = combined.drop_duplicates(subset=["root", "vt_symbol", "model", "param_set", "period", "slippage_ticks"], keep="last")
    combined.reindex(columns=DETAIL_FIELDS).to_csv(path, index=False)


def _prune_combination(output_dir: Path, vt_symbol: str, param_set: str, cost: int) -> None:
    detail_path = output_dir / "batch_detail.csv"
    remaining = []
    if detail_path.exists() and detail_path.stat().st_size:
        for row in pd.read_csv(detail_path).to_dict("records"):
            same = str(row["vt_symbol"]).casefold() == vt_symbol.casefold() and row["param_set"] == param_set and int(row["slippage_ticks"]) == cost
            if not same:
                remaining.append(row)
    _write_frame(detail_path, remaining, DETAIL_FIELDS)
    safe = base._safe_symbol(vt_symbol)
    for path in output_dir.glob(f"trades_{safe}_{param_set}_*_slippage{cost}.csv"):
        path.unlink()


def _save_combination(output_dir: Path, result: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _append_detail(output_dir / "batch_detail.csv", result["rows"])
    metadata = result["metadata"]
    safe = base._safe_symbol(metadata["vt_symbol"])
    for model in MODELS:
        _write_frame(output_dir / f"trades_{safe}_{metadata['param_set']}_{model}_slippage{metadata['slippage_ticks']}.csv", result["trades"].get(model, []), TRADE_FIELDS)
    stem = f"{safe}-{metadata['param_set']}-slippage{metadata['slippage_ticks']}"
    base._write_json(output_dir / f"{stem}-metadata.json", metadata)


def _read_failures(path: Path) -> list[dict]:
    if not path.exists() or not path.stat().st_size:
        return []
    return pd.read_csv(path, keep_default_na=False).to_dict("records")


def _write_metadata(output_dir: Path, **extra: Any) -> None:
    payload = {
        "signal_minutes": 15, "models": list(MODELS), "param_sets": PARAM_SETS,
        "periods": base._base_metadata([])["periods"], "capital": base.CAPITAL,
        "source_inventory": str(SOURCE_DIR / "contract_inventory.csv"),
        "selection_policy": "validation only; review excluded before select_parameters",
        "stress_policy": "2 ticks accepts exactly one frozen param_set per invocation",
        "solvency_policy": "沿用已审查 calculate_period_metrics；非正余额/前值的 Sharpe=NaN，实际 pnl/return/drawdown 与全部 solvency 字段原样保留。", **extra,
    }
    base._write_json(output_dir / "metadata.json", payload)


def run_batch(contracts: Sequence[Mapping[str, Any]], slippage_ticks: int, param_sets: Sequence[str], models: Sequence[str] = MODELS, *, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    """每合约只加载一次；每完成一个 param_set 的三模型立即落盘。"""
    if slippage_ticks not in (1, 2):
        raise ValueError("slippage_ticks 只允许 1 或 2")
    param_sets, models = tuple(param_sets), tuple(models)
    if not param_sets or len(set(param_sets)) != len(param_sets) or any(n not in PARAM_SETS for n in param_sets):
        raise ValueError("param_sets 必须非空、不重复且已冻结")
    if slippage_ticks == 2 and len(param_sets) != 1:
        raise ValueError("2-tick 冻结复检每次只接受唯一 param_set")
    if models != MODELS:
        raise ValueError(f"研究模型必须完整且顺序固定为 {MODELS}")
    output_dir.mkdir(parents=True, exist_ok=True)
    failure_path = output_dir / "contract_failures.csv"
    failures, errors, completed, all_rows = _read_failures(failure_path), [], [], []
    for contract in contracts:
        resolved = base._resolve_contract(contract)
        try:
            warmup_bars, bars = base._load_bars(resolved)
        except Exception as exc:
            for param_set in param_sets:
                failures.append({"root": resolved["root"], "vt_symbol": resolved["vt_symbol"], "exchange": resolved.get("exchange", ""), "slippage_ticks": slippage_ticks, "param_set": param_set, "signal_minutes": 15, "reason": "backtest_failed", "detail": str(exc), "exception_type": type(exc).__name__, "traceback": traceback.format_exc()})
                errors.append({"vt_symbol": resolved["vt_symbol"], "param_set": param_set, "detail": str(exc)})
            _write_frame(failure_path, failures, FAILURE_FIELDS)
            print(f"数据失败 {resolved['vt_symbol']}: {exc}", flush=True)
            continue
        for param_set in param_sets:
            _prune_combination(output_dir, resolved["vt_symbol"], param_set, slippage_ticks)
            failures = [row for row in failures if not (str(row.get("vt_symbol", "")).casefold() == resolved["vt_symbol"].casefold() and str(row.get("slippage_ticks", "")) == str(slippage_ticks) and row.get("param_set") == param_set)]
            try:
                rows, trades = [], {}
                for model in models:
                    model_rows, model_trades = _run_model(resolved, model, param_set, slippage_ticks, warmup_bars, bars)
                    rows.extend(model_rows)
                    trades[model] = model_trades
                all_trades = [row for values in trades.values() for row in values]
                metadata = {"root": resolved["root"], "vt_symbol": resolved["vt_symbol"], "param_set": param_set, "parameters": PARAM_SETS[param_set], "models": list(models), "signal_minutes": 15, "slippage_ticks": slippage_ticks, "fixed_size": 1, "bars_loaded": len(bars), "warmup_bars": len(warmup_bars), "first_bar": str(bars[0].datetime), "last_bar": str(bars[-1].datetime), "executed_trades": len(all_trades), **base._audit_trade_fills(all_trades, vt_symbol=resolved["vt_symbol"], model="ALL")}
                _save_combination(output_dir, {"rows": rows, "trades": trades, "metadata": metadata})
                completed.append(f"{resolved['vt_symbol']}:{param_set}")
                all_rows.extend(rows)
                print(f"完成 {resolved['vt_symbol']} {param_set} cost={slippage_ticks}", flush=True)
            except Exception as exc:
                _prune_combination(output_dir, resolved["vt_symbol"], param_set, slippage_ticks)
                error = {"root": resolved["root"], "vt_symbol": resolved["vt_symbol"], "exchange": resolved.get("exchange", ""), "slippage_ticks": slippage_ticks, "param_set": param_set, "signal_minutes": 15, "reason": "backtest_failed", "detail": str(exc), "exception_type": type(exc).__name__, "traceback": traceback.format_exc()}
                failures.append(error)
                errors.append(error)
                print(f"失败 {resolved['vt_symbol']} {param_set}: {exc}", flush=True)
            _write_frame(failure_path, failures, FAILURE_FIELDS)
        base._release_database()
    _write_metadata(output_dir, last_run={"slippage_ticks": slippage_ticks, "param_sets": list(param_sets), "completed_combinations": completed, "detail_rows": len(all_rows), "errors": errors})
    return {"rows": all_rows, "failures": failures, "errors": errors, "completed_combinations": completed}


def _validation_frame(rows: Sequence[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """唯一 period 入口；review/train 在类型转换后立即、永久排除。"""
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if "period" not in frame.columns:
        raise ValueError("选参输入必须显式包含 period")
    return frame.loc[frame["period"].eq("validation")].copy()


def summarize_parameter_combinations(rows: Sequence[Mapping[str, Any]] | pd.DataFrame, model: str) -> list[dict[str, Any]]:
    if model not in Q_MODELS:
        raise ValueError("model 必须是 bayes_q_legacy 或 bayes_q_fixed")
    validation = _validation_frame(rows)
    if validation.empty:
        return []
    validation = validation[validation["slippage_ticks"].astype(int).eq(1)]
    combinations = []
    for param_set in PARAM_SETS:
        q = validation[validation["model"].eq(model) & validation["param_set"].eq(param_set)]
        n = validation[validation["model"].eq("nqqe") & validation["param_set"].eq(param_set)]
        paired = q.merge(n, on="root", suffixes=("_q", "_nqqe"), how="inner", validate="one_to_one")
        n_roots = len(paired)
        required = math.ceil(2 * n_roots / 3) if n_roots else 0
        active = int((paired["open_entries_q"] > 0).sum()) if n_roots else 0
        q_entries = int(paired["open_entries_q"].sum()) if n_roots else 0
        n_entries = int(paired["open_entries_nqqe"].sum()) if n_roots else 0
        entry_ratio = q_entries / n_entries if n_entries else (math.inf if q_entries else 0.0)
        median_sharpe = float(paired["sharpe_ratio_q"].median(skipna=False)) if n_roots else math.nan
        median_pnl = float(paired["total_net_pnl_q"].median(skipna=False)) if n_roots else math.nan
        improved = int((paired["total_net_pnl_q"] > paired["total_net_pnl_nqqe"]).sum()) if n_roots else 0
        combinations.append({"model": model, "param_set": param_set, "n_roots": n_roots, "required_active_roots": required, "active_roots": active, "q_open_entries": q_entries, "nqqe_open_entries": n_entries, "entry_ratio": entry_ratio, "activity_eligible": bool(n_roots and active >= required and q_entries >= 0.2 * n_entries), "median_sharpe": median_sharpe, "median_net_pnl": median_pnl, "improved_roots": improved})
    return combinations


def select_parameters(rows: Sequence[Mapping[str, Any]] | pd.DataFrame, model: str) -> dict[str, Any] | None:
    """仅用 validation 选参；输入中的极端 review 值不可进入任何计算。"""
    validation = _validation_frame(rows)
    combinations = summarize_parameter_combinations(validation, model)
    eligible = [row for row in combinations if row["activity_eligible"]]
    result = {"model": model, "validation_rows_seen": len(validation), "combinations": combinations, "eligible_param_sets": [r["param_set"] for r in eligible]}
    if not eligible:
        return None
    def rank(row):
        sharpe = row["median_sharpe"] if math.isfinite(row["median_sharpe"]) else -math.inf
        pnl = row["median_net_pnl"] if math.isfinite(row["median_net_pnl"]) else -math.inf
        return sharpe, pnl, row["improved_roots"]
    ranked = sorted(eligible, key=lambda row: row["param_set"])
    ranked = sorted(ranked, key=rank, reverse=True)
    best = ranked[0]
    return {**best, **result, "param_set": best["param_set"]}


def _load_contracts(path: Path) -> list[dict]:
    contracts = pd.read_csv(path).to_dict("records")
    if len(contracts) != 49:
        raise ValueError(f"1h 冻结 inventory 应为 49 合约，实际 {len(contracts)}")
    return contracts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", help="烟雾测试用 vt_symbol")
    parser.add_argument("--param-set", choices=tuple(PARAM_SETS), help="缺省跑四组；2 tick 必填")
    parser.add_argument("--slippage-ticks", type=int, choices=[1, 2], default=1)
    args = parser.parse_args(argv)
    if args.slippage_ticks == 2 and not args.param_set:
        parser.error("2-tick 复检必须显式指定唯一 --param-set")
    param_sets = (args.param_set,) if args.param_set else tuple(PARAM_SETS)
    contracts = _load_contracts(SOURCE_DIR / "contract_inventory.csv")
    if args.contract:
        contracts = [c for c in contracts if c["vt_symbol"].casefold() == args.contract.casefold()]
        if not contracts:
            parser.error("指定合约不在 49 个冻结 inventory 中")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.read_csv(SOURCE_DIR / "contract_inventory.csv").to_csv(OUTPUT_DIR / "contract_inventory.csv", index=False)
    _write_metadata(OUTPUT_DIR, inventory_roots=len(contracts))
    base._configure_settings()
    from loguru import logger
    logger.remove()
    result = run_batch(contracts, args.slippage_ticks, param_sets, output_dir=OUTPUT_DIR)
    print(json.dumps({"detail_rows": len(result["rows"]), "completed_combinations": len(result["completed_combinations"]), "errors": len(result["errors"]), "output_dir": str(OUTPUT_DIR)}, ensure_ascii=False), flush=True)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
