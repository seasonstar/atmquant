"""自适应回归批量研究的完整性与选参测试。"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.batch_backtest_adaptive_linear_regression import (
    ADAPTIVE_GRID,
    calculate_period_metrics,
    ensure_backtest_completed,
    select_adaptive_parameters,
)


def make_row(param_id: int, period: str, total_return: float, drawdown: float = -1.0):
    return {
        "model": "adaptive",
        "scan_horizon": 10 + param_id,
        "deviation_factor": 2.0,
        "structural_sensitivity": 5,
        "quality_threshold": 0.5,
        "period": period,
        "vt_symbol": "rb2701.SHFE",
        "total_return": total_return,
        "max_ddpercent": drawdown,
        "trade_count": 10,
    }


def test_preregistered_grid_contains_36_unique_parameter_sets() -> None:
    """四个预登记维度必须形成36个唯一组合。"""
    assert len(ADAPTIVE_GRID) == 36
    assert len({tuple(sorted(row.items())) for row in ADAPTIVE_GRID}) == 36


def test_selection_ignores_review_and_prefers_smaller_drawdown() -> None:
    """复检段不能改参数，同收益时负回撤绝对值较小者优先。"""
    rows = [
        make_row(1, "train", 3.0, -5.0),
        make_row(1, "validation", 2.0, -5.0),
        make_row(1, "review", 1000.0, -0.1),
        make_row(2, "train", 3.0, -1.0),
        make_row(2, "validation", 2.0, -1.0),
        make_row(2, "review", -1000.0, -20.0),
    ]

    selected = select_adaptive_parameters(rows)

    assert selected["scan_horizon"] == 12


def test_period_drawdown_includes_initial_capital_highwater() -> None:
    """区间首日亏损必须形成回撤，不能从亏损后的余额重新起算高水位。"""
    df = pd.DataFrame(
        [{"net_pnl": -100.0, "commission": 5.0, "slippage": 5.0, "trade_count": 2}],
        index=[date(2026, 10, 30)],
    )

    metrics = calculate_period_metrics(df, capital=1000)

    assert metrics["max_ddpercent"] == pytest.approx(-10.0)
    assert metrics["gross_pnl"] == pytest.approx(-90.0)


def test_backtest_error_and_unfinished_last_bar_are_not_silent() -> None:
    """引擎异常或时间戳未消费到最后都要让该组实验失败。"""
    final_bar = SimpleNamespace(datetime=datetime(2026, 10, 30, 15, 0, tzinfo=UTC))
    strategy = SimpleNamespace(last_bar_datetime=datetime(2026, 10, 30, 14, 59, tzinfo=UTC))

    with pytest.raises(RuntimeError, match="回测异常"):
        ensure_backtest_completed(["触发异常，回测终止"], strategy, final_bar)
    with pytest.raises(RuntimeError, match="最后一根K线"):
        ensure_backtest_completed([], strategy, final_bar)
