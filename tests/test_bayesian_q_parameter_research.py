# -*- coding: utf-8 -*-
"""15 分钟冻结参数研究的参数化、执行和选参隔离测试。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

import pandas as pd
import pytest

from core.indicators.calculators.bayesian_q_calculator import BayesianQCalculator
from core.indicators.calculators.nqqe_calculator import NqqeCalculator
from core.strategies.base_strategy import BaseCtaStrategy
from core.strategies.bayesian_q_strategy import BayesianQStrategy
from scripts.bayesian_q_parameter_research import MODELS, PARAM_SETS, select_parameters


@dataclass(frozen=True)
class Bar:
    close_price: float


def _bars(closes):
    return [Bar(float(close)) for close in closes]


EXPECTED_PARAM_SETS = {
    "default": {
        "signal_minutes": 15,
        "bb_period": 20,
        "bb_stddev_mult": 2.5,
        "bayes_lookback": 20,
        "lower_threshold": 0.15,
        "rsi_period": 14,
        "rsi_smoothing": 5,
        "atrrsi_multiplier": 4.236,
    },
    "fast": {
        "signal_minutes": 15,
        "bb_period": 14,
        "bb_stddev_mult": 2.5,
        "bayes_lookback": 14,
        "lower_threshold": 0.15,
        "rsi_period": 10,
        "rsi_smoothing": 3,
        "atrrsi_multiplier": 4.236,
    },
    "slow": {
        "signal_minutes": 15,
        "bb_period": 34,
        "bb_stddev_mult": 2.5,
        "bayes_lookback": 34,
        "lower_threshold": 0.15,
        "rsi_period": 21,
        "rsi_smoothing": 7,
        "atrrsi_multiplier": 4.236,
    },
    "strict": {
        "signal_minutes": 15,
        "bb_period": 20,
        "bb_stddev_mult": 2.5,
        "bayes_lookback": 20,
        "lower_threshold": 0.25,
        "rsi_period": 14,
        "rsi_smoothing": 5,
        "atrrsi_multiplier": 4.236,
    },
}


def _sequence(states, fields):
    return [
        tuple(
            "nan" if isinstance(getattr(state, field), float)
            and math.isnan(getattr(state, field)) else getattr(state, field)
            for field in fields
        )
        for state in states
    ]


def test_default_calculators_preserve_original_recursions():
    bars = _bars(100 + 3 * math.sin(i * 0.31) + i * 0.03 for i in range(80))
    nqqe_fields = ("rsi", "qqef", "qqes", "crossover", "crossunder")
    combined_fields = ("sma", "upper", "sigma_up_legacy", "prime_fixed")

    default_nqqe = NqqeCalculator.compute(bars)
    explicit_nqqe = NqqeCalculator.compute(
        bars, rsi_period=14, rsi_smoothing=5, atrrsi_multiplier=4.236
    )
    default_combined = BayesianQCalculator.compute(bars)
    explicit_combined = BayesianQCalculator.compute(
        bars,
        **{key: value for key, value in EXPECTED_PARAM_SETS["default"].items()
           if key != "signal_minutes"},
    )

    assert _sequence(default_nqqe, nqqe_fields) == _sequence(explicit_nqqe, nqqe_fields)
    assert [state.signals for state in default_combined] == [
        state.signals for state in explicit_combined
    ]
    assert _sequence([s.bayes for s in default_combined], combined_fields) == _sequence(
        [s.bayes for s in explicit_combined], combined_fields
    )
    assert _sequence([s.nqqe for s in default_combined], nqqe_fields) == _sequence(
        [s.nqqe for s in explicit_combined], nqqe_fields
    )


def test_custom_nqqe_periods_change_rsi_smoothing_and_band_recursions():
    bars = _bars(100 + 4 * math.sin(i * 0.27) + i * 0.05 for i in range(80))
    base = NqqeCalculator.compute(bars)
    custom = NqqeCalculator.compute(
        bars, rsi_period=10, rsi_smoothing=3, atrrsi_multiplier=3.0
    )

    assert any(
        (math.isnan(a.rsi) and not math.isnan(b.rsi))
        or (not math.isnan(a.rsi) and not math.isnan(b.rsi) and a.rsi != b.rsi)
        for a, b in zip(base, custom)
    )
    assert any(
        not math.isnan(a.qqef) and not math.isnan(b.qqef) and a.qqef != b.qqef
        for a, b in zip(base, custom)
    )
    assert any(a.qqes != b.qqes for a, b in zip(base, custom))


def test_custom_bayes_windows_and_threshold_change_states():
    bars = _bars(100 + 4 * math.sin(i * 0.27) + i * 0.05 for i in range(80))
    base = BayesianQCalculator.compute(bars)
    custom = BayesianQCalculator.compute(
        bars, bb_period=14, bayes_lookback=14, lower_threshold=0.25
    )

    assert any(state.bayes.ready for state in custom[:38])
    assert not any(state.bayes.ready for state in base[:38])
    assert any(
        not math.isnan(a.bayes.upper) and not math.isnan(b.bayes.upper)
        and a.bayes.upper != b.bayes.upper
        for a, b in zip(base, custom)
    )


class RecordingEngine:
    def __init__(self):
        self.orders = []
        self.cancel_all_calls = 0

    def send_order(self, strategy, direction, offset, price, volume, stop, lock, net):
        self.orders.append({"price": price, "volume": volume, "offset": offset})
        return [str(len(self.orders))]

    def cancel_all(self, strategy):
        self.cancel_all_calls += 1


def _strategy(monkeypatch, setting=None):
    monkeypatch.setattr(
        BaseCtaStrategy, "_fill_optimized_params", lambda self, setting, vt_symbol: None
    )
    engine = RecordingEngine()
    strategy = BayesianQStrategy(
        engine, "test15", "rb2701.SHFE", setting or {"model": "nqqe", "fixed_size": 1}
    )
    strategy.trading = True
    return strategy, engine


def _minute_bar(dt, close=100.0):
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData

    return BarData(
        symbol="rb2701", exchange=Exchange.SHFE, datetime=dt,
        interval=Interval.MINUTE, gateway_name="TEST", open_price=close,
        high_price=close + 1, low_price=close - 1, close_price=close,
        volume=1, turnover=100, open_interest=1,
    )


def test_fifteen_minute_completion_and_default_hour_compatibility(monkeypatch):
    strategy, _ = _strategy(monkeypatch, {"model": "nqqe", "signal_minutes": 15})
    calls = []
    calculator = BayesianQCalculator()

    class Spy:
        def update(self, bar):
            calls.append(bar)
            return calculator.update(bar)

    strategy.calculator = Spy()
    start = datetime(2026, 5, 6, 9, 0, tzinfo=timezone.utc)
    bars = [_minute_bar(start + timedelta(minutes=i), 100 + i) for i in range(30)]

    for bar in bars[:14]:
        strategy.on_bar(bar)
    assert calls == []
    strategy.on_bar(bars[14])
    assert len(calls) == 1
    assert calls[0].datetime == start
    strategy.on_bar(bars[29])
    assert len(calls) == 2
    assert len(strategy.audit_records) == 2

    hourly, _ = _strategy(monkeypatch)
    hourly_calls = []
    hourly.calculator = type("Stub", (), {
        "update": lambda self, bar: hourly_calls.append(bar)
    })()
    assert hourly.signal_minutes == 60
    assert hourly.bg.window == 60
    assert callable(hourly.on_60min_bar)


def test_frozen_indicator_settings_cannot_be_overridden(monkeypatch):
    strategy, _ = _strategy(monkeypatch, {
        "model": "nqqe", "signal_minutes": 15, "rsi_period": 10,
        "rsi_smoothing": 3, "bb_period": 14,
    })
    assert strategy.signal_minutes == 15
    assert strategy.calculator._nqqe.rsi_period == 10
    assert strategy.calculator._nqqe.rsi_smoothing == 3
    assert strategy.calculator._bayes.period == 14


def test_param_grid_is_exactly_frozen():
    assert set(PARAM_SETS) == set(EXPECTED_PARAM_SETS)
    assert {name: dict(values) for name, values in PARAM_SETS.items()} == EXPECTED_PARAM_SETS
    assert MODELS == ("nqqe", "bayes_q_legacy", "bayes_q_fixed")


def _validation_rows():
    rows = []
    for root in ("a", "b", "c"):
        for param_set in PARAM_SETS:
            for model in MODELS:
                rows.append({
                    "root": root,
                    "model": model,
                    "param_set": param_set,
                    "period": "validation",
                    "slippage_ticks": 1,
                    "total_net_pnl": 1.0,
                    "sharpe_ratio": 1.0,
                    "open_entries": 10 if model == "nqqe" else 2,
                })
    return rows


def test_selection_is_structurally_validation_only_and_review_cannot_change_it():
    rows = _validation_rows()
    selected = select_parameters(rows, "bayes_q_legacy")
    assert selected["param_set"] == "default"
    assert selected["validation_rows_seen"] == 36
    assert selected["n_roots"] == 3
    assert selected["required_active_roots"] == 2

    changed = []
    for row in rows:
        for period in ("train", "review"):
            extreme = dict(row, period=period, total_net_pnl=1e12, sharpe_ratio=1e12)
            changed.append(extreme)
    assert select_parameters(rows + changed, "bayes_q_legacy") == selected


def test_selection_orders_by_sharpe_pnl_breadth_then_lexical():
    rows = _validation_rows()
    for row in rows:
        if row["model"] == "nqqe":
            row.update(total_net_pnl=0.0, sharpe_ratio=0.0)
        elif row["param_set"] == "fast":
            row.update(total_net_pnl=3.0, sharpe_ratio=2.0)
        elif row["param_set"] == "slow":
            row.update(total_net_pnl=3.0, sharpe_ratio=2.0)
    selected = select_parameters(rows, "bayes_q_fixed")
    assert selected["param_set"] == "fast"
    assert selected["improved_roots"] == 3
    assert len(selected["combinations"]) == 4


def test_no_eligible_combination_returns_none():
    rows = _validation_rows()
    for row in rows:
        if row["model"] != "nqqe":
            row["open_entries"] = 0
    assert select_parameters(rows, "bayes_q_legacy") is None


def test_two_tick_batch_rejects_more_than_one_param_set():
    from scripts.bayesian_q_parameter_research import run_batch

    with pytest.raises(ValueError, match="唯一 param_set"):
        run_batch([], 2, ("fast", "slow"))


def test_timeframe_comparison_uses_only_same_root_intersection():
    from scripts.bayesian_q_parameter_analysis import compare_same_roots

    selected = {"bayes_q_legacy": {"param_set": "fast"}, "bayes_q_fixed": None}
    fifteen_rows = []
    hourly_rows = []
    for period in ("validation", "review"):
        for cost in (1, 2):
            for root, pnl, sharpe in (("a", 999.0, 9.0), ("b", 20.0, 2.0)):
                fifteen_rows.append({
                    "root": root, "model": "bayes_q_legacy", "param_set": "fast",
                    "period": period, "slippage_ticks": cost,
                    "total_net_pnl": pnl, "sharpe_ratio": sharpe,
                    "max_ddpercent": -1.0,
                })
            for root, pnl, sharpe in (("b", 10.0, 1.0), ("c", -999.0, -9.0)):
                hourly_rows.append({
                    "root": root, "model": "bayes_q_legacy", "period": period,
                    "slippage_ticks": cost, "total_net_pnl": pnl,
                    "sharpe_ratio": sharpe, "max_ddpercent": -2.0,
                })
    result = compare_same_roots(
        pd.DataFrame(fifteen_rows), pd.DataFrame(hourly_rows), selected
    )

    assert len(result) == 4
    assert set(result["n_roots"]) == {1}
    assert set(result["15m_roots"]) == {2}
    assert set(result["1h_roots"]) == {2}
    validation = result[
        result["period"].eq("validation") & result["slippage_ticks"].eq(1)
    ].iloc[0]
    assert validation["15m_median_net_pnl"] == 20
    assert validation["1h_median_net_pnl"] == 10
    assert validation["median_sharpe_delta"] == 1


def test_validation_improvement_alone_cannot_pass_robust_review_decision():
    from scripts.bayesian_q_parameter_analysis import decide_robust_better

    selected = {"bayes_q_legacy": {"param_set": "fast"}, "bayes_q_fixed": None}
    gates = pd.DataFrame([{
        "model": "bayes_q_legacy", "slippage_ticks": 1,
        "double_cost_pass": False, "candidate": True,
        "double_cost_candidate": False,
    }])
    comparisons = pd.DataFrame([{
        "model": "bayes_q_legacy", "period": "validation", "slippage_ticks": 1,
        "validation_better_than_1h": True,
    }])
    outcome = decide_robust_better(selected, gates, comparisons)

    assert outcome["bayes_q_legacy"]["robust_better"] is False
    assert outcome["bayes_q_legacy"]["conditions"] == {
        "review_filter_and_double_cost_pass": False,
        "validation_pnl_and_sharpe_better_than_1h": True,
        "review_candidate_breadth_positive_pnl_sharpe": True,
    }
