"""分位数尾部风险计算与检验测试。"""

from types import SimpleNamespace

import numpy as np
import pytest

from core.indicators.calculators.quantile_risk_calculator import (
    CaviarParameters,
    QuantileRiskCalculator,
    calculate_target_size,
    caviar_var_forecast,
    dynamic_quantile_pvalue,
    ewma_var_forecast,
    fit_caviar_as,
    historical_var_forecast,
    kupiec_pvalue,
    pinball_loss,
    risk_metrics,
)


def test_historical_forecast_uses_only_past_returns() -> None:
    returns = np.array([1.0, -2.0, 0.5, 100.0, 0.2])

    forecasts = historical_var_forecast(returns, window=3, tau=0.05)

    assert np.isnan(forecasts[:3]).all()
    assert forecasts[3] == pytest.approx(-np.quantile(returns[:3], 0.05))
    changed = returns.copy()
    changed[3] = -100.0
    changed_forecasts = historical_var_forecast(changed, window=3, tau=0.05)
    assert changed_forecasts[3] == pytest.approx(forecasts[3])
    assert changed_forecasts[4] != pytest.approx(forecasts[4])


def test_ewma_forecast_does_not_include_current_return() -> None:
    returns = np.array([0.1, 0.2, -0.1, 5.0, 0.2])

    forecasts = ewma_var_forecast(returns, ewma_lambda=0.94, tau=0.05)
    changed = returns.copy()
    changed[3] = -50.0
    changed_forecasts = ewma_var_forecast(changed, ewma_lambda=0.94, tau=0.05)

    assert forecasts[3] == pytest.approx(changed_forecasts[3])
    assert forecasts[4] != pytest.approx(changed_forecasts[4])


def test_caviar_as_separates_positive_and_negative_shocks() -> None:
    params = CaviarParameters(0.0, 0.0, 0.2, 0.5, 0.4)

    forecasts = caviar_var_forecast(np.array([1.0, -1.0, 0.0]), params)

    assert forecasts == pytest.approx([0.4, 0.2, 0.5])


def test_online_caviar_matches_offline_one_step_forecast() -> None:
    returns = np.array([0.2, -0.4, 0.1, -0.3])
    params = CaviarParameters(0.01, 0.8, 0.1, 0.3, 0.25)
    calculator = QuantileRiskCalculator(model="caviar", caviar_params=params)

    states = [
        calculator.update(SimpleNamespace(close_price=100.0, high_price=100.0, low_price=100.0))
    ]
    for value in returns[:-1]:
        states.append(calculator.update(SimpleNamespace(
            close_price=states[-1].close * (1 + value / 100),
            high_price=states[-1].close * (1 + value / 100),
            low_price=states[-1].close * (1 + value / 100),
        )))

    offline = caviar_var_forecast(returns, params)
    assert states[-1].risk == pytest.approx(offline[-1])


def test_fit_caviar_is_deterministic_and_beats_constant_loss() -> None:
    rng = np.random.default_rng(20261112)
    returns = rng.normal(0, 0.5, 500)
    returns[100:130] -= 1.0

    fitted = fit_caviar_as(returns, n_starts=2)
    repeated = fit_caviar_as(returns, n_starts=2)

    assert fitted == repeated
    assert 0 <= fitted.beta1 <= 0.999
    assert fitted.beta2 >= 0 and fitted.beta3 >= 0
    forecasts = caviar_var_forecast(returns, fitted)
    constant = np.full(len(returns), -np.quantile(returns, 0.05))
    assert pinball_loss(returns, -forecasts) <= pinball_loss(returns, -constant)


def test_position_size_can_only_reduce_fixed_two_lot_exposure() -> None:
    assert calculate_target_size(0.5, 0.5) == 2
    assert calculate_target_size(0.5, 2.0) == 1
    assert calculate_target_size(0.5, 0.1) == 2
    assert calculate_target_size(0.5, float("nan")) == 0
    assert calculate_target_size(0.5, 0.0) == 0


def test_kupiec_accepts_exact_expected_breach_count() -> None:
    assert kupiec_pvalue(5, 100, tau=0.05) == pytest.approx(1.0)


def test_risk_metrics_and_dq_return_finite_diagnostics() -> None:
    rng = np.random.default_rng(7)
    returns = rng.normal(0, 1, 300)
    risks = np.full(300, 1.6448536269514722)

    metrics = risk_metrics(returns, risks, tau=0.05)
    dq_p = dynamic_quantile_pvalue(returns, -risks, tau=0.05)

    assert metrics["count"] == 300
    assert 0 <= metrics["breach_rate"] <= 1
    assert 0 <= metrics["kupiec_p"] <= 1
    assert 0 <= metrics["christoffersen_p"] <= 1
    assert np.isfinite(metrics["pinball_loss"])
    assert 0 <= dq_p <= 1
