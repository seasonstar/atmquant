"""自适应回归信号与分位数尾部风险仓位覆盖策略。"""

from typing import ClassVar

import numpy as np

from core.indicators.calculators.quantile_risk_calculator import (
    CaviarParameters,
    QuantileRiskCalculator,
    calculate_target_size,
)
from core.strategies.adaptive_linear_regression_strategy import (
    AdaptiveLinearRegressionStrategy,
    get_exit_reason,
)
from vnpy_ctastrategy import BarData


class QuantileRiskStrategy(AdaptiveLinearRegressionStrategy):
    """保持原信号方向与退出规则，只在1至2手之间调整风险暴露。"""

    risk_model = "fixed"
    tau = 0.05
    risk_window = 480
    atr_window = 60
    ewma_lambda = 0.94
    reference_risk = 1.0
    base_size = 2
    max_size = 2
    caviar_beta0 = 0.01
    caviar_beta1 = 0.90
    caviar_beta2 = 0.10
    caviar_beta3 = 0.20
    caviar_initial_var = 0.50

    current_risk = 0.0
    current_quantile = 0.0
    target_size = 2

    parameters: ClassVar = AdaptiveLinearRegressionStrategy.parameters + [
        "risk_model",
        "tau",
        "risk_window",
        "atr_window",
        "ewma_lambda",
        "reference_risk",
        "base_size",
        "max_size",
        "caviar_beta0",
        "caviar_beta1",
        "caviar_beta2",
        "caviar_beta3",
        "caviar_initial_var",
    ]
    variables: ClassVar = AdaptiveLinearRegressionStrategy.variables + [
        "current_risk",
        "current_quantile",
        "target_size",
    ]

    def on_init(self) -> None:
        """先建风险状态机，再让父类回放预热K线。"""
        params = CaviarParameters(
            self.caviar_beta0,
            self.caviar_beta1,
            self.caviar_beta2,
            self.caviar_beta3,
            self.caviar_initial_var,
        )
        self.risk_calculator = QuantileRiskCalculator(
            model=self.risk_model if self.risk_model != "fixed" else "historical",
            tau=self.tau,
            window=self.atr_window if self.risk_model == "atr" else self.risk_window,
            ewma_lambda=self.ewma_lambda,
            caviar_params=params,
        )
        self.signal_log = []
        super().on_init()

    def on_15min_bar(self, bar: BarData) -> None:
        """复用原进出场逻辑，持仓中仅调整同方向手数。"""
        self.cancel_all()
        if self.risk_model == "fixed":
            self.current_risk = self.reference_risk
            self.current_quantile = -self.reference_risk
            self.target_size = self.base_size
        else:
            risk_state = self.risk_calculator.update(bar)
            self.current_risk = risk_state.risk or 0.0
            self.current_quantile = risk_state.quantile or 0.0
            self.target_size = calculate_target_size(
                self.reference_risk,
                self.current_risk,
                base_size=self.base_size,
                max_size=self.max_size,
            )

        state = self.calculator.update(bar)
        self.r_squared = state.model.coeff_deter
        self.z_score = state.model.z_metric
        self.duration = state.model.duration
        self.upper_band = state.upper_band or 0.0
        self.lower_band = state.lower_band or 0.0
        bar_datetime = getattr(bar, "datetime", None)
        if state.signal and self.first_signal_datetime is None:
            self.first_signal_datetime = bar_datetime

        if self.pos != 0:
            exit_reason = get_exit_reason(
                int(self.pos), state.close, state.model, self.entry_stop_price
            )
            if exit_reason:
                direction = 1 if self.pos > 0 else -1
                if self.pos > 0:
                    self.sell(state.close * 0.9, abs(self.pos))
                else:
                    self.cover(state.close * 1.1, abs(self.pos))
                if self.trading:
                    self.signal_log.append((bar_datetime, "exit", direction))
                return

            if self.trading and self.risk_model != "fixed" and self.target_size > 0:
                current_size = abs(int(self.pos))
                difference = self.target_size - current_size
                if self.pos > 0 and difference > 0:
                    self.buy(state.close * 1.1, difference)
                elif self.pos > 0 and difference < 0:
                    self.sell(state.close * 0.9, -difference)
                elif self.pos < 0 and difference > 0:
                    self.short(state.close * 0.9, difference)
                elif self.pos < 0 and difference < 0:
                    self.cover(state.close * 1.1, -difference)
            return

        if not state.signal or not np.isfinite(state.atr) or self.target_size < 1:
            return
        self.pending_stop_price = state.signal.stop_loss
        self.entry_signal_price = state.signal.entry
        if state.signal.direction > 0:
            self.buy(state.close * 1.1, self.target_size)
        else:
            self.short(state.close * 0.9, self.target_size)
        if self.trading:
            self.signal_log.append((bar_datetime, "entry", int(state.signal.direction)))
