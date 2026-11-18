"""稳健回归效率通道批量研究测试。"""

from scripts.batch_backtest_robust_regression_efficiency_channel import (
    ROBUST_GRID,
    select_robust_parameters,
)


def make_row(param_id: int, period: str, total_return: float, drawdown: float = -1.0):
    return {
        "model": "robust",
        "window": 20 + param_id,
        "deviation_factor": 2.0,
        "er_threshold": 0.3,
        "period": period,
        "vt_symbol": "rb2701.SHFE",
        "total_return": total_return,
        "max_ddpercent": drawdown,
        "trade_count": 10,
    }


def test_grid_has_18_unique_preregistered_combinations() -> None:
    """独立网格必须包含18个唯一组合。"""
    assert len(ROBUST_GRID) == 18
    assert len({tuple(sorted(row.items())) for row in ROBUST_GRID}) == 18


def test_selection_ignores_review_and_uses_smaller_drawdown() -> None:
    """复检不能改参数，同收益时负数回撤更接近0者优先。"""
    rows = [
        make_row(1, "train", 2.0, -4.0),
        make_row(1, "validation", 1.0, -4.0),
        make_row(1, "review", 999.0, -0.1),
        make_row(2, "train", 2.0, -1.0),
        make_row(2, "validation", 1.0, -1.0),
        make_row(2, "review", -999.0, -10.0),
    ]

    selected = select_robust_parameters(rows)

    assert selected["window"] == 22
