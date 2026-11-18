"""分位数风险批量实验协议与统计测试。"""

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.batch_backtest_quantile_risk import (
    MODEL_NAMES,
    TAU,
    atr_var_forecast,
    candidate_passes,
    turnover_metrics,
)


def test_preregistered_models_quantile_and_caps_are_frozen() -> None:
    assert MODEL_NAMES == ("fixed", "atr", "historical", "ewma", "caviar")
    assert TAU == 0.05


def test_atr_forecast_uses_previous_completed_bar() -> None:
    bars = [
        SimpleNamespace(high_price=102.0, low_price=98.0, close_price=100.0),
        SimpleNamespace(high_price=103.0, low_price=99.0, close_price=101.0),
        SimpleNamespace(high_price=200.0, low_price=1.0, close_price=100.0),
    ]

    forecasts = atr_var_forecast(bars, window=2)
    changed = list(bars)
    changed[2] = SimpleNamespace(high_price=101.0, low_price=99.0, close_price=100.0)
    changed_forecasts = atr_var_forecast(changed, window=2)

    assert forecasts[2] == pytest.approx(changed_forecasts[2])
    assert np.isnan(forecasts[1])


def test_turnover_uses_actual_volume_and_notional() -> None:
    trades = [
        SimpleNamespace(datetime=datetime(2026, 9, 20, 10, 0), price=100.0, volume=2),
        SimpleNamespace(datetime=datetime(2026, 9, 21, 10, 0), price=110.0, volume=1),
    ]

    metrics = turnover_metrics(trades, contract_size=10, capital=10_000)

    assert metrics["traded_volume"] == 3
    assert metrics["turnover_ratio"] == pytest.approx(0.31)


def test_candidate_gate_requires_drawdown_sharpe_and_breadth() -> None:
    passing = {
        "drawdown_improved": 8,
        "drawdown_relative_reduction": 0.25,
        "caviar_sharpe": 0.4,
        "fixed_sharpe": 0.3,
    }
    assert candidate_passes(passing)
    assert not candidate_passes({**passing, "drawdown_improved": 7})
    assert not candidate_passes({**passing, "drawdown_relative_reduction": 0.19})
    assert not candidate_passes({**passing, "caviar_sharpe": 0.2})
