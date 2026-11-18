"""全期货品种 Bayesian BBSMA/nQQE 六模型双成本批量回测。

数据、配置和区间覆盖不合格的品种均进入失败清单；1m 数据每合约每次
成本运行只加载一次，六模型共用相同数据但使用独立真实回测引擎。
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import traceback
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.futures_config import FUTURES_INFO
from core.indicators.calculators.bayesian_q_calculator import MODEL_NAMES
from core.strategies.bayesian_q_strategy import BayesianQStrategy
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.database import BarOverview
from vnpy.trader.object import BarData
from vnpy_ctastrategy.backtesting import BacktestingEngine

OUTPUT_DIR = PROJECT_ROOT / "research" / "bayesian-q-data"
CAPITAL = 200_000
START = datetime(2026, 5, 1)
MAIN_END = datetime(2026, 10, 30)
MAIN_FIRST_TRADING_DATE = date(2026, 5, 6)
END_CUTOFF = datetime(2026, 10, 31, 2, 30)
WARMUP_START = START - timedelta(days=45)
PERIODS = ("train", "validation", "review")
# 最长 BBSMA 预热需要 40 根已完成小时 K 线；1m 数量不得再用夜盘
# 品种的 30000 根门槛误伤日盘/CFFEX。首末交易时段仍另行精确校验。
MIN_MAIN_BARS = 40 * 60
CONTINUOUS_SUFFIXES = {"8888", "9999"}

# 预期收盘来源：各交易所公开交易时段规则的 2026 研究快照，并用真实
# 2026-10-30/31 数据逐 root 交叉核对。1m bar 使用时间戳作为分钟起点，
# 因而官方 23:00/01:00/02:30 收盘分别对应 22:59/00:59/02:29。
# 仓库 config.trading_sessions_config 的通用 CN_FUTURES_SESSION 到 02:29、
# CN_CFFEX_SESSION 到 14:59，不能描述品种差异，故这里显式冻结完整映射。
# END_CUTOFF 只是研究数据集截取边界，不是所有市场的官方统一收盘。
DAY_ONLY_ROOTS = frozenset({
    "ap", "cj", "pk", "sf", "sm", "ur",  # CZCE 日盘品种
    "jd", "lg", "lh",                    # DCE 日盘品种
    "ec",                                # INE 集运指数（欧线）
})
ONE_AM_CLOSE_ROOTS = frozenset({
    "cu", "al", "zn", "pb", "ni", "sn", "ss", "ao", "ad", "bc",
})
TWO_THIRTY_CLOSE_ROOTS = frozenset({"au", "ag", "sc"})
CFFEX_BOND_ROOTS = frozenset({"t", "tf", "ts", "tl"})
SESSION_EXCHANGES = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "GFEX", "INE"})
SESSION_CLOSE_SOURCE = (
    "SHFE/DCE/CZCE/CFFEX/GFEX/INE 公开交易时段规则（2026 研究快照）；"
    "逐 root 真实 2026-10-30/31 1m 数据交叉核对；分钟起始时间戳=官方收盘减 1 分钟"
)

INVENTORY_FIELDS = [
    "root",
    "vt_symbol",
    "exchange",
    "count",
    "start",
    "end",
    "size",
    "pricetick",
    "rate",
    "fixed_fee",
]
FAILURE_FIELDS = [
    "root",
    "vt_symbol",
    "exchange",
    "count",
    "start",
    "end",
    "slippage_ticks",
    "reason",
    "detail",
    "exception_type",
    "traceback",
]
DETAIL_FIELDS = [
    "root",
    "vt_symbol",
    "model",
    "period",
    "slippage_ticks",
    "fixed_size",
    "size",
    "pricetick",
    "rate",
    "fixed_fee",
    "price_slippage",
    "warmup_bars",
    "bars_loaded",
    "first_bar",
    "last_bar",
    "expected_first_bar",
    "expected_final_bar",
    "first_signal",
    "final_position",
    "audit_records",
    "executed_trades",
    "traded_volume",
    "last_trade_datetime",
    "next_minute_fill_verified",
    "fill_audit_status",
    "invalid_fill_count",
    "total_net_pnl",
    "gross_pnl",
    "total_return",
    "max_ddpercent",
    "sharpe_ratio",
    "solvency_ok",
    "solvency_status",
    "nonpositive_balance_days",
    "nonpositive_pre_balance_days",
    "invalid_log_return_days",
    "min_balance",
    "min_pre_balance",
    "commission",
    "slippage",
    "trade_count",
    "days",
]
SIGNAL_FIELDS = [
    "root",
    "vt_symbol",
    "slippage_ticks",
    "datetime",
    "model",
    "signal",
    "target_pos",
    "pos",
    "close_price",
    "model_ready",
    "sma",
    "basis",
    "upper",
    "sigma_up_legacy",
    "sigma_down_legacy",
    "prime_legacy",
    "sigma_up_fixed",
    "sigma_down_fixed",
    "prime_fixed",
    "bayes_ready",
    "rsi",
    "qqef",
    "qqes",
    "nqqe_ready",
    "nqqe_trend",
    *MODEL_NAMES,
]
TRADE_FIELDS = [
    "root",
    "vt_symbol",
    "model",
    "slippage_ticks",
    "tradeid",
    "orderid",
    "datetime",
    "signal_datetime",
    "next_minute_fill",
    "direction",
    "offset",
    "price",
    "volume",
]


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _iso(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _exchange_value(exchange: Any) -> str:
    if exchange is None:
        return ""
    return str(getattr(exchange, "value", exchange))


def _root_from_symbol(symbol: str) -> str:
    match = re.match(r"^([A-Za-z]+)", str(symbol))
    return match.group(1) if match else ""


def _is_real_contract(overview: BarOverview, exchange: Exchange | None) -> bool:
    """仅字母加真实年月数字的合约可交易，8888/9999 主连明确排除。"""

    match = re.fullmatch(r"^([A-Za-z]+)([0-9]+)$", str(overview.symbol))
    if not match or match.group(2) in CONTINUOUS_SUFFIXES:
        return False
    digits = match.group(2)
    if exchange == Exchange.CZCE:
        return len(digits) == 3
    if exchange is not None:
        return len(digits) == 4
    return len(digits) in (3, 4)


def _vt_symbol(overview: BarOverview, config_info: Mapping[str, Any] | None = None) -> str:
    exchange = overview.exchange
    if exchange is None and config_info:
        exchange = config_info.get("exchange")
    suffix = _exchange_value(exchange)
    return f"{overview.symbol}.{suffix}" if suffix else str(overview.symbol)


def _overview_sort_key(overview: BarOverview) -> tuple[datetime, int, str]:
    end = _naive(overview.end) if isinstance(overview.end, datetime) else datetime.min
    return end, int(overview.count or 0), str(overview.symbol)


def _failure(
    root: str,
    reason: str,
    overview: BarOverview | None = None,
    *,
    config_info: Mapping[str, Any] | None = None,
    detail: str = "",
) -> dict:
    return {
        "root": root,
        "vt_symbol": _vt_symbol(overview, config_info) if overview else "",
        "exchange": _exchange_value(overview.exchange) if overview else "",
        "count": int(overview.count or 0) if overview else 0,
        "start": _iso(overview.start) if overview else "",
        "end": _iso(overview.end) if overview else "",
        "reason": reason,
        "detail": detail,
    }


def _fixed_fee(info: Mapping[str, Any]) -> tuple[Any, str | None]:
    if "slippage" in info:
        return info["slippage"], None
    if "fixed_fee" in info:
        return info["fixed_fee"], None
    return None, "missing_fixed_fee"


def _config_errors(info: Mapping[str, Any]) -> list[str]:
    errors = []
    for field in ("size", "pricetick", "rate"):
        if field not in info or info[field] is None:
            errors.append(f"missing_{field}")
            continue
        try:
            value = float(info[field])
        except (TypeError, ValueError):
            errors.append(f"invalid_{field}")
            continue
        minimum_ok = value > 0 if field in ("size", "pricetick") else value >= 0
        if not math.isfinite(value) or not minimum_ok:
            errors.append(f"invalid_{field}")

    fixed_fee, missing = _fixed_fee(info)
    if missing:
        errors.append(missing)
    else:
        try:
            value = float(fixed_fee)
            if not math.isfinite(value) or value < 0:
                errors.append("invalid_fixed_fee")
        except (TypeError, ValueError):
            errors.append("invalid_fixed_fee")
    return errors


def _covers_main_period(overview: BarOverview) -> bool:
    if not isinstance(overview.start, datetime) or not isinstance(overview.end, datetime):
        return False
    return bool(
        (overview.count or 0) > 0
        and _naive(overview.start) <= START
        and _naive(overview.end).date() >= MAIN_END.date()
    )


def discover_futures_universe(
    overviews: Sequence[BarOverview],
    config: Mapping[str, Mapping[str, Any]] = FUTURES_INFO,
) -> tuple[list[dict], list[dict]]:
    """配置 root 与真实 1m DB root 求并集，每 root 最多选择一个真实合约。"""

    config_by_key: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for root, info in config.items():
        key = str(root).casefold()
        if key in config_by_key:
            raise ValueError(f"配置 root 大小写归一后重复: {root}")
        config_by_key[key] = (str(root), info)

    db_groups: dict[str, list[BarOverview]] = {}
    db_roots: dict[str, str] = {}
    for overview in overviews:
        if overview.interval != Interval.MINUTE:
            continue
        root = _root_from_symbol(overview.symbol)
        if not root:
            continue
        key = root.casefold()
        db_groups.setdefault(key, []).append(overview)
        db_roots.setdefault(key, root)

    selected = []
    failures = []
    for key in sorted(set(config_by_key) | set(db_groups)):
        rows = db_groups.get(key, [])
        config_entry = config_by_key.get(key)
        config_info = config_entry[1] if config_entry else None
        root = config_entry[0] if config_entry else db_roots[key]
        exchange = rows[0].exchange if rows else (
            config_info.get("exchange") if config_info else None
        )
        real_rows = [row for row in rows if _is_real_contract(row, exchange)]
        representative_rows = real_rows or rows
        representative = (
            max(representative_rows, key=_overview_sort_key)
            if representative_rows else None
        )

        reasons: list[str] = []
        details: list[str] = []
        if not config_entry:
            reasons.append("missing_config")
            details.append("missing_config: 数据库存在 1m root，但 FUTURES_INFO 无对应配置")
        else:
            for reason in _config_errors(config_info):
                reasons.append(reason)
                details.append(f"{reason}: 缺少或无效的合约/成本配置，禁止回测")

        chosen = None
        if not real_rows:
            reason = "no_real_contract" if rows else "missing_db_data"
            reasons.append(reason)
            details.append(
                f"{reason}: "
                + ("连续 8888/9999 不能替代真实合约" if rows else "配置 root 无 1m 数据")
            )
        else:
            covering = [row for row in real_rows if _covers_main_period(row)]
            if not covering:
                reasons.append("incomplete_coverage")
                details.append(
                    f"incomplete_coverage: 真实合约未完整覆盖 {START.date()} 至 {MAIN_END.date()}"
                )
            else:
                chosen = max(covering, key=_overview_sort_key)

        if reasons:
            failures.append(_failure(
                root,
                ";".join(reasons),
                chosen or representative,
                config_info=config_info,
                detail="; ".join(details),
            ))
            continue

        fixed_fee, _ = _fixed_fee(config_info)
        selected.append({
            "root": root,
            "vt_symbol": _vt_symbol(chosen, config_info),
            "exchange": _exchange_value(chosen.exchange or config_info.get("exchange")),
            "count": int(chosen.count),
            "start": _iso(chosen.start),
            "end": _iso(chosen.end),
            "size": float(config_info["size"]),
            "pricetick": float(config_info["pricetick"]),
            "rate": float(config_info["rate"]),
            "fixed_fee": float(fixed_fee),
        })

    return selected, failures


def _resolve_contract(contract: Mapping[str, Any] | tuple[str, str]) -> dict:
    if isinstance(contract, Mapping):
        resolved = dict(contract)
        info = dict(contract)
    else:
        root, vt_symbol = contract
        config_entry = next(
            (info for key, info in FUTURES_INFO.items() if key.casefold() == root.casefold()),
            None,
        )
        if config_entry is None:
            raise ValueError(f"{root} 缺少配置")
        resolved = {"root": root, "vt_symbol": vt_symbol}
        info = dict(config_entry)

    resolved.setdefault("exchange", _exchange_value(info.get("exchange")))
    errors = _config_errors(info)
    if errors:
        raise ValueError(f"{resolved.get('vt_symbol', '')} 配置失败: {', '.join(errors)}")
    fixed_fee, _ = _fixed_fee(info)
    for field in ("size", "pricetick", "rate"):
        resolved[field] = float(info[field])
    resolved["fixed_fee"] = float(fixed_fee)
    if not resolved.get("root") or not resolved.get("vt_symbol"):
        raise ValueError("合约必须包含 root 和 vt_symbol")
    return resolved


def get_research_period(day: date) -> str:
    if day <= date(2026, 8, 14):
        return "train"
    if day <= date(2026, 9, 15):
        return "validation"
    return "review"


def calculate_period_metrics(df: pd.DataFrame, capital: float = CAPITAL) -> dict:
    """沿用冻结研究协议的逐段资金曲线指标。"""

    empty = {
        "total_net_pnl": 0.0,
        "gross_pnl": 0.0,
        "total_return": 0.0,
        "max_ddpercent": 0.0,
        "sharpe_ratio": 0.0,
        "solvency_ok": True,
        "solvency_status": "no_data",
        "nonpositive_balance_days": 0,
        "nonpositive_pre_balance_days": 0,
        "invalid_log_return_days": 0,
        "min_balance": np.nan,
        "min_pre_balance": np.nan,
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
    # 非正权益/期初权益没有金融意义上的对数收益。不得把无效值填零；
    # 该分段 Sharpe 明确定义为 NaN，同时保留实际 pnl/return/drawdown。
    valid_log_return = (balance > 0) & (pre_balance > 0)
    solvency_ok = bool(valid_log_return.all())
    returns = pd.Series(np.nan, index=df.index, dtype=float)
    if valid_log_return.any():
        returns.loc[valid_log_return] = np.log(
            balance.loc[valid_log_return] / pre_balance.loc[valid_log_return]
        )
    highwater = balance.cummax().clip(lower=capital)
    drawdown = (balance - highwater) / highwater * 100
    if solvency_ok:
        return_std = returns.std()
        sharpe = returns.mean() / return_std * np.sqrt(240) if return_std > 0 else 0.0
    else:
        sharpe = np.nan
    total_net_pnl = float(df["net_pnl"].sum())
    commission = float(df["commission"].sum())
    slippage = float(df["slippage"].sum())
    return {
        "total_net_pnl": total_net_pnl,
        "gross_pnl": total_net_pnl + commission + slippage,
        "total_return": (balance.iloc[-1] / capital - 1) * 100,
        "max_ddpercent": float(drawdown.min()),
        "sharpe_ratio": float(sharpe),
        "solvency_ok": solvency_ok,
        "solvency_status": "solvent" if solvency_ok else "insolvent",
        "nonpositive_balance_days": int((balance <= 0).sum()),
        "nonpositive_pre_balance_days": int((pre_balance <= 0).sum()),
        "invalid_log_return_days": int((~valid_log_return).sum()),
        "min_balance": float(balance.min()),
        "min_pre_balance": float(pre_balance.min()),
        "commission": commission,
        "slippage": slippage,
        "trade_count": int(df["trade_count"].sum()),
        "days": len(df),
    }


def add_fixed_fees(df: pd.DataFrame, trades: list, fixed_fee: float) -> None:
    """每成交手补收 legacy slippage 固定费，不乘合约乘数；零费用有效。"""

    if fixed_fee < 0 or not math.isfinite(fixed_fee):
        raise ValueError("固定手续费必须是非负有限数")
    if fixed_fee == 0:
        return
    added: dict[date, float] = {}
    for trade in trades:
        day = _naive(trade.datetime).date()
        added[day] = added.get(day, 0.0) + trade.volume * fixed_fee
    for day, fee in added.items():
        if day not in df.index:
            raise RuntimeError(f"成交日 {day} 缺少逐日结果，固定费用不能落账")
        df.loc[day, "commission"] += fee
        df.loc[day, "net_pnl"] -= fee


def ensure_backtest_completed(messages: list[str], strategy: Any, final_bar: Any) -> None:
    if any("触发异常" in message for message in messages):
        raise RuntimeError("回测异常，结果作废\n" + "\n".join(messages))
    consumed = getattr(strategy, "last_bar_datetime", None)
    if consumed is None:
        raise RuntimeError("策略没有 last_bar_datetime，不能证明消费最终 K 线")
    if _naive(consumed) != _naive(final_bar.datetime):
        raise RuntimeError("策略未消费到最后一根K线")


def _make_engine(
    contract: Mapping[str, Any] | tuple[str, str],
    slippage_ticks: int,
) -> BacktestingEngine:
    if slippage_ticks not in (1, 2):
        raise ValueError("slippage_ticks 只允许 1 或 2")
    resolved = _resolve_contract(contract)
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=resolved["vt_symbol"],
        interval=Interval.MINUTE,
        start=START,
        end=END_CUTOFF,
        rate=resolved["rate"],
        slippage=resolved["pricetick"] * slippage_ticks,
        size=resolved["size"],
        pricetick=resolved["pricetick"],
        capital=CAPITAL,
    )
    return engine


def _expected_session_bounds(contract: Mapping[str, Any]) -> tuple[datetime, datetime]:
    """返回主区间首个和最终交易时段应有的一分钟 bar 时间戳。"""

    root = str(contract["root"]).casefold()
    exchange = str(
        contract.get("exchange")
        or str(contract["vt_symbol"]).rsplit(".", 1)[-1]
    ).upper()
    if exchange not in SESSION_EXCHANGES:
        raise ValueError(f"{contract.get('vt_symbol', '')} 无显式交易时段配置: {exchange}")

    first_time = time(9, 30) if exchange == "CFFEX" else time(9, 0)
    expected_first = datetime.combine(MAIN_FIRST_TRADING_DATE, first_time)

    final_day = MAIN_END.date()
    if exchange == "CFFEX":
        close = time(15, 14) if root in CFFEX_BOND_ROOTS else time(14, 59)
    elif exchange == "GFEX" or root in DAY_ONLY_ROOTS:
        close = time(14, 59)
    elif root in TWO_THIRTY_CLOSE_ROOTS:
        close = time(2, 29)
        final_day += timedelta(days=1)
    elif root in ONE_AM_CLOSE_ROOTS:
        close = time(0, 59)
        final_day += timedelta(days=1)
    else:
        # SHFE/INE 其余夜盘品种及 DCE/CZCE 夜盘品种均为 23:00 收盘。
        close = time(22, 59)
    return expected_first, datetime.combine(final_day, close)


def _load_mysql_history(
    symbol: str,
    exchange: Exchange,
) -> list[BarData]:
    """SELECT-only 加载，绕过 MysqlDatabase.__init__ 的 create_all。"""

    from vnpy.trader.database import DB_TZ
    from vnpy_mysql.mysql_database import DbBarData, SessionLocal

    session = SessionLocal()
    try:
        rows = session.query(DbBarData).filter(
            DbBarData.symbol == symbol,
            DbBarData.exchange == exchange.value,
            DbBarData.interval == Interval.MINUTE.value,
            DbBarData.datetime >= WARMUP_START,
            DbBarData.datetime <= END_CUTOFF,
        ).order_by(DbBarData.datetime).all()
        return [
            BarData(
                symbol=row.symbol,
                exchange=Exchange(row.exchange),
                datetime=datetime.fromtimestamp(row.datetime.timestamp(), DB_TZ),
                interval=Interval(row.interval),
                volume=row.volume,
                turnover=row.turnover,
                open_interest=row.open_interest,
                open_price=row.open_price,
                high_price=row.high_price,
                low_price=row.low_price,
                close_price=row.close_price,
                gateway_name="DB",
            )
            for row in rows
        ]
    finally:
        session.close()


def _load_bars(contract: Mapping[str, Any] | tuple[str, str]) -> tuple[list, list]:
    from vnpy.trader.setting import SETTINGS

    resolved = _resolve_contract(contract)
    symbol, exchange_text = resolved["vt_symbol"].rsplit(".", 1)
    exchange = Exchange(exchange_text)
    if SETTINGS["database.name"] == "mysql":
        history = _load_mysql_history(symbol, exchange)
    else:
        from vnpy.trader.database import get_database

        history = get_database().load_bar_data(
            symbol=symbol,
            exchange=exchange,
            interval=Interval.MINUTE,
            start=WARMUP_START,
            end=END_CUTOFF,
        )
    warmup_bars = [bar for bar in history if _naive(bar.datetime) < START]
    bars = [bar for bar in history if START <= _naive(bar.datetime) <= END_CUTOFF]
    vt_symbol = resolved["vt_symbol"]
    if not history or not bars:
        raise RuntimeError(f"{vt_symbol} 主区间无 1m 数据")
    if not warmup_bars:
        raise RuntimeError(f"{vt_symbol} 缺少 45 天预热数据")
    if len(bars) < MIN_MAIN_BARS:
        raise RuntimeError(f"{vt_symbol} 主区间仅 {len(bars)} 根，低于完整性门槛 {MIN_MAIN_BARS}")
    expected_first, expected_final = _expected_session_bounds(resolved)
    first_main = _naive(bars[0].datetime)
    if first_main != expected_first:
        raise RuntimeError(
            f"{vt_symbol} 主区间起点 {first_main.isoformat()} 不符合预期 "
            f"{expected_first.isoformat()}，不能视为完整覆盖"
        )
    final_bar = _naive(bars[-1].datetime)
    if final_bar != expected_final:
        raise RuntimeError(
            f"{vt_symbol} 最终交易时段不完整或越界: 最后 bar {final_bar.isoformat()}，"
            f"预期 {expected_final.isoformat()}；来源 {SESSION_CLOSE_SOURCE}"
        )
    return warmup_bars, bars


def _trade_rows(
    contract: Mapping[str, Any],
    model: str,
    slippage_ticks: int,
    engine: BacktestingEngine,
) -> list[dict]:
    orders = {order.orderid: order for order in engine.limit_orders.values()}
    rows = []
    for trade in sorted(engine.trades.values(), key=lambda item: _naive(item.datetime)):
        order = orders.get(trade.orderid)
        signal_datetime = order.datetime if order else None
        next_minute = bool(
            signal_datetime is not None
            and _naive(trade.datetime) > _naive(signal_datetime)
        )
        rows.append({
            "root": contract["root"],
            "vt_symbol": contract["vt_symbol"],
            "model": model,
            "slippage_ticks": slippage_ticks,
            "tradeid": trade.tradeid,
            "orderid": trade.orderid,
            "datetime": _iso(trade.datetime),
            "signal_datetime": _iso(signal_datetime),
            "next_minute_fill": next_minute,
            "direction": _exchange_value(trade.direction),
            "offset": _exchange_value(trade.offset),
            "price": float(trade.price),
            "volume": float(trade.volume),
        })
    return rows


def _audit_trade_fills(
    trade_rows: Sequence[Mapping[str, Any]],
    *,
    vt_symbol: str = "",
    model: str = "",
) -> dict:
    """零成交不视为已验证；任何真实成交时序异常都使该次回测失败。"""

    if not trade_rows:
        return {
            "next_minute_fill_verified": False,
            "fill_audit_status": "no_trades",
            "invalid_fill_count": 0,
        }
    invalid_count = sum(not bool(row.get("next_minute_fill")) for row in trade_rows)
    if invalid_count:
        raise RuntimeError(
            f"{vt_symbol} {model} {invalid_count} 笔成交时序异常："
            "成交必须严格晚于对应小时委托信号，且订单时间不得缺失"
        )
    return {
        "next_minute_fill_verified": True,
        "fill_audit_status": "verified",
        "invalid_fill_count": 0,
    }


def _run_model(
    contract: Mapping[str, Any],
    model: str,
    slippage_ticks: int,
    warmup_bars: list,
    bars: list,
) -> tuple[list[dict], list[dict], list[dict]]:
    engine = _make_engine(contract, slippage_ticks)
    messages: list[str] = []
    engine.output = lambda text: messages.append(str(text))
    engine.load_bar = lambda *args, **kwargs: warmup_bars
    setting = {"model": model, "fixed_size": 1}
    engine.add_strategy(BayesianQStrategy, dict(setting))
    actual = engine.strategy.get_parameters()
    for key, expected in setting.items():
        if actual.get(key) != expected:
            raise RuntimeError(
                f"{contract['vt_symbol']} 参数 {key} 被外部配置覆盖: "
                f"期望 {expected!r}，实际 {actual.get(key)!r}"
            )

    engine.history_data = bars
    engine.run_backtesting()
    ensure_backtest_completed(messages, engine.strategy, bars[-1])
    result_df = engine.calculate_result()
    add_fixed_fees(result_df, list(engine.trades.values()), contract["fixed_fee"])
    trade_rows = _trade_rows(contract, model, slippage_ticks, engine)
    fill_audit = _audit_trade_fills(
        trade_rows, vt_symbol=contract["vt_symbol"], model=model,
    )
    expected_first, expected_final = _expected_session_bounds(contract)
    first_signal = engine.strategy.first_signal_datetime
    last_trade = trade_rows[-1]["datetime"] if trade_rows else ""

    rows = []
    for period in PERIODS:
        period_df = result_df[[
            get_research_period(day) == period for day in result_df.index
        ]]
        rows.append({
            "root": contract["root"],
            "vt_symbol": contract["vt_symbol"],
            "model": model,
            "period": period,
            "slippage_ticks": slippage_ticks,
            "fixed_size": 1,
            "size": contract["size"],
            "pricetick": contract["pricetick"],
            "rate": contract["rate"],
            "fixed_fee": contract["fixed_fee"],
            "price_slippage": contract["pricetick"] * slippage_ticks,
            "warmup_bars": len(warmup_bars),
            "bars_loaded": len(bars),
            "first_bar": str(bars[0].datetime),
            "last_bar": str(bars[-1].datetime),
            "expected_first_bar": expected_first.isoformat(),
            "expected_final_bar": expected_final.isoformat(),
            "first_signal": _iso(first_signal),
            "final_position": int(engine.strategy.pos),
            "audit_records": len(engine.strategy.audit_records),
            "executed_trades": len(trade_rows),
            "traded_volume": sum(row["volume"] for row in trade_rows),
            "last_trade_datetime": last_trade,
            **fill_audit,
            **calculate_period_metrics(period_df),
        })

    signal_rows = []
    for record in engine.strategy.audit_records:
        signal_rows.append({
            "root": contract["root"],
            "vt_symbol": contract["vt_symbol"],
            "slippage_ticks": slippage_ticks,
            **record,
        })
    return rows, signal_rows, trade_rows


def _release_database() -> None:
    import vnpy.trader.database as database_module

    if database_module.database is None:
        return
    try:
        from vnpy_mysql.mysql_database import close_db_session, engine as mysql_engine

        close_db_session()
        mysql_engine.dispose()
    finally:
        database_module.database = None


def run_contract(
    contract: Mapping[str, Any] | tuple[str, str],
    slippage_ticks: int,
    models: Sequence[str] = MODEL_NAMES,
) -> dict:
    """加载一次 1m 数据，依次运行所选模型；任何异常使本合约本次成本作废。"""

    resolved = _resolve_contract(contract)
    if slippage_ticks not in (1, 2):
        raise ValueError("slippage_ticks 只允许 1 或 2")
    models = tuple(models)
    if not models or any(model not in MODEL_NAMES for model in models):
        raise ValueError("models 为空或含未知模型")
    if len(set(models)) != len(models):
        raise ValueError("models 不允许重复")

    try:
        warmup_bars, bars = _load_bars(resolved)
        rows = []
        signals: dict[str, list[dict]] = {}
        trades: dict[str, list[dict]] = {}
        for model in models:
            model_rows, model_signals, model_trades = _run_model(
                resolved, model, slippage_ticks, warmup_bars, bars
            )
            rows.extend(model_rows)
            signals[model] = model_signals
            trades[model] = model_trades
        expected_first, expected_final = _expected_session_bounds(resolved)
        all_trade_rows = [row for items in trades.values() for row in items]
        metadata = {
            "root": resolved["root"],
            "vt_symbol": resolved["vt_symbol"],
            "models": list(models),
            "slippage_ticks": slippage_ticks,
            "fixed_size": 1,
            "rate": resolved["rate"],
            "fixed_fee": resolved["fixed_fee"],
            "price_slippage": resolved["pricetick"] * slippage_ticks,
            "warmup_bars": len(warmup_bars),
            "bars_loaded": len(bars),
            "first_bar": str(bars[0].datetime),
            "last_bar": str(bars[-1].datetime),
            "expected_first_bar": expected_first.isoformat(),
            "expected_final_bar": expected_final.isoformat(),
            "session_close_source": SESSION_CLOSE_SOURCE,
            "dataset_cutoff_not_official_close": END_CUTOFF.isoformat(),
            "executed_trades": len(all_trade_rows),
            "zero_trade_models": [model for model in models if not trades[model]],
            **_audit_trade_fills(
                all_trade_rows, vt_symbol=resolved["vt_symbol"], model="ALL",
            ),
        }
        print(
            f"完成 {resolved['vt_symbol']}，{len(models)} 模型，"
            f"{len(rows)} 个分段结果，{len(bars)} 根主区间 K 线",
            flush=True,
        )
        return {"rows": rows, "signals": signals, "trades": trades, "metadata": metadata}
    finally:
        _release_database()


def _safe_symbol(vt_symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", vt_symbol)


def _write_frame(path: Path, records: list[dict], fields: list[str]) -> None:
    df = pd.DataFrame(records)
    columns = list(dict.fromkeys([*fields, *df.columns]))
    df.reindex(columns=columns).to_csv(path, index=False)


def _read_failure_rows(path: Path) -> list[dict]:
    if not path.exists() or not path.stat().st_size:
        return []
    return pd.read_csv(path, keep_default_na=False).to_dict("records")


def _failure_cost(row: Mapping[str, Any]) -> int | None:
    value = row.get("slippage_ticks")
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _merge_failure_rows(*groups: Sequence[Mapping[str, Any]]) -> list[dict]:
    """按 root/合约/原因/成本去重，后写入的当前盘点或运行结果优先。"""

    merged: dict[tuple[str, str, str, int | None], dict] = {}
    for group in groups:
        for source in group:
            row = dict(source)
            key = (
                str(row.get("root", "")).casefold(),
                str(row.get("vt_symbol", "")).casefold(),
                str(row.get("reason", "")),
                _failure_cost(row),
            )
            merged[key] = row
    return list(merged.values())


def _drop_backtest_failure(
    failures: Sequence[Mapping[str, Any]],
    vt_symbol: str,
    slippage_ticks: int,
) -> list[dict]:
    return [
        dict(row) for row in failures
        if not (
            row.get("reason") == "backtest_failed"
            and str(row.get("vt_symbol", "")).casefold() == vt_symbol.casefold()
            and _failure_cost(row) == slippage_ticks
        )
    ]


def _append_detail(path: Path, rows: list[dict]) -> None:
    new = pd.DataFrame(rows).reindex(columns=DETAIL_FIELDS)
    if path.exists() and path.stat().st_size:
        old = pd.read_csv(path)
        combined = new.copy() if old.empty else pd.concat([old, new], ignore_index=True)
    else:
        combined = new
    combined = combined.drop_duplicates(
        subset=["root", "vt_symbol", "model", "period", "slippage_ticks"],
        keep="last",
    )
    combined.reindex(columns=DETAIL_FIELDS).to_csv(path, index=False)


def _prune_contract_result(output_dir: Path, vt_symbol: str, slippage_ticks: int) -> None:
    """失败尝试不得留下同合约/成本、看似成功的明细或审计产物。"""

    detail_path = output_dir / "batch_detail.csv"
    remaining: list[dict] = []
    if detail_path.exists() and detail_path.stat().st_size:
        for row in pd.read_csv(detail_path).to_dict("records"):
            same_symbol = str(row.get("vt_symbol", "")).casefold() == vt_symbol.casefold()
            cost = _failure_cost(row)
            same_or_legacy_unknown_cost = cost is None or cost == slippage_ticks
            if not (same_symbol and same_or_legacy_unknown_cost):
                remaining.append(row)
    _write_frame(detail_path, remaining, DETAIL_FIELDS)

    safe = _safe_symbol(vt_symbol)
    patterns = [
        f"signals_{safe}_*_slippage{slippage_ticks}.csv",
        f"trades_{safe}_*_slippage{slippage_ticks}.csv",
        f"{safe}-slippage{slippage_ticks}-metadata.json",
    ]
    for pattern in patterns:
        for path in output_dir.glob(pattern):
            path.unlink()


def _git_state() -> dict:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True
        ).strip()
        return {"head": head, "dirty": bool(status)}
    except (subprocess.CalledProcessError, OSError):
        return {"head": "unknown", "dirty": True}


def _session_policy_metadata() -> dict:
    return {
        "source": SESSION_CLOSE_SOURCE,
        "first_session": "2026-05-06 09:00；CFFEX 09:30（分钟起始时间戳）",
        "dataset_cutoff": END_CUTOFF.isoformat(),
        "dataset_cutoff_is_not_official_close": True,
        "repository_generic_session_not_used_as_universal_close": (
            "config.trading_sessions_config.CN_FUTURES_SESSION/CN_CFFEX_SESSION"
        ),
        "day_only_roots": sorted(DAY_ONLY_ROOTS),
        "gfex_day_close": "14:59",
        "cffex_bond_roots": sorted(CFFEX_BOND_ROOTS),
        "cffex_bond_close": "15:14",
        "cffex_other_close": "14:59",
        "one_am_close_roots": sorted(ONE_AM_CLOSE_ROOTS),
        "two_thirty_close_roots": sorted(TWO_THIRTY_CLOSE_ROOTS),
        "other_night_session_close": "22:59",
        "zero_trade_fill_policy": (
            "next_minute_fill_verified=false/status=no_trades；零成交本身不报错；"
            "任何真实成交缺失信号时间或未严格晚于信号均拒绝该合约/成本"
        ),
    }


def _reason_counts(failures: Sequence[Mapping[str, Any]]) -> dict:
    counter = Counter(
        part
        for row in failures
        for part in str(row.get("reason", "")).split(";")
        if part
    )
    return dict(sorted(counter.items()))


def _base_metadata(overviews: Sequence[BarOverview]) -> dict:
    return {
        "models": list(MODEL_NAMES),
        "fixed_size": 1,
        "capital": CAPITAL,
        "periods": {
            "main": "2026-05-01 至 2026-10-30",
            "warmup_start": WARMUP_START.date().isoformat(),
            "end_cutoff": END_CUTOFF.isoformat(),
            "train": "2026-05-01 至 2026-08-14",
            "validation": "2026-08-15 至 2026-09-15",
            "review": "2026-09-16 至 2026-10-30，二次验证，非全新样本外",
        },
        "costs": {
            "slippage_ticks": [1, 2],
            "price_slippage": "pricetick × 1/2，每边",
            "proportional_fee": "成交名义金额 × rate",
            "fixed_fee": "legacy slippage/fixed_fee × 实际成交手数，不乘 size",
        },
        "session_coverage_policy": _session_policy_metadata(),
        "overview_snapshot": [
            {
                "symbol": row.symbol,
                "exchange": _exchange_value(row.exchange),
                "interval": _exchange_value(row.interval),
                "count": int(row.count or 0),
                "start": _iso(row.start),
                "end": _iso(row.end),
            }
            for row in overviews
        ],
        "git": _git_state(),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def write_inventory_outputs(
    selected: list[dict],
    failures: list[dict],
    overviews: Sequence[BarOverview],
    *,
    output_dir: Path = OUTPUT_DIR,
    config_count: int | None = None,
    db_root_count: int | None = None,
    overview_recovery: Mapping[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    failure_path = output_dir / "contract_failures.csv"
    previous_backtest_failures = [
        row for row in _read_failure_rows(failure_path)
        if row.get("reason") == "backtest_failed"
    ]
    output_failures = _merge_failure_rows(failures, previous_backtest_failures)
    _write_frame(output_dir / "contract_inventory.csv", selected, INVENTORY_FIELDS)
    _write_frame(failure_path, output_failures, FAILURE_FIELDS)
    detail_path = output_dir / "batch_detail.csv"
    if not detail_path.exists():
        _write_frame(detail_path, [], DETAIL_FIELDS)

    metadata = _base_metadata(overviews)
    failed_root_keys = {str(row["root"]).casefold() for row in failures}
    selected_root_keys = {str(row["root"]).casefold() for row in selected}
    metadata["counts"] = {
        "configured_roots": config_count,
        "db_roots": db_root_count,
        "selected": len(selected),
        "failed_roots": len(failed_root_keys),
        "union_roots": len(selected_root_keys | failed_root_keys),
        "failure_records": len(failures),
        "failures": len(failures),
        "persisted_backtest_failures": len(previous_backtest_failures),
        "failures_by_reason": _reason_counts(failures),
    }
    metadata["overview_recovery"] = dict(overview_recovery or {"source": "get_bar_overview"})
    _write_json(output_dir / "metadata.json", metadata)


def _update_run_metadata(
    output_dir: Path,
    result: Mapping[str, Any],
    slippage_ticks: int,
    models: Sequence[str],
) -> None:
    path = output_dir / "metadata.json"
    if path.exists():
        metadata = json.loads(path.read_text(encoding="utf-8"))
    else:
        metadata = _base_metadata([])
    detail_rows = list(result["rows"])
    metadata["last_run"] = {
        "slippage_ticks": slippage_ticks,
        "models": list(models),
        "completed_contracts": sorted({row["vt_symbol"] for row in detail_rows}),
        "detail_rows": len(detail_rows),
        "failure_count": len(result["failures"]),
        "new_backtest_failures": result.get("new_backtest_failures", 0),
        # 空结果不验证；所有明细行必须验证通过，零成交模型的 false 不会被掩盖。
        "next_minute_fill_verified": bool(detail_rows) and all(
            bool(row.get("next_minute_fill_verified", False)) for row in detail_rows
        ),
        "zero_trade_models": sorted({
            f"{row['vt_symbol']}:{row['model']}"
            for row in detail_rows if row.get("executed_trades") == 0
        }),
        "errors": list(result.get("errors", [])),
    }
    metadata["git"] = _git_state()
    _write_json(path, metadata)


def save_contract_result(output_dir: Path, contract_result: Mapping[str, Any]) -> None:
    """一个合约/成本完成后立即更新总明细和逐模型审计文件。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    _append_detail(output_dir / "batch_detail.csv", contract_result["rows"])
    metadata = contract_result["metadata"]
    stem = f"{_safe_symbol(metadata['vt_symbol'])}-slippage{metadata['slippage_ticks']}"
    for model in contract_result["metadata"]["models"]:
        _write_frame(
            output_dir / f"signals_{_safe_symbol(metadata['vt_symbol'])}_{model}_slippage{metadata['slippage_ticks']}.csv",
            contract_result["signals"].get(model, []),
            SIGNAL_FIELDS,
        )
        _write_frame(
            output_dir / f"trades_{_safe_symbol(metadata['vt_symbol'])}_{model}_slippage{metadata['slippage_ticks']}.csv",
            contract_result["trades"].get(model, []),
            TRADE_FIELDS,
        )
    _write_json(output_dir / f"{stem}-metadata.json", {
        **metadata,
        "periods": _base_metadata([])["periods"],
        "session_coverage_policy": _session_policy_metadata(),
        "git": _git_state(),
    })


