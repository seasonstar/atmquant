#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
随机森林方向概率 CTA 策略（日线）

日K线收盘后更新滚动方向模型，输出未来 label_horizon 个交易日的上涨概率。
概率偏离 0.5 超过阈值才入场，偏离越大仓位越大（概率定仓位），回到中性区间
则空仓——与逻辑回归方向策略（策略06）同一套执行语义，唯一差异是模型类。
目标仓位与当前仓位不一致时，下一交易日开盘撮合差额。

预热回放与实盘启动阶段的历史K线只允许训练，不允许下单（trading 开关）。
"""

from typing import ClassVar

from core.indicators.calculators.random_forest_direction_calculator import (
    RandomForestDirectionCalculator,
)
from core.strategies.base_strategy import BaseCtaStrategy
from core.strategies.momentum_baseline_strategy import MomentumBaselineStrategy
from vnpy_ctastrategy import (
    BarData,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class RandomForestDirectionStrategy(BaseCtaStrategy):
    """随机森林/逻辑回归概率阈值入场 + 概率分档定仓位（日线）。"""

    model_kind = "random_forest"
    train_window = 750
    label_horizon = 5
    retrain_interval = 21
    prob_threshold = 0.05
    max_size = 2

    prob_up = 0.0
    target_pos = 0
    model_ready = False
    train_count = 0

    parameters: ClassVar = [
        "model_kind",
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
        self.calculator = RandomForestDirectionCalculator(
            model_kind=self.model_kind,
            train_window=self.train_window,
            label_horizon=self.label_horizon,
            retrain_interval=self.retrain_interval,
        )
        self.first_signal_datetime = None
        self.last_bar_datetime = None
        self.load_bar(90)

    def on_tick(self, tick: TickData) -> None:
        pass  # 日线策略不消费 tick

    def on_bar(self, bar: BarData) -> None:
        self.last_bar_datetime = bar.datetime
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

        # 预热回放与实盘启动阶段的历史K线只允许训练，不允许下单
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


class MomentumBaselineDailyStrategy(MomentumBaselineStrategy):
    """06 同款朴素动量基线的日线版。

    动量规则、仓位与下单语义完全复用 MomentumBaselineStrategy（21日动量符号、
    固定1手、始终在场）；父类按 15 分钟 BarGenerator 合成K线，日线回测直接把
    日K线送进窗口回调，故只覆盖K线管道，不动量逻辑零改动。
    """

    def on_init(self) -> None:
        super(MomentumBaselineStrategy, self).on_init()
        self.closes: list[float] = []
        self.first_signal_datetime = None
        self.last_bar_datetime = None
        self.load_bar(45)

    def on_tick(self, tick: TickData) -> None:
        pass

    def on_bar(self, bar: BarData) -> None:
        self.last_bar_datetime = bar.datetime
        self.on_15min_bar(bar)
