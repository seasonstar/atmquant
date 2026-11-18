#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bayesian BBSMA/nQQE CTA 策略。

许可证与第三方署名见项目根目录 NOTICE（MPL-2.0）。
信号只在选定周期完成后产生，订单由后续一分钟 K 线撮合。事件 0
保持当前仓位，反手只发送目标仓位与当前仓位之间的差额订单。
"""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any

from vnpy.trader.object import BarData
from vnpy.trader.utility import BarGenerator

from core.indicators.calculators.bayesian_q_calculator import (
    MODEL_NAMES,
    BayesianQCalculator,
    BayesianQState,
)
from .base_strategy import BaseCtaStrategy


class BayesianQStrategy(BaseCtaStrategy):
    """六个预登记模型共享的固定仓位执行策略。"""

    author = "ATMTrader"

    model = "bayes_q_fixed"
    fixed_size = 1
    signal_minutes = 60
    bb_period = 20
    bb_stddev_mult = 2.5
    bayes_lookback = 20
    lower_threshold = 0.15
    rsi_period = 14
    rsi_smoothing = 5
    atrrsi_multiplier = 4.236

    signal = 0
    target_pos = 0
    first_signal_datetime: datetime | None = None
    last_bar_datetime: datetime | None = None

    parameters = [
        "model", "fixed_size", "signal_minutes", "bb_period", "bb_stddev_mult",
        "bayes_lookback", "lower_threshold", "rsi_period", "rsi_smoothing",
        "atrrsi_multiplier",
    ]
    variables = [
        "signal",
        "target_pos",
        "first_signal_datetime",
        "last_bar_datetime",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        if self.model not in MODEL_NAMES:
            raise ValueError(
                f"unknown Bayesian Q model {self.model!r}; expected one of {MODEL_NAMES}"
            )

        if int(self.signal_minutes) < 1:
            raise ValueError("signal_minutes must be positive")

        self.signal_minutes = int(self.signal_minutes)
        self.bg = BarGenerator(self.on_bar, self.signal_minutes, self.on_signal_bar)
        self.calculator = BayesianQCalculator(
            bb_period=self.bb_period,
            bb_stddev_mult=self.bb_stddev_mult,
            bayes_lookback=self.bayes_lookback,
            lower_threshold=self.lower_threshold,
            rsi_period=self.rsi_period,
            rsi_smoothing=self.rsi_smoothing,
            atrrsi_multiplier=self.atrrsi_multiplier,
        )

        self.signal = 0
        self.target_pos = 0
        self.first_signal_datetime = None
        self.last_bar_datetime = None
        self.audit_records: list[dict[str, Any]] = []

    def on_init(self) -> None:
        """用正式回测前的历史一分钟 K 线预热，此阶段 trading=False。"""

        super().on_init()
        self.load_bar(45)

    def on_bar(self, bar: BarData) -> None:
        """消费一分钟 K 线；仅完整六十分钟窗口触发小时信号。"""

        self.last_bar_datetime = bar.datetime
        self.bg.update_bar(bar)

    def _model_ready(self, state: BayesianQState) -> bool:
        """只要求当前模型实际依赖的数据就绪，不拖延独立 SMA 基线。"""

        if self.model in ("bayes_legacy", "bayes_fixed"):
            return state.bayes.ready
        if self.model == "nqqe":
            return state.nqqe.ready
        if self.model in ("bayes_q_legacy", "bayes_q_fixed"):
            return state.bayes.ready and state.nqqe.ready
        return not math.isnan(state.bayes.sma)

    def _append_audit_record(self, bar: BarData, state: BayesianQState, ready: bool) -> None:
        """保存当根六模型原始事件及后续公式/事件审计所需字段。"""

        record = {
            "datetime": bar.datetime,
            "model": self.model,
            "signal": self.signal,
            "target_pos": self.target_pos,
            "pos": self.pos,
            "close_price": float(bar.close_price),
            "model_ready": ready,
            "sma": state.bayes.sma,
            "basis": state.bayes.basis,
            "upper": state.bayes.upper,
            "sigma_up_legacy": state.bayes.sigma_up_legacy,
            "sigma_down_legacy": state.bayes.sigma_down_legacy,
            "prime_legacy": state.bayes.prime_legacy,
            "sigma_up_fixed": state.bayes.sigma_up_fixed,
            "sigma_down_fixed": state.bayes.sigma_down_fixed,
            "prime_fixed": state.bayes.prime_fixed,
            "bayes_ready": state.bayes.ready,
            "rsi": state.nqqe.rsi,
            "qqef": state.nqqe.qqef,
            "qqes": state.nqqe.qqes,
            "nqqe_ready": state.nqqe.ready,
            "nqqe_trend": state.nqqe.trend,
        }
        record.update(state.signals)
        self.audit_records.append(record)

    def on_signal_bar(self, bar: BarData) -> None:
        """更新组合计算器，并用 buy/sell 差额单执行当前模型事件。"""

        self.cancel_all()
        state = self.calculator.update(bar)
        ready = self._model_ready(state)
        self.signal = state.signals[self.model] if ready else 0

        if self.signal > 0:
            self.target_pos = self.fixed_size
        elif self.signal < 0:
            self.target_pos = -self.fixed_size
        else:
            self.target_pos = self.pos

        if self.signal and self.first_signal_datetime is None:
            self.first_signal_datetime = bar.datetime

        self._append_audit_record(bar, state, ready)

        # CtaTemplate 也会检查 trading；此处显式阻断预热和未启动阶段的下单调用。
        if not self.trading:
            return

        delta = self.target_pos - self.pos
        if delta > 0:
            self.buy(bar.close_price, abs(delta))
        elif delta < 0:
            self.sell(bar.close_price, abs(delta))

    def on_60min_bar(self, bar: BarData) -> None:
        """兼容既有直接调用方；实际周期由 ``signal_minutes`` 决定。"""

        self.on_signal_bar(bar)
