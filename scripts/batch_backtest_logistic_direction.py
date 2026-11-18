"""逻辑回归方向概率策略与朴素动量基线的批量研究。

自包含版本：不依赖已删除的 batch_backtest_ols_channel 公共模块。
12 个真实主力合约、1 分钟K线撮合、15 分钟信号、训练/验证/复检三段评估，
参数只在训练与验证段选择，复检段不参与排名，另做双倍滑点压力测试。
"""

import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401 应用 .env 到 vnpy SETTINGS
import vnpy.trader.database as database_module
from config.futures_config import get_futures_info
from core.strategies.logistic_direction_strategy import LogisticDirectionStrategy
from core.strategies.momentum_baseline_strategy import MomentumBaselineStrategy
from vnpy.trader.constant import Interval
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy_mysql.mysql_database import close_db_session
from vnpy_mysql.mysql_database import engine as mysql_engine

OUTPUT_DIR = PROJECT_ROOT / "research"
RESULT_DATE = "2026-11-03"

CAPITAL = 200_000
START = datetime(2026, 5, 1)
END_CUTOFF = datetime(2026, 10, 31, 2, 30)
WARMUP_START = START - timedelta(days=45)

CONTRACTS = [
    ("rb", "rb2701.SHFE"),
    ("hc", "hc2701.SHFE"),
    ("i", "i2701.DCE"),
    ("j", "j2701.DCE"),
    ("jm", "jm2701.DCE"),
    ("MA", "MA701.CZCE"),
    ("TA", "TA701.CZCE"),
    ("SR", "SR701.CZCE"),
    ("m", "m2701.DCE"),
    ("FG", "FG701.CZCE"),
    ("SA", "SA701.CZCE"),
    ("RM", "RM701.CZCE"),
]

PARAMETER_KEYS = ["train_window", "prob_threshold"]
LOGISTIC_GRID = [
    {
        "train_window": train_window,
        "prob_threshold": prob_threshold,
        "label_horizon": 4,
        "retrain_interval": 21,
        "max_size": 2,
    }
    for train_window, prob_threshold in product([240, 480], [0.05, 0.10])
]
BASELINE_SETTING = {
    "momentum_window": 21,
    "fixed_size": 1,
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
    sharpe = returns.mean() / return_std * np.sqrt(240) if return_std > 0 else 0.0
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
        row for row in rows if row["model"] == "logistic" and row["period"] == period
    ]
    if not period_rows:
        raise ValueError(f"缺少逻辑回归模型的 {period} 区间结果")
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


def select_logistic_parameters(rows: list[dict], shortlist_size: int = 2) -> dict:
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
        raise RuntimeError("回测异常，结果作废\n" + "\n".join(messages))
    consumed = getattr(strategy, "last_bar_datetime", None)
    if (
        consumed is not None
        and consumed.replace(tzinfo=None) != final_bar.datetime.replace(tzinfo=None)
    ):
        raise RuntimeError("策略未消费到最后一根K线")


def _make_engine(contract: tuple[str, str], slippage_ticks: int) -> BacktestingEngine:
    root, vt_symbol = contract
    info = get_futures_info(root)
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.MINUTE,
        start=START,
        end=END_CUTOFF,
        rate=info["rate"],
        slippage=info["pricetick"] * slippage_ticks,
        size=info["size"],
        pricetick=info["pricetick"],
        capital=CAPITAL,
    )
    return engine


def add_fixed_fees(df, trades: list, fixed_fee: float) -> None:
    """把每手固定手续费按成交日并入 commission 并扣减 net_pnl。

    配置中的 slippage 字段按约定为每手固定手续费（元/手），
    比例手续费已由引擎按 rate 计入，这里只补固定部分。
    """
    if fixed_fee <= 0:
        return
    added: dict[date, float] = {}
    for trade in trades:
        day = trade.datetime.replace(tzinfo=None).date()
        added[day] = added.get(day, 0.0) + trade.volume * fixed_fee
    for day, fee in added.items():
        if day in df.index:
            df.loc[day, "commission"] += fee
            df.loc[day, "net_pnl"] -= fee


def _load_bars(contract: tuple[str, str]) -> tuple[list, list]:
    loader = _make_engine(contract, 1)
    loader.start = WARMUP_START
    loader.end = END_CUTOFF
    loader.load_data()
    warmup_bars = [
        bar for bar in loader.history_data
        if bar.datetime.replace(tzinfo=None) < START
    ]
    bars = [
        bar for bar in loader.history_data
        if START <= bar.datetime.replace(tzinfo=None) <= END_CUTOFF
    ]
    vt_symbol = contract[1]
    if len(bars) < 30000 or not warmup_bars:
        raise RuntimeError(f"{vt_symbol} 主数据或预热数据不完整")
    if bars[-1].datetime.replace(tzinfo=None).date() < date(2026, 10, 30):
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
    strategy_class = (
        LogisticDirectionStrategy if model == "logistic" else MomentumBaselineStrategy
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
    logistic_grid: list[dict] | None = None,
    include_baseline: bool = True,
) -> list[dict]:
    _, vt_symbol = contract
    grid = logistic_grid or LOGISTIC_GRID
    try:
        warmup_bars, bars = _load_bars(contract)
        rows = []
        for setting in grid:
            rows.extend(_run_setting(
                contract, "logistic", setting, warmup_bars, bars, slippage_ticks
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
    detail_path = OUTPUT_DIR / f"逻辑回归方向批量回测明细-{RESULT_DATE}.csv"
    for contract in CONTRACTS:
        rows.extend(run_contract(contract))
        pd.DataFrame(rows).to_csv(detail_path, index=False)

    selected = select_logistic_parameters(rows)
    metadata = {
        "selected": selected,
        "grid": [{k: row[k] for k in PARAMETER_KEYS} for row in LOGISTIC_GRID],
        "fixed": {"label_horizon": 4, "retrain_interval": 21, "max_size": 2},
        "baseline": BASELINE_SETTING,
        "train": "2026-05-01 至 2026-08-14",
        "validation": "2026-08-15 至 2026-09-15",
        "review": "2026-09-16 至 2026-10-30，对逻辑回归为全新样本外",
        "contracts": [vt_symbol for _, vt_symbol in CONTRACTS],
        "logistic_runs": len(CONTRACTS) * len(LOGISTIC_GRID),
        "baseline_runs": len(CONTRACTS),
        "features": "ret1/ret4/ret16/ret64/vol16/vol64/range_pos/volume_z/amplitude",
        "label": "未来4根15分钟K线收盘方向",
        "slippage_ticks": 1,
        "git": _git_state(),
    }
    (OUTPUT_DIR / f"逻辑回归方向核心参数-{RESULT_DATE}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )

    stress_rows = []
    stress_path = OUTPUT_DIR / f"逻辑回归方向成本压力测试-{RESULT_DATE}.csv"
    selected_setting = next(
        row for row in LOGISTIC_GRID
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
