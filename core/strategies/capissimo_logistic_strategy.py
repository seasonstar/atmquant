#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capissimo《Machine Learning: Logistic Regression (v.3)》CTA 策略转换

Original author: capissimo
Source: https://www.tradingview.com/script/49YIV1jW-Machine-Learning-Logistic-Regression/
License: MPL-2.0（衍生代码遵循同一许可证，保留署名）

信号变更时入场 1 手（含直接反手），持有 holding_period 根 15 分钟K线后
若信号未再变化则退出，信号再次变更前不再入场。
15 分钟收盘决策，下一根 1 分钟K线撮合。
"""

from typing import ClassVar

from core.indicators.calculators.capissimo_logistic_calculator import (
    CapissimoLogisticCalculator,
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


class CapissimoLogisticStrategy(BaseCtaStrategy):
    """capissimo ML 逻辑回归信号执行策略。"""

    lookback = 3
    normalization_lookback = 2
    learning_rate = 0.0009
    iterations = 1000
    filter_type = "None"
    holding_period = 5
    fixed_size = 1

    signal = 0
    scaled_loss = 0.0
    loss = 0.0
    target_pos = 0

    parameters: ClassVar = [
        "lookback",
        "normalization_lookback",
        "learning_rate",
        "iterations",
        "filter_type",
        "holding_period",
        "fixed_size",
    ]
    variables: ClassVar = [
        "signal",
        "scaled_loss",
        "loss",
        "target_pos",
    ]

    def on_init(self) -> None:
        super().on_init()
        self.bg = BarGenerator(self.on_bar, 15, self.on_15min_bar)
        self.calculator = CapissimoLogisticCalculator(
            lookback=self.lookback,
            normalization_lookback=self.normalization_lookback,
            learning_rate=self.learning_rate,
            iterations=self.iterations,
            filter_type=self.filter_type,
            holding_period=self.holding_period,
        )
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
        self.signal = state.signal
        self.loss = state.loss
        self.scaled_loss = state.scaled_loss or 0.0

        if (
            self.first_signal_datetime is None
            and (state.start_long or state.start_short)
        ):
            self.first_signal_datetime = getattr(bar, "datetime", None)

        # 先处理退出（持有期满或反向），再处理新入场；反手同根K线完成
        target = int(self.pos)
        if state.end_long and target > 0:
            target = 0
        if state.end_short and target < 0:
            target = 0
        if state.start_long:
            target = self.fixed_size
        elif state.start_short:
            target = -self.fixed_size
        self.target_pos = target

        # 预热回放与实盘启动的历史K线不允许下单
        if not self.trading:
            return

        delta = target - int(self.pos)
        if delta > 0:
            self.buy(bar.close_price * 1.1, delta)
        elif delta < 0:
            self.sell(bar.close_price * 0.9, -delta)

    def on_order(self, order: OrderData) -> None:
        super().on_order(order)

    def on_trade(self, trade: TradeData) -> None:
        super().on_trade(trade)

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
