import pandas as pd
import pytest

from scripts.lasso_portfolio_optimization import (
    compute_turnover_cost,
    equal_weights,
    select_buffered_holdings,
)


def test_buffer_keeps_old_top100_and_fills_from_best_newcomers():
    scores = pd.Series({"A": 9.0, "B": 8.0, "C": 7.0, "D": 6.0, "E": 5.0})
    amounts = pd.Series(100.0, index=scores.index)
    result = select_buffered_holdings(
        scores, amounts, previous={"C", "E"}, holdings_n=3, exit_rank=4,
    )
    assert result == ["A", "B", "C"]


def test_liquidity_filter_removes_lowest_amount_and_forces_exit():
    scores = pd.Series({"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0})
    amounts = pd.Series({"A": 100.0, "B": 80.0, "C": 10.0, "D": 70.0})
    result = select_buffered_holdings(
        scores, amounts, previous={"C"}, holdings_n=2, exit_rank=4,
        liquidity_pct=0.25,
    )
    assert result == ["A", "B"]


def test_turnover_cost_handles_initial_buy_unchanged_and_partial_switch():
    buy, sell, cost = compute_turnover_cost({}, {"A": 0.5, "B": 0.5})
    assert (buy, sell) == (1.0, 0.0)
    assert cost == pytest.approx(0.00125)

    buy, sell, cost = compute_turnover_cost(
        {"A": 0.5, "B": 0.5}, {"A": 0.5, "B": 0.5},
    )
    assert (buy, sell, cost) == (0.0, 0.0, 0.0)

    buy, sell, cost = compute_turnover_cost(
        {"A": 0.5, "B": 0.5}, {"A": 0.25, "B": 0.5, "C": 0.25},
    )
    assert (buy, sell) == (0.25, 0.25)
    assert cost == pytest.approx(0.25 * 0.00125 + 0.25 * 0.00225)


def test_equal_weights_respects_exposure_cap():
    assert equal_weights(["A", "B"], exposure=0.4) == {"A": 0.2, "B": 0.2}
    assert equal_weights([], exposure=1.0) == {}


import numpy as np

from scripts.lasso_portfolio_optimization import historical_exposure


def test_historical_exposure_caps_leverage_and_excludes_future():
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    signal_date = dates[59]
    low_vol = pd.Series(np.repeat([0.001, -0.001], 40), index=dates)
    high_vol = pd.Series(np.repeat([0.03, -0.03], 40), index=dates)
    returns = {"A": low_vol, "B": high_vol}

    exposure_low, count_low, vol_low = historical_exposure(
        returns, ["A"], signal_date, target_vol=0.12,
    )
    exposure_high, count_high, vol_high = historical_exposure(
        returns, ["B"], signal_date, target_vol=0.12,
    )
    assert count_low == count_high == 60
    assert exposure_low == 1.0
    assert 0 < exposure_high < 1
    assert vol_high > vol_low

    changed = {"A": low_vol.copy(), "B": high_vol.copy()}
    changed["A"].iloc[65:] = 10.0
    changed_exposure, _, _ = historical_exposure(
        changed, ["A"], signal_date, target_vol=0.12,
    )
    assert changed_exposure == exposure_low


def test_historical_exposure_uses_previous_when_observations_are_insufficient():
    dates = pd.date_range("2024-01-01", periods=20, freq="B")
    returns = {"A": pd.Series(0.001, index=dates)}
    exposure, count, annual_vol = historical_exposure(
        returns, ["A"], dates[-1], previous_exposure=0.65,
    )
    assert exposure == 0.65
    assert count == 20
    assert np.isnan(annual_vol)


from scripts.lasso_portfolio_optimization import PortfolioConfig, run_portfolio_backtest


def test_backtest_first_period_only_charges_buy_side():
    dates = pd.to_datetime(["2024-01-01", "2024-02-01"])
    daily = pd.DataFrame([
        {"trade_date": dates[0], "symbol": "A", "lasso_score": 2.0, "hold_ret": 0.10, "amount": 100.0, "is_rebal": True},
        {"trade_date": dates[0], "symbol": "B", "lasso_score": 1.0, "hold_ret": 0.00, "amount": 90.0, "is_rebal": True},
        {"trade_date": dates[1], "symbol": "A", "lasso_score": 2.0, "hold_ret": 0.02, "amount": 100.0, "is_rebal": True},
        {"trade_date": dates[1], "symbol": "B", "lasso_score": 1.0, "hold_ret": 0.01, "amount": 90.0, "is_rebal": True},
    ])
    config = PortfolioConfig(name="test", holdings_n=2, exit_rank=2)
    result = run_portfolio_backtest(daily, {}, config)
    assert result.iloc[0]["gross"] == pytest.approx(0.05)
    assert result.iloc[0]["buy"] == pytest.approx(1.0)
    assert result.iloc[0]["sell"] == pytest.approx(0.0)
    assert result.iloc[0]["cost"] == pytest.approx(0.00125)
    assert result.iloc[1]["cost"] == pytest.approx(0.0)
