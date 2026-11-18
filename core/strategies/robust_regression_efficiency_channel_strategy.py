"""稳健回归效率通道的趋势突破CTA策略。"""

from typing import ClassVar

import numpy as np

from core.indicators.calculators.robust_regression_efficiency_channel_calculator import (
    RobustRegressionEfficiencyCalculator,
    get_breakout_direction,
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


def get_tightened_atr_stop(
    position: int,
    current_stop: float,
    extreme_close: float,
    atr: float,
    atr_multiplier: float,
) -> float:
    """多头止损只上移，空头止损只下移。"""
    if position > 0:
        return max(current_stop, extreme_close - atr_multiplier * atr)
    return min(current_stop, extreme_close + atr_multiplier * atr)


def get_robust_exit_reason(
    position: int,
    close_price: float,
    slope: float,
    stop_price: float,
) -> str | None:
    """ATR止损优先，斜率反向其次，不设置中轨止盈。"""
    if position > 0:
        if close_price <= stop_price:
            return "stop"
        if slope < 0:
            return "slope_reversal"
    elif position < 0:
        if close_price >= stop_price:
            return "stop"
        if slope > 0:
            return "slope_reversal"
    return None


class RobustRegressionEfficiencyChannelStrategy(BaseCtaStrategy):
    """稳健通道突破入场，ATR移动止损与斜率反向退出。"""

    window = 40
    deviation_factor = 2.0
    er_threshold = 0.3
    atr_multiplier = 2.0
    fixed_size = 1

    slope = 0.0
    efficiency_ratio = 0.0
    atr = 0.0
    upper_band = 0.0
    lower_band = 0.0

    parameters: ClassVar = [
        "window",
        "deviation_factor",
        "er_threshold",
        "atr_multiplier",
        "fixed_size",
    ]
    variables: ClassVar = [
        "slope",
        "efficiency_ratio",
        "atr",
        "upper_band",
        "lower_band",
    ]

    def on_init(self) -> None:
        super().on_init()
        self.bg = BarGenerator(self.on_bar, 15, self.on_15min_bar)
        self.calculator = RobustRegressionEfficiencyCalculator(
            window=self.window,
            deviation_factor=self.deviation_factor,
            er_threshold=self.er_threshold,
        )
        self.pending_atr = 0.0
        self.pending_extreme_close = 0.0
        self.entry_stop_price = 0.0
        self.extreme_close = 0.0
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
        self.slope = state.slope
        self.efficiency_ratio = state.efficiency_ratio
        self.atr = state.atr
        self.upper_band = state.upper_band
        self.lower_band = state.lower_band

        direction = get_breakout_direction(state, self.er_threshold)
        bar_datetime = getattr(bar, "datetime", None)
        if direction and self.first_signal_datetime is None:
            self.first_signal_datetime = bar_datetime

        if self.pos != 0:
            if self.pos > 0:
                self.extreme_close = max(self.extreme_close, state.close)
            else:
                self.extreme_close = min(self.extreme_close, state.close)
            if np.isfinite(state.atr):
                self.entry_stop_price = get_tightened_atr_stop(
                    int(self.pos),
                    self.entry_stop_price,
                    self.extreme_close,
                    state.atr,
                    self.atr_multiplier,
                )
            exit_reason = get_robust_exit_reason(
                int(self.pos), state.close, state.slope, self.entry_stop_price
            )
            if exit_reason:
                if self.pos > 0:
                    self.sell(state.close * 0.9, abs(self.pos))
                else:
                    self.cover(state.close * 1.1, abs(self.pos))
            return

        if not direction or not np.isfinite(state.atr):
            return
        self.pending_atr = state.atr
        self.pending_extreme_close = state.close
        if direction > 0:
            self.buy(state.close * 1.1, self.fixed_size)
        else:
            self.short(state.close * 0.9, self.fixed_size)

    def on_order(self, order: OrderData) -> None:
        """批量研究不输出逐笔委托日志。"""

    def on_trade(self, trade: TradeData) -> None:
        if self.pos != 0 and self.entry_stop_price == 0:
            direction = 1 if self.pos > 0 else -1
            self.entry_stop_price = (
                trade.price - direction * self.atr_multiplier * self.pending_atr
            )
            self.extreme_close = self.pending_extreme_close
        elif self.pos == 0:
            self.pending_atr = 0.0
            self.pending_extreme_close = 0.0
            self.entry_stop_price = 0.0
            self.extreme_close = 0.0

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """当前研究只使用限价委托。"""