def run_batch(
    contracts: Sequence[Mapping[str, Any] | tuple[str, str]],
    slippage_ticks: int,
    models: Sequence[str] = MODEL_NAMES,
    *,
    output_dir: Path = OUTPUT_DIR,
    initial_failures: Sequence[Mapping[str, Any]] | None = None,
    runner: Callable | None = None,
) -> dict:
    runner = runner or run_contract
    output_dir.mkdir(parents=True, exist_ok=True)
    failure_path = output_dir / "contract_failures.csv"
    failures = _merge_failure_rows(
        _read_failure_rows(failure_path), initial_failures or []
    )
    new_backtest_failures = 0
    errors = []
    rows = []
    _write_frame(failure_path, failures, FAILURE_FIELDS)
    for contract in contracts:
        resolved = dict(contract) if isinstance(contract, Mapping) else {
            "root": contract[0], "vt_symbol": contract[1]
        }
        vt_symbol = str(resolved.get("vt_symbol", ""))
        # 新尝试开始即作废旧同成本结果，异常后再次清理部分写入。
        _prune_contract_result(output_dir, vt_symbol, slippage_ticks)
        # 同合约同成本的新尝试取代旧失败；另一成本的失败必须继续保留。
        failures = _drop_backtest_failure(failures, vt_symbol, slippage_ticks)
        _write_frame(failure_path, failures, FAILURE_FIELDS)
        try:
            contract_result = runner(contract, slippage_ticks, models)
            save_contract_result(output_dir, contract_result)
            rows.extend(contract_result["rows"])
        except Exception as exc:
            _prune_contract_result(output_dir, vt_symbol, slippage_ticks)
            traceback_text = traceback.format_exc()
            error = {
                "root": resolved.get("root", ""),
                "vt_symbol": vt_symbol,
                "slippage_ticks": slippage_ticks,
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "traceback": traceback_text,
            }
            errors.append(error)
            failures.append({
                "root": resolved.get("root", ""),
                "vt_symbol": vt_symbol,
                "exchange": resolved.get("exchange", ""),
                "count": resolved.get("count", 0),
                "start": resolved.get("start", ""),
                "end": resolved.get("end", ""),
                "slippage_ticks": slippage_ticks,
                "reason": "backtest_failed",
                "detail": str(exc),
                "exception_type": type(exc).__name__,
                "traceback": traceback_text,
            })
            new_backtest_failures += 1
            print(f"失败 {vt_symbol}: {exc}", flush=True)
        _write_frame(failure_path, failures, FAILURE_FIELDS)
        _update_run_metadata(
            output_dir,
            {
                "rows": rows,
                "failures": failures,
                "new_backtest_failures": new_backtest_failures,
                "errors": errors,
            },
            slippage_ticks,
            models,
        )
    _write_frame(failure_path, failures, FAILURE_FIELDS)
    return {
        "rows": rows,
        "failures": failures,
        "new_backtest_failures": new_backtest_failures,
        "errors": errors,
    }


