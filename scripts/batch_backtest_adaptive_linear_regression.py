"""自适应线性回归结构与固定窗口OLS的批量对照研究。"""

import json
import subprocess
import sys
from datetime import date, timedelta
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import vnpy.trader.database as database_module
from config.futures_config import get_futures_info
from core.strategies.adaptive_linear_regression_strategy import (
    AdaptiveLinearRegressionStrategy,
)
from core.strategies.ols_channel_strategy import OlsChannelStrategy
from scripts.batch_backtest_ols_channel import (
    CAPITAL,
    CONTRACTS,
    START,
    _make_engine,
    add_fixed_fees,
)
from vnpy_mysql.mysql_database import close_db_session
from vnpy_mysql.mysql_database import engine as mysql_engine

OUTPUT_DIR = PROJECT_ROOT / "research"
RESULT_DATE = "2026-11-03"
PARAMETER_KEYS = [
    "scan_horizon",
    "deviation_factor",
    "structural_sensitivity",
    "quality_threshold",
]
ADAPTIVE_GRID = [
    {
        "scan_horizon": horizon,
        "deviation_factor": deviation,
        "structural_sensitivity": sensitivity,
        "quality_threshold": quality,
    }
    for horizon, deviation, sensitivity, quality in product(
        [10, 20, 40], [1.5, 2.0], [3, 5, 10], [0.25, 0.5]
    )
]
BASELINE_SETTING = {
    "window": 60,
    "entry_dev": 2.0,
    "r2_threshold": 0.1,
    "risk_per_trade": 0.0,
    "initial_capital": CAPITAL,
}


def get_research_period(day: date) -> str:
    if day <= date(2026, 8, 14):
        return "train"
    if day <= date(2026, 9, 15):
        return "validation"
    return "review"


def calculate_period_metrics(df, capital: float = CAPITAL) -> dict:
    empty = {
        "total_net_pnl": 0.0,
        "gross_pnl": 0.0,
        "total_return": 0.0,
        "max_ddpercent": 0.0,
        "sharpe_ratio": 0.0,
        "commission": 0.0,
        "slippage": 0.0,
        "trade_count": 0,
        "days": 0,
    }
    if df.empty:
        return empty

    balance = capital + df["net_pnl"].cumsum()
    pre_balance = balance.shift(1)
    pre_balance.iloc[0] = capital
    returns = np.log(balance / pre_balance).fillna(0)
    highwater = balance.cummax().clip(lower=capital)
    drawdown = (balance - highwater) / highwater * 100
    return_std = returns.std()
    sharpe = 0.0
    if return_std > 0:
        sharpe = returns.mean() / return_std * np.sqrt(240)

    total_net_pnl = float(df["net_pnl"].sum())
    commission = float(df["commission"].sum())
    slippage = float(df["slippage"].sum())
    return {
        "total_net_pnl": total_net_pnl,
        "gross_pnl": total_net_pnl + commission + slippage,
        "total_return": (balance.iloc[-1] / capital - 1) * 100,
        "max_ddpercent": float(drawdown.min()),
        "sharpe_ratio": float(sharpe),
        "commission": commission,
        "slippage": slippage,
        "trade_count": int(df["trade_count"].sum()),
        "days": len(df),
    }


def _parameter_summary(rows: list[dict], period: str) -> list[dict]:
    period_rows = [
        row for row in rows if row["model"] == "adaptive" and row["period"] == period
    ]
    if not period_rows:
        raise ValueError(f"缺少自适应模型的 {period} 区间结果")

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


def select_adaptive_parameters(rows: list[dict], shortlist_size: int = 5) -> dict:
    shortlist = _parameter_summary(rows, "train")[:shortlist_size]
    candidates = {tuple(row[key] for key in PARAMETER_KEYS) for row in shortlist}
    validation = _parameter_summary(rows, "validation")
    selected = next(
        row for row in validation
        if tuple(row[key] for key in PARAMETER_KEYS) in candidates
    )
    return {key: selected[key] for key in PARAMETER_KEYS}


