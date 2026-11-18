#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逻辑回归方向概率 CTA 策略

15 分钟K线收盘后更新滚动逻辑回归模型，输出未来 label_horizon 根K线的
上涨概率。概率偏离 0.5 超过阈值才入场，偏离越大仓位越大（概率定仓位），
回到中性区间则空仓。目标仓位与当前仓位不一致时，下一根 1 分钟K线撮合差额。
"""

from typing import ClassVar

from core.indicators.calculators.logistic_direction_calculator import (
    LogisticDirectionCalculator,
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


class LogisticDirectionStrategy(BaseCtaStrategy):
    """逻辑回归概率阈值入场 + 概率分档定仓位。"""

    train_window = 480
    label_horizon = 4
    retrain_interval = 21
    prob_threshold = 0.05
    max_size = 2

    prob_up = 0.0
    target_pos = 0
    model_ready = False
    train_count = 0

    parameters: ClassVar = [
        "train_window",
        "label_horizon",
        "retrain_interval",
        "prob_threshold",
        "max_size",
    ]
    variables: ClassVar = [
        "prob_up",
        "target_pos",
        "model_ready",
        "train_count",
    ]

    def on_init(self) -> None:
        super().on_init()
        self.bg = BarGenerator(self.on_bar, 15, self.on_15min_bar)
        self.calculator = LogisticDirectionCalculator(
            train_window=self.train_window,
            label_horizon=self.label_horizon,
            retrain_interval=self.retrain_interval,
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
        self.model_ready = state.model_ready
        self.train_count = state.train_count

        if state.prob_up is None:
            return

        self.prob_up = state.prob_up
        if self.first_signal_datetime is None:
            self.first_signal_datetime = getattr(bar, "datetime", None)

        # 概率偏离 0.5 超过阈值才持仓，偏离超过两倍阈值加仓到 max_size
        edge = state.prob_up - 0.5
        threshold = self.prob_threshold
        if edge > threshold:
            target = self.max_size if edge > 2 * threshold else 1
        elif edge < -threshold:
            target = -self.max_size if edge < -2 * threshold else -1
        else:
            target = 0
        self.target_pos = target

        # 预热回放与实盘启动的历史K线只允许训练，不允许下单
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
