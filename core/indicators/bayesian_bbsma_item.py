#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bayesian BBSMA 副图 ChartItem。"""

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
from .indicator_base import ConfigurableIndicator
from .market_colors import MARKET_DOWN_RGB, MARKET_UP_RGB


class BayesianBbsmaItem(ChartItem, ConfigurableIndicator):
    """直接消费逐根 BBSMA 计算器，以百分数显示所选公式。"""

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
        self.states: list[BayesianBbsmaState] = []
        self._calculator = self._create_calculator()

        self.up_pen = pg.mkPen(color=MARKET_UP_RGB, width=1.5)
        self.down_pen = pg.mkPen(color=MARKET_DOWN_RGB, width=1.5)
        self.prime_pen = pg.mkPen(color=(60, 130, 245), width=2)
        self.threshold_pen = pg.mkPen(
            color=(180, 180, 180, 150), width=1, style=QtCore.Qt.DashLine
        )
        self.up_brush = pg.mkBrush(MARKET_UP_RGB)
        self.down_brush = pg.mkBrush(MARKET_DOWN_RGB)

    def _create_calculator(self) -> BayesianBbsmaCalculator:
        return BayesianBbsmaCalculator(
            period=self.period,
            lookback=self.lookback,
            stddev_mult=self.stddev_mult,
            lower_threshold=self.lower_threshold,
        )

    def _selected_values(self, state: BayesianBbsmaState) -> tuple[float, float, float]:
        return state.sigma_up_fixed, state.sigma_down_fixed, state.prime_fixed

    def _selected_events(self, state: BayesianBbsmaState) -> tuple[bool, bool]:
        return state.long_fixed, state.short_fixed

    def _recalculate(self) -> None:
        """从 manager 的同一组 bars 重建计算器和全部图片占位。"""

        self.states.clear()
        self._calculator = self._create_calculator()
        bars = self._manager.get_all_bars()
        for bar in bars:
            self.states.append(self._calculator.update(bar))

        self._bar_picutures = {index: None for index in range(len(bars))}
        self._item_picuture = None
        self._rect_area = None
        self.update()

    def update_history(self, history: list[BarData]) -> None:
        """历史替换或内容变化时，不保留旧状态或 QPicture。"""

        self._recalculate()

    def update_bar(self, bar: BarData) -> None:
        """新根走逐根增量；修改既有根时全量回放到同一状态。"""

        index = self._manager.get_index(bar.datetime)
        if index is None:
            return
        if index == len(self.states):
            self.states.append(self._calculator.update(bar))
            super().update_bar(bar)
            return
        self._recalculate()

    def clear_all(self) -> None:
        self.states.clear()
        self._calculator = self._create_calculator()
        self._rect_area = None
        super().clear_all()

    @staticmethod
    def _finite(value: float) -> bool:
        return math.isfinite(value)

    def get_y_range(
        self, min_ix: int | None = None, max_ix: int | None = None
    ) -> tuple[float, float]:
        """按可见窗口计算，保留原始公式的负值与超出 0-100 的值。"""

        if not self.states:
            return (0.0, 100.0)
        if min_ix is None or max_ix is None:
            start, end = 0, len(self.states) - 1
        else:
            start = max(0, int(min_ix))
            end = min(len(self.states) - 1, int(max_ix))
        if end < start:
            return (0.0, 100.0)

        values = [self.lower_threshold * 100.0]
        for state in self.states[start : end + 1]:
            values.extend(
                value * 100.0
                for value in self._selected_values(state)
                if self._finite(value)
            )
        minimum, maximum = min(values), max(values)
        if minimum == maximum:
            padding = max(1.0, abs(minimum) * 0.05)
        else:
            padding = (maximum - minimum) * 0.05
        return (minimum - padding, maximum + padding)

    def boundingRect(self) -> QtCore.QRectF:
        minimum, maximum = self.get_y_range()
        return QtCore.QRectF(0, minimum, len(self.states), maximum - minimum)

    def _draw_event_marker(
        self, painter: QtGui.QPainter, index: int, value: float, long: bool
    ) -> None:
        color_pen = self.up_pen if long else self.down_pen
        painter.setPen(color_pen)
        painter.setBrush(self.up_brush if long else self.down_brush)
        if long:
            points = [
                QtCore.QPointF(index, value + 3.0),
                QtCore.QPointF(index - 0.3, value - 2.0),
                QtCore.QPointF(index + 0.3, value - 2.0),
            ]
        else:
            points = [
                QtCore.QPointF(index, value - 3.0),
                QtCore.QPointF(index - 0.3, value + 2.0),
                QtCore.QPointF(index + 0.3, value + 2.0),
            ]
        painter.drawPolygon(QtGui.QPolygonF(points))

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        painter.setPen(self.threshold_pen)
        threshold = self.lower_threshold * 100.0
        painter.drawLine(
            QtCore.QPointF(ix - 0.5, threshold),
            QtCore.QPointF(ix + 0.5, threshold),
        )
        if ix >= len(self.states):
            painter.end()
            return picture

        state = self.states[ix]
        up, down, prime = self._selected_values(state)
        values = (up * 100.0, down * 100.0, prime * 100.0)
        if ix > 0:
            previous = self._selected_values(self.states[ix - 1])
            previous_values = tuple(value * 100.0 for value in previous)
            for current_value, previous_value, pen in zip(
                values, previous_values, (self.up_pen, self.down_pen, self.prime_pen)
            ):
                if self._finite(current_value) and self._finite(previous_value):
                    painter.setPen(pen)
                    painter.drawLine(
                        QtCore.QPointF(ix - 1, previous_value),
                        QtCore.QPointF(ix, current_value),
                    )

        long, short = self._selected_events(state)
        if (long or short) and self._finite(values[2]):
            self._draw_event_marker(painter, ix, values[2], long)

        painter.end()
        return picture

    @staticmethod
    def _display_value(value: float) -> float | None:
        return value if math.isfinite(value) else None

    def get_current_values(self) -> dict[str, Any]:
        """隐藏副图也直接读取已计算状态，供 AI 使用。"""

        if not self.states or not self.states[-1].ready:
            return {}
        state = self.states[-1]
        up, down, prime = self._selected_values(state)
        previous_prime = math.nan
        if len(self.states) > 1:
            previous_prime = self._selected_values(self.states[-2])[2]
        trend = "neutral"
        if math.isfinite(previous_prime):
            if prime > previous_prime:
                trend = "up"
            elif prime < previous_prime:
                trend = "down"
        long, short = self._selected_events(state)
        return {
            "value": self._display_value(prime * 100.0),
            "previous": self._display_value(previous_prime * 100.0),
            "trend": trend,
            "up": self._display_value(up * 100.0),
            "down": self._display_value(down * 100.0),
            "prime": self._display_value(prime * 100.0),
            "long": long,
            "short": short,
            "lower_threshold": self.lower_threshold * 100.0,
        }

    def get_info_text(self, ix: int) -> str:
        if ix < 0 or ix >= len(self.states) or not self.states[ix].ready:
            return "Bayesian BBSMA - 数据不足"
        state = self.states[ix]
        up, down, prime = self._selected_values(state)

        def format_percent(value: float) -> str:
            return f"{value * 100.0:.2f}%" if math.isfinite(value) else "N/A"

        long, short = self._selected_events(state)
        return "\n".join(
            (
                "Bayesian BBSMA",
                f"Up: {format_percent(up)}",
                f"Down: {format_percent(down)}",
                f"Prime: {format_percent(prime)}",
                f"阈值: {self.lower_threshold * 100.0:.2f}%",
                f"多空事件: long={long}, short={short}",
            )
        )

    def get_config_dialog(self, parent: QtWidgets.QWidget) -> QtWidgets.QDialog:
        return self.create_config_dialog(
            parent,
            "Bayesian BBSMA 配置",
            [
                ("period", "价格周期", "spinbox", {"min": 1, "max": 200, "value": self.period}),
                ("lookback", "事件回望", "spinbox", {"min": 1, "max": 200, "value": self.lookback}),
                ("stddev_mult", "标准差倍数", "doublespinbox", {"min": 0.0, "max": 10.0, "step": 0.1, "value": self.stddev_mult}),
                ("lower_threshold", "Prime 阈值", "doublespinbox", {"min": 0.0, "max": 1.0, "step": 0.01, "value": self.lower_threshold}),
            ],
        )

    def apply_config(self, config: dict[str, Any]) -> None:
        period = int(config.get("period", self.period))
        lookback = int(config.get("lookback", self.lookback))
        stddev_mult = float(config.get("stddev_mult", self.stddev_mult))
        lower_threshold = float(config.get("lower_threshold", self.lower_threshold))
        # 先构造一次以执行计算器的参数校验，再提交配置。
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
        return "Up、Down 与 Prime 使用百分数显示。修改参数后立即重算。"
