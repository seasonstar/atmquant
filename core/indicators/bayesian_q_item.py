#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bayesian Q 组合副图：nQQE、sigma 方向背景与已接受信号。"""

from __future__ import annotations

import math
from typing import Any

import pyqtgraph as pg

from vnpy.chart.item import ChartItem
from vnpy.chart.manager import BarManager
from vnpy.trader.object import BarData
from vnpy.trader.ui import QtCore, QtGui, QtWidgets

from .calculators.bayesian_bbsma_calculator import (
    BayesianBbsmaCalculator,
    BayesianBbsmaState,
)
from .calculators.bayesian_q_calculator import BayesianQState, calculate_signals
from .calculators.nqqe_calculator import NqqeCalculator, NqqeState
from .indicator_base import ConfigurableIndicator
from .market_colors import MARKET_DOWN_RGB, MARKET_UP_RGB


class BayesianQItem(ChartItem, ConfigurableIndicator):
    """组合两个 reviewed 逐根计算器及 reviewed 信号映射，不另写指标公式。"""

    def __init__(
        self,
        manager: BarManager,
        period: int = 20,
        lookback: int = 20,
        stddev_mult: float = 2.5,
        lower_threshold: float = 0.15,
    ) -> None:
        super().__init__(manager)
        self.period = period
        self.lookback = lookback
        self.stddev_mult = stddev_mult
        self.lower_threshold = lower_threshold
        self.states: list[BayesianQState] = []
        self._create_calculators()

        self.neutral_pen = pg.mkPen(color=(80, 150, 240), width=2)
        self.up_pen = pg.mkPen(color=MARKET_UP_RGB, width=2)
        self.down_pen = pg.mkPen(color=MARKET_DOWN_RGB, width=2)
        self.slow_pen = pg.mkPen(color=(245, 180, 50), width=2)
        self.reference_pen = pg.mkPen(
            color=(170, 170, 170, 130), width=1, style=QtCore.Qt.DashLine
        )
        self.up_brush = pg.mkBrush(MARKET_UP_RGB)
        self.down_brush = pg.mkBrush(MARKET_DOWN_RGB)
        self.up_background = pg.mkBrush((*MARKET_UP_RGB, 32))
        self.down_background = pg.mkBrush((*MARKET_DOWN_RGB, 32))

    def _create_calculators(self) -> None:
        self._bayes_calculator = BayesianBbsmaCalculator(
            period=self.period,
            lookback=self.lookback,
            stddev_mult=self.stddev_mult,
            lower_threshold=self.lower_threshold,
        )
        self._nqqe_calculator = NqqeCalculator()

    def _selected_sigmas(self, state: BayesianBbsmaState) -> tuple[float, float]:
        return state.sigma_up_fixed, state.sigma_down_fixed

    def _direction(self, state: BayesianQState) -> str:
        up, down = self._selected_sigmas(state.bayes)
        if not math.isfinite(up) or not math.isfinite(down) or up == down:
            return "neutral"
        return "up" if up > down else "down"

    def _accepted_signal(self, state: BayesianQState) -> int:
        return state.signals["bayes_q_fixed"]

    def _recalculate(self) -> None:
        self.states.clear()
        self._create_calculators()
        bars = self._manager.get_all_bars()
        for bar in bars:
            bayes = self._bayes_calculator.update(bar)
            nqqe = self._nqqe_calculator.update(bar)
            signals = calculate_signals(float(bar.close_price), bayes, nqqe)
            self.states.append(BayesianQState(bayes=bayes, nqqe=nqqe, signals=signals))
        self._bar_picutures = {index: None for index in range(len(bars))}
        self._item_picuture = None
        self._rect_area = None
        self.update()

    def update_history(self, history: list[BarData]) -> None:
        self._recalculate()

    def update_bar(self, bar: BarData) -> None:
        index = self._manager.get_index(bar.datetime)
        if index is None:
            return
        if index == len(self.states):
            previous_range = self.get_y_range()
            bayes = self._bayes_calculator.update(bar)
            nqqe = self._nqqe_calculator.update(bar)
            signals = calculate_signals(float(bar.close_price), bayes, nqqe)
            self.states.append(BayesianQState(bayes=bayes, nqqe=nqqe, signals=signals))
            if self.get_y_range() != previous_range:
                # 背景矩形高度依赖全历史范围；极值变化时旧根图片也必须失效。
                self._bar_picutures = {
                    picture_index: None for picture_index in range(len(self.states))
                }
                self._item_picuture = None
                self._rect_area = None
                self.update()
            else:
                super().update_bar(bar)
            return
        self._recalculate()

    def clear_all(self) -> None:
        self.states.clear()
        self._create_calculators()
        self._rect_area = None
        super().clear_all()

    def get_y_range(
        self, min_ix: int | None = None, max_ix: int | None = None
    ) -> tuple[float, float]:
        if not self.states:
            return (0.0, 100.0)
        if min_ix is None or max_ix is None:
            start, end = 0, len(self.states) - 1
        else:
            start = max(0, int(min_ix))
            end = min(len(self.states) - 1, int(max_ix))
        if end < start:
            return (0.0, 100.0)

        values = [40.0, 50.0, 60.0]
        for state in self.states[start : end + 1]:
            values.extend(
                value
                for value in (state.nqqe.qqef, state.nqqe.qqes)
                if math.isfinite(value)
            )
        minimum, maximum = min(values), max(values)
        padding = (maximum - minimum) * 0.05 if maximum != minimum else 2.0
        return (minimum - padding, maximum + padding)

    def boundingRect(self) -> QtCore.QRectF:
        minimum, maximum = self.get_y_range()
        return QtCore.QRectF(0, minimum, len(self.states), maximum - minimum)

    def _trend_pen(self, state: NqqeState):
        if state.trend == "up":
            return self.up_pen
        if state.trend == "down":
            return self.down_pen
        return self.neutral_pen

    @staticmethod
    def _cross_marker_index(index: int) -> int:
        """交叉标记显示在确认K线左侧一根，计算与交易时点不变。"""

        return max(0, index - 1)

    def _draw_signal_marker(
        self, painter: QtGui.QPainter, index: int, value: float, signal: int
    ) -> None:
        long = signal > 0
        painter.setPen(self.up_pen if long else self.down_pen)
        painter.setBrush(self.up_brush if long else self.down_brush)
        if long:
            points = [
                QtCore.QPointF(index, value + 4.0),
                QtCore.QPointF(index - 0.35, value + 0.8),
                QtCore.QPointF(index + 0.35, value + 0.8),
            ]
        else:
            points = [
                QtCore.QPointF(index, value - 4.0),
                QtCore.QPointF(index - 0.35, value - 0.8),
                QtCore.QPointF(index + 0.35, value - 0.8),
            ]
        painter.drawPolygon(QtGui.QPolygonF(points))

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        if ix < len(self.states):
            state = self.states[ix]
            direction = self._direction(state)
            if direction != "neutral":
                minimum, maximum = self.get_y_range()
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(
                    self.up_background if direction == "up" else self.down_background
                )
                painter.drawRect(
                    QtCore.QRectF(ix - 0.5, minimum, 1.0, maximum - minimum)
                )

        painter.setPen(self.reference_pen)
        for reference in (60.0, 50.0, 40.0):
            painter.drawLine(
                QtCore.QPointF(ix - 0.5, reference),
                QtCore.QPointF(ix + 0.5, reference),
            )
        if ix >= len(self.states):
            painter.end()
            return picture

        nqqe = state.nqqe
        if ix > 0:
            previous = self.states[ix - 1].nqqe
            if math.isfinite(nqqe.qqef) and math.isfinite(previous.qqef):
                painter.setPen(self._trend_pen(nqqe))
                painter.drawLine(
                    QtCore.QPointF(ix - 1, previous.qqef),
                    QtCore.QPointF(ix, nqqe.qqef),
                )
            if math.isfinite(nqqe.qqes) and math.isfinite(previous.qqes):
                painter.setPen(self.slow_pen)
                painter.drawLine(
                    QtCore.QPointF(ix - 1, previous.qqes),
                    QtCore.QPointF(ix, nqqe.qqes),
                )

        if math.isfinite(nqqe.qqef) and (nqqe.crossover or nqqe.crossunder):
            marker_index = self._cross_marker_index(ix)
            marker_qqef = self.states[marker_index].nqqe.qqef
            if math.isfinite(marker_qqef):
                if nqqe.crossover or nqqe.crossunder:
                    painter.setPen(self.up_pen if nqqe.crossover else self.down_pen)
                    painter.setBrush(self.up_brush if nqqe.crossover else self.down_brush)
                    painter.drawEllipse(QtCore.QPointF(marker_index, marker_qqef), 0.25, 0.25)
                signal = self._accepted_signal(state)
                if signal:
                    self._draw_signal_marker(painter, marker_index, marker_qqef, signal)

        painter.end()
        return picture

    @staticmethod
    def _display_value(value: float) -> float | None:
        return value if math.isfinite(value) else None

    def get_current_values(self) -> dict[str, Any]:
        if not self.states or not self.states[-1].nqqe.ready:
            return {}
        state = self.states[-1]
        previous = self.states[-2].nqqe.qqef if len(self.states) > 1 else math.nan
        sigma_up, sigma_down = self._selected_sigmas(state.bayes)
        return {
            "value": self._display_value(state.nqqe.qqef),
            "previous": self._display_value(previous),
            "trend": state.nqqe.trend,
            "qqef": self._display_value(state.nqqe.qqef),
            "qqes": self._display_value(state.nqqe.qqes),
            "crossover": state.nqqe.crossover,
            "crossunder": state.nqqe.crossunder,
            "sigma_up": self._display_value(sigma_up),
            "sigma_down": self._display_value(sigma_down),
            "direction": self._direction(state),
            "accepted_signal": self._accepted_signal(state),
            "background_is_calibrated_probability": False,
        }

    def get_info_text(self, ix: int) -> str:
        if ix < 0 or ix >= len(self.states):
            return "Bayesian Q - 数据不足"
        state = self.states[ix]
        sigma_up, sigma_down = self._selected_sigmas(state.bayes)

        def format_value(value: float) -> str:
            return f"{value:.4f}" if math.isfinite(value) else "N/A"

        return "\n".join(
            (
                "Bayesian Q",
                f"QQEF: {format_value(state.nqqe.qqef)}",
                f"QQES: {format_value(state.nqqe.qqes)}",
                f"Sigma Up: {format_value(sigma_up)}",
                f"Sigma Down: {format_value(sigma_down)}",
                f"当根方向背景: {self._direction(state)}",
                f"已接受 Bayesian Q 信号: {self._accepted_signal(state)}",
                "半透明背景只表示 sigma 的方向，不是校准概率。",
            )
        )

    def get_config_dialog(self, parent: QtWidgets.QWidget) -> QtWidgets.QDialog:
        return self.create_config_dialog(
            parent,
            "Bayesian Q 配置",
            [
                ("period", "BBSMA 价格周期", "spinbox", {"min": 1, "max": 200, "value": self.period}),
                ("lookback", "BBSMA 事件回望", "spinbox", {"min": 1, "max": 200, "value": self.lookback}),
                ("stddev_mult", "标准差倍数", "doublespinbox", {"min": 0.0, "max": 10.0, "step": 0.1, "value": self.stddev_mult}),
                ("lower_threshold", "BBSMA Prime 阈值", "doublespinbox", {"min": 0.0, "max": 1.0, "step": 0.01, "value": self.lower_threshold}),
            ],
        )

    def apply_config(self, config: dict[str, Any]) -> None:
        period = int(config.get("period", self.period))
        lookback = int(config.get("lookback", self.lookback))
        stddev_mult = float(config.get("stddev_mult", self.stddev_mult))
        lower_threshold = float(config.get("lower_threshold", self.lower_threshold))
        BayesianBbsmaCalculator(
            period=period,
            lookback=lookback,
            stddev_mult=stddev_mult,
            lower_threshold=lower_threshold,
        )
        self.period = period
        self.lookback = lookback
        self.stddev_mult = stddev_mult
        self.lower_threshold = lower_threshold
        self._recalculate()

    def get_current_config(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "lookback": self.lookback,
            "stddev_mult": self.stddev_mult,
            "lower_threshold": self.lower_threshold,
        }

    def _get_default_config(self) -> dict[str, Any]:
        return {
            "period": 20,
            "lookback": 20,
            "stddev_mult": 2.5,
            "lower_threshold": 0.15,
        }

    def _get_config_help_text(self) -> str:
        return "背景表示 sigma 的相对方向，不是校准概率；三角标记表示通过过滤的组合事件。"
