"""盈利品种子样本的成交与筛选测试。"""

import pandas as pd
import pytest

from scripts.bayesian_q_winner_case import round_trip_pnls, select_winner_rows


def trade(direction, offset, price, volume=1.0):
    return {
        "direction": direction,
        "offset": offset,
        "price": price,
        "volume": volume,
    }


def test_long_round_trip_uses_actual_prices_and_both_side_fees() -> None:
    frame = pd.DataFrame([
        trade("多", "开", 100.0),
        trade("空", "平", 105.0),
    ])

    result = round_trip_pnls(frame, size=10, fixed_fee=2.0, rate=0.0)

    assert result.tolist() == [46.0]


def test_short_round_trip_handles_volume_and_rate() -> None:
    frame = pd.DataFrame([
        trade("空", "开", 100.0, 2.0),
        trade("多", "平", 95.0, 2.0),
    ])

    result = round_trip_pnls(frame, size=10, fixed_fee=2.0, rate=0.001)

    assert result.tolist() == pytest.approx([88.1])


def test_unclosed_position_is_not_counted_as_winning_trade() -> None:
    frame = pd.DataFrame([trade("多", "开", 100.0)])
    assert round_trip_pnls(frame, size=10, fixed_fee=2.0, rate=0.0).empty


def test_winner_selection_is_scoped_to_model_period_and_cost() -> None:
    detail = pd.DataFrame([
        {"root": "a", "model": "bayes_q_fixed", "period": "review", "slippage_ticks": 1, "total_net_pnl": 10.0},
        {"root": "b", "model": "bayes_q_fixed", "period": "review", "slippage_ticks": 1, "total_net_pnl": -5.0},
        {"root": "c", "model": "bayes_q_fixed", "period": "train", "slippage_ticks": 1, "total_net_pnl": 20.0},
        {"root": "d", "model": "bayes_q_fixed", "period": "review", "slippage_ticks": 2, "total_net_pnl": 30.0},
    ])

    selected = select_winner_rows(detail, "bayes_q_fixed", "review", 1)

    assert selected["root"].tolist() == ["a"]
