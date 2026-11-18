#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随机森林/逻辑回归日线方向预测与朴素动量基线的批量研究。

自包含批量程序：18 个品种 9999 主连日线（比例平滑，由 extract_futures_daily.py
产出）、日收盘决策次开盘撮合、训练/验证/复检三段评估。两模型共用同一特征
管线与网格，参数只在训练与验证段选择，复检段不参与排名；另跑双倍滑点压力。
协议见 research/随机森林方向预测研究方案-2026-11-17.md。
"""

import json
import subprocess
import sys
from datetime import date, datetime
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401 应用 .env 到 vnpy SETTINGS
from config.futures_config import get_futures_info
from core.strategies.random_forest_direction_strategy import (
    MomentumBaselineDailyStrategy,
    RandomForestDirectionStrategy,
)
from scripts.batch_backtest_logistic_direction import (
    add_fixed_fees,
    calculate_period_metrics,
    ensure_backtest_completed,
)
from vnpy.trader.constant import Exchange, Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine

OUTPUT_DIR = PROJECT_ROOT / "research"
DATA_DIR = PROJECT_ROOT / "research" / "rf-direction-data"
RESULT_DATE = "2026-11-18"

CAPITAL = 200_000
START = datetime(2016, 4, 1)
END_CUTOFF = datetime(2026, 10, 30, 23, 59)
WARMUP_END = date(2016, 4, 1)
LAST_MAIN_DAY = date(2026, 10, 30)
MIN_DAILY_DAYS = 2300

EXCHANGES = {
    "SHFE": Exchange.SHFE,
    "DCE": Exchange.DCE,
    "CZCE": Exchange.CZCE,
}

CONTRACTS = [
    ("rb", "SHFE"), ("hc", "SHFE"), ("i", "DCE"), ("j", "DCE"), ("jm", "DCE"),
    ("MA", "CZCE"), ("TA", "CZCE"), ("FG", "CZCE"), ("RM", "CZCE"),
    ("m", "DCE"), ("y", "DCE"),
    ("au", "SHFE"), ("ag", "SHFE"), ("al", "SHFE"), ("ni", "SHFE"), ("sn", "SHFE"),
    ("bu", "SHFE"), ("fu", "SHFE"),
]

MODELS = ("random_forest", "logistic")
PARAMETER_KEYS = ["train_window", "prob_threshold"]
MODEL_GRID = [
    {
        "train_window": train_window,
        "prob_threshold": prob_threshold,
        "label_horizon": 5,
        "retrain_interval": 21,
        "max_size": 2,
    }
    for train_window, prob_threshold in product([750, 1500], [0.05, 0.10])
]
BASELINE_SETTING = {
    "momentum_window": 21,
    "fixed_size": 1,
}


def get_research_period(day: date) -> str:
    if day <= date(2022, 12, 31):
        return "train"
    if day <= date(2023, 12, 31):
        return "validation"
    return "review"


def build_bars(contract: tuple[str, str]) -> tuple[list, list]:
    """读日线 parquet 构造 BarData，切分预热与主区间并做完整性校验。"""
    root, exchange = contract
    parquet = DATA_DIR / f"daily_{root}.parquet"
    if not parquet.exists():
        raise RuntimeError(f"缺少 {parquet}，请先运行 extract_futures_daily.py")
    daily = pd.read_parquet(parquet)
    daily = daily[daily.index.date <= LAST_MAIN_DAY]  # 剔除末端不完整交易日
    if len(daily) < MIN_DAILY_DAYS:
        raise RuntimeError(f"{root}9999 日线仅 {len(daily)} 根，低于门槛 {MIN_DAILY_DAYS}")
    if daily.index[-1].date() < LAST_MAIN_DAY:
        raise RuntimeError(f"{root}9999 最后交易日 {daily.index[-1].date()} 未覆盖到 {LAST_MAIN_DAY}")

    symbol = f"{root}9999"
    exchange_enum = EXCHANGES[exchange]
    bars = []
    for day, row in daily.iterrows():
        bars.append(_make_bar(symbol, exchange_enum, day, row))
    warmup_bars = [b for b in bars if b.datetime.date() < WARMUP_END]
    main_bars = [b for b in bars if START <= b.datetime <= END_CUTOFF]
    if len(warmup_bars) < 55:
        raise RuntimeError(f"{symbol} 预热日线不足: {len(warmup_bars)}")
    return warmup_bars, main_bars


def _make_bar(symbol: str, exchange_enum, day, row):
    from vnpy.trader.object import BarData

    return BarData(
        gateway_name="BACKTESTING",
        symbol=symbol,
        exchange=exchange_enum,
        datetime=pd.Timestamp(day).replace(hour=15, minute=0),
        interval=Interval.DAILY,
        open_price=float(row["open"]),
        high_price=float(row["high"]),
        low_price=float(row["low"]),
        close_price=float(row["close"]),
        volume=float(row["volume"]),
        turnover=0.0,
        open_interest=0.0,
    )


def _make_engine(contract: tuple[str, str], slippage_ticks: int) -> BacktestingEngine:
    root, exchange = contract
    info = get_futures_info(root)
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=f"{root}9999.{exchange}",
        interval=Interval.DAILY,
        start=START,
        end=END_CUTOFF,
        rate=info["rate"],
        slippage=info["pricetick"] * slippage_ticks,
        size=info["size"],
        pricetick=info["pricetick"],
        capital=CAPITAL,
    )
    return engine


def _run_setting(
    contract: tuple[str, str],
    model: str,
    setting: dict,
    warmup_bars: list,
    bars: list,
    slippage_ticks: int,
) -> list[dict]:
    root, exchange = contract
    vt_symbol = f"{root}9999.{exchange}"
    info = get_futures_info(root)
    engine = _make_engine(contract, slippage_ticks)
    messages = []
    engine.output = lambda text: messages.append(str(text))
    engine.load_bar = lambda *args, **kwargs: warmup_bars
    if model == "baseline":
        strategy_class = MomentumBaselineDailyStrategy
        run_setting = dict(setting)
    else:
        strategy_class = RandomForestDirectionStrategy
        run_setting = {**setting, "model_kind": model}
    engine.add_strategy(strategy_class, dict(run_setting))
    actual = engine.strategy.get_parameters()
    for key, value in run_setting.items():
        if key in actual and actual[key] != value:
            raise RuntimeError(f"{vt_symbol} 参数 {key} 被外部配置覆盖")
    engine.history_data = bars
    engine.run_backtesting()
    ensure_backtest_completed(messages, engine.strategy, bars[-1])
    df = engine.calculate_result()
    add_fixed_fees(df, list(engine.trades.values()), fixed_fee=info["slippage"])

    rows = []
    for period in ["train", "validation", "review"]:
        period_df = df[[get_research_period(day) == period for day in df.index]]
        metrics = calculate_period_metrics(period_df, capital=CAPITAL)
        rows.append({
            "model": model,
            **setting,
            "root": root,
            "vt_symbol": vt_symbol,
            "period": period,
            "slippage_ticks": slippage_ticks,
            "warmup_bars": len(warmup_bars),
            "bars_loaded": len(bars),
            "first_bar": str(bars[0].datetime),
            "last_bar": str(bars[-1].datetime),
            "first_signal": str(getattr(engine.strategy, "first_signal_datetime", "")),
            "final_position": int(engine.strategy.pos),
            **metrics,
        })
    return rows


def run_contract(
    contract: tuple[str, str],
    slippage_ticks: int = 1,
    models: tuple[str, ...] = MODELS,
    grid: list[dict] | None = None,
    include_baseline: bool = True,
) -> list[dict]:
    root, exchange = contract
    vt_symbol = f"{root}9999.{exchange}"
    grid = grid or MODEL_GRID
    warmup_bars, bars = build_bars(contract)
    rows = []
    for model in models:
        for setting in grid:
            rows.extend(_run_setting(
                contract, model, setting, warmup_bars, bars, slippage_ticks
            ))
    if include_baseline:
        rows.extend(_run_setting(
            contract, "baseline", BASELINE_SETTING, warmup_bars, bars, slippage_ticks
        ))
    print(f"完成 {vt_symbol}，{len(rows) // 3} 组回测，{len(bars)} 根日线", flush=True)
    return rows


def _parameter_summary(rows: list[dict], model: str, period: str) -> list[dict]:
    period_rows = [row for row in rows if row["model"] == model and row["period"] == period]
    if not period_rows:
        raise ValueError(f"缺少 {model} 模型的 {period} 区间结果")
    summaries = []
    for values in {tuple(row[key] for key in PARAMETER_KEYS) for row in period_rows}:
        group = [
            row for row in period_rows
            if tuple(row[key] for key in PARAMETER_KEYS) == values
        ]
        summaries.append({
            **dict(zip(PARAMETER_KEYS, values)),
            "median_return": float(np.median([row["total_return"] for row in group])),
            "positive_ratio": float(np.mean([row["total_return"] > 0 for row in group])),
            "median_drawdown": float(np.median([row["max_ddpercent"] for row in group])),
            "median_trades": float(np.median([row["trade_count"] for row in group])),
        })
    return sorted(
        summaries,
        key=lambda row: (
            -row["median_return"],
            -row["positive_ratio"],
            -row["median_drawdown"],
            *[row[key] for key in PARAMETER_KEYS],
        ),
    )


def select_model_parameters(rows: list[dict], model: str, shortlist_size: int = 2) -> dict:
    """训练段跨品种中位数取前二，验证段在这两组中选唯一冻结参数。"""
    shortlist = _parameter_summary(rows, model, "train")[:shortlist_size]
    candidates = {tuple(row[key] for key in PARAMETER_KEYS) for row in shortlist}
    validation = _parameter_summary(rows, model, "validation")
    selected = next(
        row for row in validation
        if tuple(row[key] for key in PARAMETER_KEYS) in candidates
    )
    return {key: selected[key] for key in PARAMETER_KEYS}


def _git_state() -> dict:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True
        ).strip()
        return {"head": head, "dirty": bool(status)}
    except subprocess.CalledProcessError:
        return {"head": "unknown", "dirty": True}


def main() -> None:
    from loguru import logger

    logger.remove()
    rows = []
    detail_path = OUTPUT_DIR / f"随机森林方向批量回测明细-{RESULT_DATE}.csv"
    for contract in CONTRACTS:
        rows.extend(run_contract(contract))
        pd.DataFrame(rows).to_csv(detail_path, index=False)

    selected = {
        model: select_model_parameters(rows, model) for model in MODELS
    }
    metadata = {
        "selected": selected,
        "grid": [{k: row[k] for k in PARAMETER_KEYS} for row in MODEL_GRID],
        "fixed": {"label_horizon": 5, "retrain_interval": 21, "max_size": 2},
        "baseline": BASELINE_SETTING,
        "random_forest": "n_estimators=300, max_depth=8, min_samples_leaf=50, "
                         "max_features=sqrt, bootstrap=True, random_state=42",
        "logistic": "C=1.0, class_weight=balanced, max_iter=1000（与策略06一致）",
        "train": "2016-04-01 至 2022-12-31",
        "validation": "2023-01-01 至 2023-12-31",
        "review": "2024-01-01 至 2026-10-30，对本轮两模型均为全新样本外",
        "contracts": [f"{root}9999.{exch}" for root, exch in CONTRACTS],
        "model_runs": len(CONTRACTS) * len(MODELS) * len(MODEL_GRID),
        "baseline_runs": len(CONTRACTS),
        "features": "16个日线量价特征（见研究方案），两模型共用同一管线",
        "label": "未来5个交易日收盘方向",
        "data": "9999主连日线，|9999-8888日收益|>1%判换月并按r9999/r8888比例回溯平滑",
        "slippage_ticks": 1,
        "git": _git_state(),
    }
    (OUTPUT_DIR / f"随机森林方向核心参数-{RESULT_DATE}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    stress_rows = []
    stress_path = OUTPUT_DIR / f"随机森林方向成本压力测试-{RESULT_DATE}.csv"
    frozen_settings = {}
    for model in MODELS:
        selected_setting = next(
            row for row in MODEL_GRID
            if all(row[key] == selected[model][key] for key in PARAMETER_KEYS)
        )
        frozen_settings[model] = selected_setting
    for contract in CONTRACTS:
        warmup_bars, bars = build_bars(contract)
        for model in MODELS:
            stress_rows.extend(_run_setting(
                contract, model, frozen_settings[model], warmup_bars, bars, 2
            ))
        stress_rows.extend(_run_setting(
            contract, "baseline", BASELINE_SETTING, warmup_bars, bars, 2
        ))
        pd.DataFrame(stress_rows).to_csv(stress_path, index=False)
        print(f"双倍滑点完成 {contract[0]}9999", flush=True)
    print(json.dumps({
        "selected": selected,
        "detail": str(detail_path),
        "stress": str(stress_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
