#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
朴素动量基线策略

过去 momentum_window 根 15 分钟K线收益为正则持多 1 手，为负则持空 1 手，
始终在市中。用作逻辑回归方向策略的对照基线：如果机器学习模型不能稳定
跑赢这条最朴素的方向规则，复杂度就没有带来价值。
"""

from typing import ClassVar

from core.strategies.base_strategy import BaseCtaStrategy
from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class MomentumBaselineStrategy(BaseCtaStrategy):
    """N 根K线动量符号定方向，固定 1 手。"""

    momentum_window = 21
    fixed_size = 1

    momentum_ret = 0.0
    target_pos = 0

    parameters: ClassVar = [
        "momentum_window",
        "fixed_size",
    ]
    variables: ClassVar = [
        "momentum_ret",
        "target_pos",
    ]

    def on_init(self) -> None:
        super().on_init()
        self.bg = BarGenerator(self.on_bar, 15, self.on_15min_bar)
        self.closes: list[float] = []
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
        self.closes.append(float(bar.close_price))
        if len(self.closes) <= self.momentum_window:
            return

        if self.first_signal_datetime is None:
            self.first_signal_datetime = getattr(bar, "datetime", None)

        base = self.closes[-1 - self.momentum_window]
        self.momentum_ret = bar.close_price / base - 1.0 if base > 0 else 0.0
        target = self.fixed_size if self.momentum_ret > 0 else -self.fixed_size
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
