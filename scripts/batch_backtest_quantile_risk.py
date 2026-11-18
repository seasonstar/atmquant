"""分位数尾部风险预测与动态仓位的12品种对照研究。"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401
import vnpy.trader.database as database_module
from config.futures_config import get_futures_info
from core.indicators.calculators.quantile_risk_calculator import (
    CaviarParameters,
    caviar_var_forecast,
    ewma_var_forecast,
    fit_caviar_as,
    historical_var_forecast,
    risk_metrics,
)
from core.strategies.quantile_risk_strategy import QuantileRiskStrategy
from scripts.batch_backtest_logistic_direction import (
    CAPITAL,
    CONTRACTS,
    END_CUTOFF,
    START,
    _load_bars,
    _make_engine,
    add_fixed_fees,
    calculate_period_metrics,
    ensure_backtest_completed,
    get_research_period,
)
from vnpy_ctastrategy import BarGenerator
from vnpy_mysql.mysql_database import close_db_session
from vnpy_mysql.mysql_database import engine as mysql_engine

RESULT_DATE = "2026-11-12"
OUTPUT_DIR = PROJECT_ROOT / "research" / "quantile-risk-data"
MODEL_NAMES = ("fixed", "atr", "historical", "ewma", "caviar")
RISK_MODEL_NAMES = ("historical", "ewma", "caviar")
TAU = 0.05
RISK_WINDOW = 480
ATR_WINDOW = 60
EWMA_LAMBDA = 0.94
BASE_SIZE = 2
MAX_SIZE = 2
TRAIN_END = date(2026, 8, 14)
VALIDATION_END = date(2026, 9, 15)


def _bar_value(bar, key: str) -> float:
    return float(getattr(bar, f"{key}_price"))


def _naive_datetime(bar) -> datetime:
    return bar.datetime.replace(tzinfo=None)


def collect_15min_bars(warmup_bars: list, bars: list) -> list:
    """用与策略相同的 BarGenerator 合成风险模型输入。"""
    collected = []
    generator = BarGenerator(lambda bar: None, 15, collected.append)
    for bar in [*warmup_bars, *bars]:
        generator.update_bar(bar)
    return collected


def close_returns(bars: list) -> np.ndarray:
    """由已完成15分钟收盘计算百分数收益，首个值不可预测。"""
    closes = np.array([_bar_value(bar, "close") for bar in bars], dtype=float)
    returns = np.full(len(bars), np.nan)
    returns[1:] = (closes[1:] / closes[:-1] - 1) * 100
    return returns


def atr_var_forecast(bars: list, window: int = ATR_WINDOW) -> np.ndarray:
    """ATR/收盘价风险序列，当前 K 线只影响下一预测时点。"""
    result = np.full(len(bars), np.nan)
    true_ranges = []
    for index, bar in enumerate(bars):
        high = _bar_value(bar, "high")
        low = _bar_value(bar, "low")
        close = _bar_value(bar, "close")
        true_range = high - low
        if index:
            previous_close = _bar_value(bars[index - 1], "close")
            true_range = max(
                true_range,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        true_ranges.append(true_range)
        if index >= window:
            previous_close = _bar_value(bars[index - 1], "close")
            result[index] = max(
                1e-8,
                float(np.mean(true_ranges[index - window:index])) / previous_close * 100,
            )
    return result


def turnover_metrics(trades: list, contract_size: float, capital: float = CAPITAL) -> dict:
    """实际成交手数与双边累计成交名义金额/初始资金。"""
    volume = float(sum(trade.volume for trade in trades))
    notional = float(sum(
        trade.volume * trade.price * contract_size for trade in trades
    ))
    return {
        "traded_volume": volume,
        "turnover_ratio": notional / capital if capital else np.nan,
    }


def candidate_passes(summary: dict) -> bool:
    """预登记策略门槛：广度、回撤幅度和夏普缺一不可。"""
    return bool(
        summary["drawdown_improved"] >= 8
        and summary["drawdown_relative_reduction"] >= 0.20
        and summary["caviar_sharpe"] >= summary["fixed_sharpe"]
    )


def _period_mask(bars: list, period: str) -> np.ndarray:
    return np.array([
        get_research_period(_naive_datetime(bar).date()) == period for bar in bars
    ])


def _main_period_mask(bars: list, period: str) -> np.ndarray:
    return np.array([
        _naive_datetime(bar) >= START and get_research_period(_naive_datetime(bar).date()) == period
        for bar in bars
    ])


def prepare_contract(contract: tuple[str, str]) -> dict:
    """读取一次数据，冻结 CAViaR 参数和各模型训练参考风险。"""
    warmup_bars, bars = _load_bars(contract)
    bars_15m = collect_15min_bars(warmup_bars, bars)
    returns = close_returns(bars_15m)
    train_mask = np.array([
        START <= _naive_datetime(bar) and _naive_datetime(bar).date() <= TRAIN_END
        for bar in bars_15m
    ]) & np.isfinite(returns)
    train_returns = returns[train_mask]
    caviar_params = fit_caviar_as(train_returns, tau=TAU, n_starts=8)
    forecasts = {
        "historical": historical_var_forecast(returns, RISK_WINDOW, TAU),
        "ewma": ewma_var_forecast(returns, EWMA_LAMBDA, TAU),
        "caviar": caviar_var_forecast(returns, caviar_params),
        "atr": atr_var_forecast(bars_15m, ATR_WINDOW),
    }
    references = {
        model: float(np.nanmedian(values[train_mask]))
        for model, values in forecasts.items()
    }
    return {
        "warmup_bars": warmup_bars,
        "bars": bars,
        "bars_15m": bars_15m,
        "returns": returns,
        "train_mask": train_mask,
        "caviar_params": caviar_params,
        "forecasts": forecasts,
        "references": references,
    }


def build_risk_outputs(contract: tuple[str, str], prepared: dict) -> tuple[list[dict], list[dict]]:
    """生成风险检验汇总与逐时点明细，ATR不冒充5%分位数。"""
    root, vt_symbol = contract
    bars = prepared["bars_15m"]
    returns = prepared["returns"]
    metric_rows = []
    detail_rows = []
    for period in ("train", "validation", "review"):
        mask = _main_period_mask(bars, period)
        for model in RISK_MODEL_NAMES:
            values = prepared["forecasts"][model]
            metrics = risk_metrics(returns[mask], values[mask], TAU)
            metric_rows.append({
                "root": root,
                "vt_symbol": vt_symbol,
                "period": period,
                "model": model,
                "tau": TAU,
                **metrics,
            })
    for index, bar in enumerate(bars):
        bar_datetime = _naive_datetime(bar)
        if bar_datetime < START or not np.isfinite(returns[index]):
            continue
        period = get_research_period(bar_datetime.date())
        for model in RISK_MODEL_NAMES:
            risk = prepared["forecasts"][model][index]
            if not np.isfinite(risk):
                continue
            quantile = -risk
            detail_rows.append({
                "datetime": bar_datetime,
                "vt_symbol": vt_symbol,
                "period": period,
                "model": model,
                "actual_return": returns[index],
                "risk": risk,
                "quantile": quantile,
                "breach": int(returns[index] < quantile),
            })
    return metric_rows, detail_rows


def _strategy_setting(prepared: dict, model: str) -> dict:
    params: CaviarParameters = prepared["caviar_params"]
    return {
        "scan_horizon": 20,
        "deviation_factor": 2.0,
        "structural_sensitivity": 5,
        "quality_threshold": 0.5,
        "risk_model": model,
        "tau": TAU,
        "risk_window": RISK_WINDOW,
        "atr_window": ATR_WINDOW,
        "ewma_lambda": EWMA_LAMBDA,
        "reference_risk": prepared["references"].get(model, 1.0),
        "base_size": BASE_SIZE,
        "max_size": MAX_SIZE,
        "caviar_beta0": params.beta0,
        "caviar_beta1": params.beta1,
        "caviar_beta2": params.beta2,
        "caviar_beta3": params.beta3,
        "caviar_initial_var": params.initial_var,
    }


def run_strategy(
    contract: tuple[str, str],
    prepared: dict,
    model: str,
    slippage_ticks: int,
) -> tuple[list[dict], list[dict]]:
    """运行一个品种、一个仓位模型，并保留信号核对记录。"""
    root, vt_symbol = contract
    info = get_futures_info(root)
    setting = _strategy_setting(prepared, model)
    engine = _make_engine(contract, slippage_ticks)
    messages = []
    engine.output = lambda text: messages.append(str(text))
    engine.load_bar = lambda *args, **kwargs: prepared["warmup_bars"]
    engine.add_strategy(QuantileRiskStrategy, setting)
    actual = engine.strategy.get_parameters()
    for key, value in setting.items():
        if key in actual and actual[key] != value:
            raise RuntimeError(f"{vt_symbol} 参数 {key} 被外部配置覆盖")
    engine.history_data = prepared["bars"]
    engine.run_backtesting()
    ensure_backtest_completed(messages, engine.strategy, prepared["bars"][-1])
    result = engine.calculate_result()
    trades = list(engine.trades.values())
    add_fixed_fees(result, trades, fixed_fee=info["slippage"])

    rows = []
    for period in ("train", "validation", "review"):
        period_result = result[[get_research_period(day) == period for day in result.index]]
        period_trades = [
            trade for trade in trades
            if get_research_period(trade.datetime.replace(tzinfo=None).date()) == period
        ]
        rows.append({
            "root": root,
            "vt_symbol": vt_symbol,
            "model": model,
            "period": period,
            "tau": TAU,
            "reference_risk": setting["reference_risk"],
            "base_size": BASE_SIZE,
            "max_size": MAX_SIZE,
            "slippage_ticks": slippage_ticks,
            "warmup_bars": len(prepared["warmup_bars"]),
            "bars_loaded": len(prepared["bars"]),
            "first_bar": str(prepared["bars"][0].datetime),
            "last_bar": str(prepared["bars"][-1].datetime),
            "entry_signals": sum(event == "entry" for _, event, _ in engine.strategy.signal_log),
            "exit_signals": sum(event == "exit" for _, event, _ in engine.strategy.signal_log),
            "final_position": int(engine.strategy.pos),
            **calculate_period_metrics(period_result),
            **turnover_metrics(period_trades, info["size"]),
        })
    signals = [
        {
            "root": root,
            "vt_symbol": vt_symbol,
            "model": model,
            "slippage_ticks": slippage_ticks,
            "datetime": str(bar_datetime),
            "event": event,
            "direction": direction,
        }
        for bar_datetime, event, direction in engine.strategy.signal_log
    ]
    return rows, signals


def run_contract(
    contract: tuple[str, str], slippage_ticks: int, models: tuple[str, ...] = MODEL_NAMES
) -> dict:
    """单进程处理一个合约，完成后释放数据库连接。"""
    try:
        prepared = prepare_contract(contract)
        strategy_rows = []
        signal_rows = []
        for model in models:
            rows, signals = run_strategy(contract, prepared, model, slippage_ticks)
            strategy_rows.extend(rows)
            signal_rows.extend(signals)
        risk_rows, forecast_rows = build_risk_outputs(contract, prepared)
        params = prepared["caviar_params"]
        metadata = {
            "vt_symbol": contract[1],
            "slippage_ticks": slippage_ticks,
            "train_observations": int(prepared["train_mask"].sum()),
            "bars_15m": len(prepared["bars_15m"]),
            "caviar": {
                "beta0": params.beta0,
                "beta1": params.beta1,
                "beta2": params.beta2,
                "beta3": params.beta3,
                "initial_var": params.initial_var,
            },
            "reference_risk": prepared["references"],
        }
        print(f"完成 {contract[1]}，{len(models)} 个仓位模型", flush=True)
        return {
            "strategy": strategy_rows,
            "signals": signal_rows,
            "risk": risk_rows,
            "forecasts": forecast_rows,
            "metadata": metadata,
        }
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


def _safe_symbol(vt_symbol: str) -> str:
    return vt_symbol.replace(".", "_")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", help="只运行指定 vt_symbol")
    parser.add_argument("--slippage-ticks", type=int, default=1, choices=[1, 2])
    parser.add_argument("--models", default=",".join(MODEL_NAMES))
    args = parser.parse_args()
    models = tuple(args.models.split(","))
    if any(model not in MODEL_NAMES for model in models):
        raise ValueError("models 含未知模型")
    contracts = [row for row in CONTRACTS if not args.contract or row[1] == args.contract]
    if not contracts:
        raise ValueError("未找到指定合约")

    from loguru import logger
    logger.remove()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for contract in contracts:
        output = run_contract(contract, args.slippage_ticks, models)
        stem = f"{_safe_symbol(contract[1])}-slippage{args.slippage_ticks}"
        pd.DataFrame(output["strategy"]).to_csv(OUTPUT_DIR / f"{stem}-strategy.csv", index=False)
        pd.DataFrame(output["signals"]).to_csv(OUTPUT_DIR / f"{stem}-signals.csv", index=False)
        pd.DataFrame(output["risk"]).to_csv(OUTPUT_DIR / f"{stem}-risk.csv", index=False)
        pd.DataFrame(output["forecasts"]).to_csv(OUTPUT_DIR / f"{stem}-forecasts.csv", index=False)
        metadata = {
            **output["metadata"],
            "tau": TAU,
            "risk_window": RISK_WINDOW,
            "atr_window": ATR_WINDOW,
            "ewma_lambda": EWMA_LAMBDA,
            "base_size": BASE_SIZE,
            "max_size": MAX_SIZE,
            "periods": {
                "train": "2026-05-01 至 2026-08-14",
                "validation": "2026-08-15 至 2026-09-15",
                "review": "2026-09-16 至 2026-10-30，二次验证，非全新样本外",
            },
            "git": _git_state(),
        }
        (OUTPUT_DIR / f"{stem}-metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2)
        )


if __name__ == "__main__":
    main()