def _configure_settings() -> None:
    """本 checkout 的 config.settings 不自动应用；数据库访问前显式加载 .env。"""

    from config.settings import get_atmquant_settings, load_env_file
    from vnpy.trader.setting import SETTINGS

    load_env_file(str(PROJECT_ROOT / ".env"))
    SETTINGS.update(get_atmquant_settings())


def _load_database_overviews() -> tuple[list[BarOverview], dict]:
    """MySQL 只执行 SELECT；禁止公共 API 的 init/add/commit/create_all 路径。"""

    from vnpy.trader.setting import SETTINGS

    if SETTINGS["database.name"] != "mysql":
        from vnpy.trader.database import get_database

        try:
            overviews = get_database().get_bar_overview()
            public = {"called": True, "error_type": None, "traceback": None}
            source = "get_bar_overview"
        except Exception as exc:
            overviews = []
            public = {
                "called": True,
                "error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
            source = "get_bar_overview_failed"
        return overviews, {
            "source": source,
            "fallback_used": False,
            "fallback_trigger": None,
            "public_overview": public,
            "invalid_rows": [],
        }

    # 不实例化 MysqlDatabase：其 __init__ 会 create_all；公共 get_bar_overview
    # 还可能在空 overview 时 init/add/commit。SessionLocal 仅用于 SELECT。
    from vnpy_mysql.mysql_database import DbBarOverview, SessionLocal

    session = SessionLocal()
    try:
        raw_rows = session.query(DbBarOverview).filter(
            DbBarOverview.interval == Interval.MINUTE.value
        ).all()
    finally:
        session.close()

    recovered = []
    invalid_rows = []
    for row in raw_rows:
        try:
            exchange = Exchange(row.exchange)
            interval = Interval(row.interval)
        except ValueError as exc:
            invalid_rows.append({
                "symbol": row.symbol,
                "exchange": row.exchange,
                "interval": row.interval,
                "count": int(row.count or 0),
                "start": _iso(row.start),
                "end": _iso(row.end),
                "reason": str(exc),
            })
            continue
        recovered.append(BarOverview(
            symbol=row.symbol,
            exchange=exchange,
            interval=interval,
            count=int(row.count),
            start=row.start,
            end=row.end,
        ))
    return recovered, {
        "source": "mysql_select_only_1m_overview",
        "fallback_used": False,
        "fallback_trigger": "mysql_public_api_bypassed_by_select_only_guard",
        "public_overview": {
            "called": False,
            "error_type": None,
            "traceback": None,
            "guard_reason": (
                "public API may initialize missing overviews and rejects the complete "
                "result on unknown non-futures Exchange values"
            ),
        },
        "raw_1m_rows": len(raw_rows),
        "recovered_1m_rows": len(recovered),
        "invalid_rows": invalid_rows,
        "writes": {
            "create_all_called": False,
            "init_bar_overview_called": False,
            "add_called": False,
            "commit_called": False,
        },
    }


def _parse_models(value: str) -> tuple[str, ...]:
    models = tuple(part.strip() for part in value.split(",") if part.strip())
    if not models or any(model not in MODEL_NAMES for model in models):
        raise ValueError(f"models 必须为 {','.join(MODEL_NAMES)} 的非空子集")
    if len(set(models)) != len(models):
        raise ValueError("models 不允许重复")
    return models


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", help="只运行指定 vt_symbol")
    parser.add_argument("--models", default=",".join(MODEL_NAMES))
    parser.add_argument("--slippage-ticks", type=int, default=1, choices=[1, 2])
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args(argv)
    models = _parse_models(args.models)

    _configure_settings()
    from loguru import logger

    logger.remove()
    overviews, recovery = _load_database_overviews()
    selected, failures = discover_futures_universe(overviews)
    db_roots = {
        _root_from_symbol(row.symbol).casefold()
        for row in overviews
        if row.interval == Interval.MINUTE and _root_from_symbol(row.symbol)
    }
    write_inventory_outputs(
        selected,
        failures,
        overviews,
        config_count=len(FUTURES_INFO),
        db_root_count=len(db_roots),
        overview_recovery=recovery,
    )
    failed_root_keys = {row["root"].casefold() for row in failures}
    summary = {
        "configured_roots": len(FUTURES_INFO),
        "db_roots": len(db_roots),
        "selected": len(selected),
        "failed_roots": len(failed_root_keys),
        "union_roots": len(selected) + len(failed_root_keys),
        "failure_records": len(failures),
        "failures_by_reason": _reason_counts(failures),
        "overview_recovery": recovery["source"],
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if args.inventory_only:
        return 0

    contracts = [
        contract for contract in selected
        if not args.contract or contract["vt_symbol"].casefold() == args.contract.casefold()
    ]
    if args.contract and not contracts:
        raise ValueError(f"指定合约不在有效 inventory: {args.contract}")
    if not contracts:
        print("没有可回测合约；请检查 contract_failures.csv", flush=True)
        return 1

    result = run_batch(
        contracts,
        args.slippage_ticks,
        models,
        initial_failures=failures,
    )
    print(json.dumps({
        "detail_rows_this_run": len(result["rows"]),
        "completed_contracts": len({row["vt_symbol"] for row in result["rows"]}),
        "new_backtest_failures": result["new_backtest_failures"],
        "output_dir": str(OUTPUT_DIR),
    }, ensure_ascii=False), flush=True)
    return 1 if result["new_backtest_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
