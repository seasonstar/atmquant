"""capissimo ML 逻辑回归（TradingView 转换版）批量研究。

8 组预登记参数（lookback × nlbk × filter_type）× 12 品种，
对照组为上一轮自研逻辑回归的冻结参数（480/0.10）。
三段评估、双倍滑点压力测试与选参纪律沿用既有口径。
"""

import json
import subprocess
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401 应用 .env 到 vnpy SETTINGS
import vnpy.trader.database as database_module
from config.futures_config import get_futures_info
from core.strategies.capissimo_logistic_strategy import CapissimoLogisticStrategy
from core.strategies.logistic_direction_strategy import LogisticDirectionStrategy
from scripts.batch_backtest_logistic_direction import (
    CONTRACTS,
    _load_bars,
    _make_engine,
    add_fixed_fees,
    calculate_period_metrics,
    ensure_backtest_completed,
    get_research_period,
)
from vnpy_mysql.mysql_database import close_db_session
from vnpy_mysql.mysql_database import engine as mysql_engine

OUTPUT_DIR = PROJECT_ROOT / "research"
RESULT_DATE = "2026-11-03"

PARAMETER_KEYS = ["lookback", "normalization_lookback", "filter_type"]
CAPISSIMO_GRID = [
    {
        "lookback": lookback,
        "normalization_lookback": nlbk,
        "filter_type": filter_type,
        "learning_rate": 0.0009,
        "iterations": 1000,
        "holding_period": 5,
        "fixed_size": 1,
    }
    for lookback, nlbk, filter_type in product(
        [3, 10], [2, 30], ["None", "Volatility"]
    )
]
HONEST_LR_SETTING = {
    "train_window": 480,
    "prob_threshold": 0.1,
    "label_horizon": 4,
    "retrain_interval": 21,
    "max_size": 2,
}


def _parameter_summary(rows: list[dict], period: str) -> list[dict]:
    period_rows = [
        row for row in rows if row["model"] == "capissimo" and row["period"] == period
    ]
    if not period_rows:
        raise ValueError(f"缺少 capissimo 模型的 {period} 区间结果")
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
            *[str(row[key]) for key in PARAMETER_KEYS],
        ),
    )


def select_capissimo_parameters(rows: list[dict], shortlist_size: int = 2) -> dict:
    shortlist = _parameter_summary(rows, "train")[:shortlist_size]
    candidates = {tuple(row[key] for key in PARAMETER_KEYS) for row in shortlist}
    validation = _parameter_summary(rows, "validation")
    selected = next(
        row for row in validation
        if tuple(row[key] for key in PARAMETER_KEYS) in candidates
    )
    return {key: selected[key] for key in PARAMETER_KEYS}


def _run_setting(
    contract: tuple[str, str],
    model: str,
    setting: dict,
    warmup_bars: list,
    bars: list,
    slippage_ticks: int,
) -> list[dict]:
    root, vt_symbol = contract
    info = get_futures_info(root)
    engine = _make_engine(contract, slippage_ticks)
    messages = []
    engine.output = lambda text: messages.append(str(text))
    engine.load_bar = lambda *args, **kwargs: warmup_bars
    strategy_class = (
        CapissimoLogisticStrategy if model == "capissimo" else LogisticDirectionStrategy
    )
    engine.add_strategy(strategy_class, dict(setting))
    actual = engine.strategy.get_parameters()
    for key, value in setting.items():
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
        metrics = calculate_period_metrics(period_df)
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
    capissimo_grid: list[dict] | None = None,
    include_honest_lr: bool = True,
) -> list[dict]:
    _, vt_symbol = contract
    grid = capissimo_grid or CAPISSIMO_GRID
    try:
        warmup_bars, bars = _load_bars(contract)
        rows = []
        for setting in grid:
            rows.extend(_run_setting(
                contract, "capissimo", setting, warmup_bars, bars, slippage_ticks
            ))
        if include_honest_lr:
            rows.extend(_run_setting(
                contract, "honest_lr", HONEST_LR_SETTING, warmup_bars, bars, slippage_ticks
            ))
        print(f"完成 {vt_symbol}，{len(rows) // 3} 组回测，{len(bars)} 根K线", flush=True)
        return rows
    finally:
        close_db_session()
        mysql_engine.dispose()
        database_module.database = None


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
    detail_path = OUTPUT_DIR / f"capissimo逻辑回归批量回测明细-{RESULT_DATE}.csv"
    for contract in CONTRACTS:
        rows.extend(run_contract(contract))
        pd.DataFrame(rows).to_csv(detail_path, index=False)

    selected = select_capissimo_parameters(rows)
    metadata = {
        "selected": selected,
        "grid": [{k: row[k] for k in PARAMETER_KEYS} for row in CAPISSIMO_GRID],
        "fixed": {
            "learning_rate": 0.0009,
            "iterations": 1000,
            "holding_period": 5,
            "easteregg": True,
            "use_price": True,
            "fixed_size": 1,
        },
        "honest_lr": HONEST_LR_SETTING,
        "train": "2026-05-01 至 2026-08-14",
        "validation": "2026-08-15 至 2026-09-15",
        "review": "2026-09-16 至 2026-10-30",
        "contracts": [vt_symbol for _, vt_symbol in CONTRACTS],
        "capissimo_runs": len(CONTRACTS) * len(CAPISSIMO_GRID),
        "source": "https://www.tradingview.com/script/49YIV1jW-Machine-Learning-Logistic-Regression/",
        "license": "MPL-2.0",
        "slippage_ticks": 1,
        "git": _git_state(),
    }
    (OUTPUT_DIR / f"capissimo逻辑回归核心参数-{RESULT_DATE}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )

    stress_rows = []
    stress_path = OUTPUT_DIR / f"capissimo逻辑回归成本压力测试-{RESULT_DATE}.csv"
    selected_setting = next(
        row for row in CAPISSIMO_GRID
        if all(row[key] == selected[key] for key in PARAMETER_KEYS)
    )
    for contract in CONTRACTS:
        stress_rows.extend(run_contract(contract, 2, [selected_setting]))
        pd.DataFrame(stress_rows).to_csv(stress_path, index=False)
    print(json.dumps({
        "selected": selected,
        "detail": str(detail_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
