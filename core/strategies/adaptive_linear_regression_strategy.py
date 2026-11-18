"""Adaptive Linear Regression Structure CTA策略。

Original author: MarkitTick
Source: https://www.tradingview.com/script/a5wesPir-Adaptive-Linear-Regression-Structure-MarkitTick/
License: CC BY-NC-SA 4.0
"""

from typing import ClassVar

import numpy as np

from core.indicators.calculators.adaptive_linear_regression_calculator import (
    AdaptiveLinearRegressionCalculator,
    StatisticalModel,
)
from core.strategies.base_strategy import BaseCtaStrategy
from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


def get_exit_reason(
    position: int,
    close_price: float,
    model: StatisticalModel,
    stop_price: float,
) -> str | None:
    """初始止损始终有效，动态中轨只在模型有效时提供止盈。"""
    if position > 0:
        if close_price <= stop_price:
            return "stop"
        if model.is_valid and close_price >= model.current_est:
            return "take_profit"
    elif position < 0:
        if close_price >= stop_price:
            return "stop"
        if model.is_valid and close_price <= model.current_est:
            return "take_profit"
    return None


class AdaptiveLinearRegressionStrategy(BaseCtaStrategy):
    """将自适应回归通道的收盘穿越信号转换为固定手数交易。"""

    scan_horizon = 20
    deviation_factor = 2.0
    structural_sensitivity = 5
    quality_threshold = 0.5
    fixed_size = 1

    r_squared = 0.0
    z_score = 0.0
    duration = 0
    upper_band = 0.0
    lower_band = 0.0

    parameters: ClassVar = [
        "scan_horizon",
        "deviation_factor",
        "structural_sensitivity",
        "quality_threshold",
        "fixed_size",
    ]
    variables: ClassVar = [
        "r_squared",
        "z_score",
        "duration",
        "upper_band",
        "lower_band",
    ]

    def on_init(self) -> None:
        super().on_init()
        self.bg = BarGenerator(self.on_bar, 15, self.on_15min_bar)
        self.calculator = AdaptiveLinearRegressionCalculator(
            scan_horizon=self.scan_horizon,
            deviation_factor=self.deviation_factor,
            structural_sensitivity=self.structural_sensitivity,
            quality_threshold=self.quality_threshold,
        )
        self.pending_stop_price = 0.0
        self.entry_stop_price = 0.0
        self.entry_signal_price = 0.0
        self.entry_actual_price = 0.0
        self.first_signal_datetime = None
        self.last_bar_datetime = None
        self.load_bar(45)

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.last_bar_datetime = bar.datetime
        self.bg.update_bar(bar)

    def on_15min_bar(self, bar: BarData) -> None:
        self.cancel_all()
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
                if self.pos > 0:
                    self.sell(state.close * 0.9, abs(self.pos))
                else:
                    self.cover(state.close * 1.1, abs(self.pos))
            return

        if not state.signal or not np.isfinite(state.atr):
            return

        self.pending_stop_price = state.signal.stop_loss
        self.entry_signal_price = state.signal.entry
        if state.signal.direction > 0:
            self.buy(state.close * 1.1, self.fixed_size)
        else:
            self.short(state.close * 0.9, self.fixed_size)

    def on_order(self, order: OrderData) -> None:
        """批量回测不需要逐笔委托日志。"""

    def on_trade(self, trade: TradeData) -> None:
        if self.pos != 0 and self.entry_stop_price == 0:
            self.entry_stop_price = self.pending_stop_price
            self.entry_actual_price = trade.price
        elif self.pos == 0:
            self.pending_stop_price = 0.0
            self.entry_stop_price = 0.0
            self.entry_signal_price = 0.0
            self.entry_actual_price = 0.0

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """当前研究只使用限价委托。"""