def ensure_backtest_completed(messages: list[str], strategy, final_bar) -> None:
    if any("触发异常" in message for message in messages):
        detail = "\n".join(messages)
        raise RuntimeError(f"回测异常，结果作废\n{detail}")
    consumed = getattr(strategy, "last_bar_datetime", None)
    if (
        consumed is not None
        and consumed.replace(tzinfo=None) != final_bar.datetime.replace(tzinfo=None)
    ):
        raise RuntimeError("策略未消费到最后一根K线")


def _load_bars(contract: tuple[str, str], slippage_ticks: int):
    loader = _make_engine(contract, slippage_ticks)
    loader.start = START - timedelta(days=45)
    loader.load_data()
    warmup_bars = [
        bar for bar in loader.history_data
        if bar.datetime.replace(tzinfo=None) < START
    ]
    bars = [
        bar for bar in loader.history_data
        if bar.datetime.replace(tzinfo=None) >= START
    ]
    vt_symbol = contract[1]
    if len(bars) < 1000 or not warmup_bars:
        raise RuntimeError(f"{vt_symbol} 主数据或预热数据不完整")
    if bars[-1].datetime.date() < date(2026, 10, 30):
        raise RuntimeError(f"{vt_symbol} 不是截至最新交易日的主力数据")
    return warmup_bars, bars


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
    strategy_class = AdaptiveLinearRegressionStrategy if model == "adaptive" else OlsChannelStrategy
    strategy_setting = dict(setting)
    if model == "baseline":
        strategy_setting.update({
            "fixed_fee_per_lot": info["slippage"],
            "deposit_rate": info["deposit_rate"],
        })
    engine.add_strategy(strategy_class, strategy_setting)
    actual = engine.strategy.get_parameters()
    for key, value in strategy_setting.items():
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
    adaptive_grid: list[dict] | None = None,
    include_baseline: bool = True,
) -> list[dict]:
    _, vt_symbol = contract
    grid = adaptive_grid or ADAPTIVE_GRID
    try:
        warmup_bars, bars = _load_bars(contract, slippage_ticks)
        rows = []
        for setting in grid:
            rows.extend(_run_setting(
                contract, "adaptive", setting, warmup_bars, bars, slippage_ticks
            ))
        if include_baseline:
            rows.extend(_run_setting(
                contract, "baseline", BASELINE_SETTING, warmup_bars, bars, slippage_ticks
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
    detail_path = OUTPUT_DIR / f"自适应回归结构批量回测明细-{RESULT_DATE}.csv"
    for contract in CONTRACTS:
        rows.extend(run_contract(contract))
        pd.DataFrame(rows).to_csv(detail_path, index=False)

    selected = select_adaptive_parameters(rows)
    metadata = {
        "selected": selected,
        "baseline": BASELINE_SETTING,
        "train": "2026-05-01 至 2026-08-14",
        "validation": "2026-08-15 至 2026-09-15",
        "review": "2026-09-16 至 2026-10-30，非全新样本外",
        "contracts": [vt_symbol for _, vt_symbol in CONTRACTS],
        "adaptive_runs": len(CONTRACTS) * len(ADAPTIVE_GRID),
        "baseline_runs": len(CONTRACTS),
        "slippage_ticks": 1,
        "git": _git_state(),
    }
    (OUTPUT_DIR / f"自适应回归结构核心参数-{RESULT_DATE}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )

    stress_rows = []
    stress_path = OUTPUT_DIR / f"自适应回归结构成本压力测试-{RESULT_DATE}.csv"
    for contract in CONTRACTS:
        stress_rows.extend(run_contract(contract, 2, [selected]))
        pd.DataFrame(stress_rows).to_csv(stress_path, index=False)
    print(json.dumps({"selected": selected, "detail": str(detail_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
