"""逻辑回归批量研究的完整性与选参测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.batch_backtest_logistic_direction import (
    LOGISTIC_GRID,
    add_fixed_fees,
    calculate_period_metrics,
    ensure_backtest_completed,
    select_logistic_parameters,
)


def make_row(param_id: int, period: str, total_return: float, drawdown: float = -1.0):
    return {
        "model": "logistic",
        "train_window": 240 + param_id,
        "prob_threshold": 0.05,
        "period": period,
        "vt_symbol": "rb2701.SHFE",
        "total_return": total_return,
        "max_ddpercent": drawdown,
        "trade_count": 10,
    }


def test_preregistered_grid_contains_4_unique_parameter_sets() -> None:
    """预登记网格必须是4个唯一组合。"""
    assert len(LOGISTIC_GRID) == 4
    assert len({
        (row["train_window"], row["prob_threshold"]) for row in LOGISTIC_GRID
    }) == 4


def test_selection_ignores_review_period() -> None:
    """复检段收益再高也不能影响参数选择。"""
    rows = [
        make_row(1, "train", 3.0),
        make_row(1, "validation", 2.0),
        make_row(1, "review", -1000.0),
        make_row(2, "train", 1.0),
        make_row(2, "validation", 0.5),
        make_row(2, "review", 1000.0),
    ]

    selected = select_logistic_parameters(rows)

    assert selected["train_window"] == 241


def test_period_drawdown_includes_initial_capital_highwater() -> None:
    """区间首日亏损必须形成回撤，不能从亏损后的余额重新起算高水位。"""
    df = pd.DataFrame(
        [{"net_pnl": -100.0, "commission": 5.0, "slippage": 5.0, "trade_count": 2}],
        index=[pd.Timestamp("2026-10-30").date()],
    )

    metrics = calculate_period_metrics(df, capital=1000)

    assert metrics["max_ddpercent"] == pytest.approx(-10.0)
    assert metrics["gross_pnl"] == pytest.approx(-90.0)


def test_add_fixed_fees_per_lot() -> None:
    """固定手续费按成交手数计入当日 commission 并扣减 net_pnl。"""
    day = pd.Timestamp("2026-10-30").date()
    df = pd.DataFrame(
        [{"net_pnl": 100.0, "commission": 0.0, "slippage": 0.0, "trade_count": 2}],
        index=[day],
    )
    trades = [
        SimpleNamespace(datetime=datetime(2026, 10, 30, 10, 0, tzinfo=UTC), volume=2),
        SimpleNamespace(datetime=datetime(2026, 10, 30, 14, 0, tzinfo=UTC), volume=2),
    ]

    add_fixed_fees(df, trades, fixed_fee=3.0)

    assert df.loc[day, "commission"] == pytest.approx(12.0)
    assert df.loc[day, "net_pnl"] == pytest.approx(88.0)


def test_zero_fixed_fee_leaves_df_untouched() -> None:
    """固定费为 0 的品种不改结果。"""
    day = pd.Timestamp("2026-10-30").date()
    df = pd.DataFrame(
        [{"net_pnl": 100.0, "commission": 1.0, "slippage": 0.0, "trade_count": 1}],
        index=[day],
    )
    trades = [SimpleNamespace(datetime=datetime(2026, 10, 30, 10, 0, tzinfo=UTC), volume=1)]

    add_fixed_fees(df, trades, fixed_fee=0.0)

    assert df.loc[day, "commission"] == pytest.approx(1.0)
    assert df.loc[day, "net_pnl"] == pytest.approx(100.0)


def test_backtest_error_and_unfinished_last_bar_are_not_silent() -> None:
    """引擎异常或时间戳未消费到最后都要让该组实验失败。"""
    final_bar = SimpleNamespace(datetime=datetime(2026, 10, 30, 15, 0, tzinfo=UTC))
    strategy = SimpleNamespace(last_bar_datetime=datetime(2026, 10, 30, 14, 59, tzinfo=UTC))

    with pytest.raises(RuntimeError, match="回测异常"):
        ensure_backtest_completed(["触发异常，回测终止"], strategy, final_bar)
    with pytest.raises(RuntimeError, match="最后一根K线"):
        ensure_backtest_completed([], strategy, final_bar)
