#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nQQE 快慢线、趋势颜色与交叉副图。"""

from __future__ import annotations

import math
from typing import Any

import pyqtgraph as pg

from vnpy.chart.item import ChartItem
from vnpy.chart.manager import BarManager
from vnpy.trader.object import BarData
from vnpy.trader.ui import QtCore, QtGui, QtWidgets

from .calculators.nqqe_calculator import NqqeCalculator, NqqeState
from .indicator_base import ConfigurableIndicator
from .market_colors import MARKET_DOWN_RGB, MARKET_UP_RGB


class NqqeItem(ChartItem, ConfigurableIndicator):
    """所有指标数值只来自 reviewed NqqeCalculator。"""

    def __init__(
        self,
        manager: BarManager,
        show_cross_markers: bool = True,
        line_width: int = 2,
    ) -> None:
        super().__init__(manager)
        self.show_cross_markers = show_cross_markers
        self.line_width = line_width
        self.states: list[NqqeState] = []
        self._calculator = NqqeCalculator()
        self._create_pens()

    def _create_pens(self) -> None:
        self.neutral_pen = pg.mkPen(color=(80, 150, 240), width=self.line_width)
        self.up_pen = pg.mkPen(color=MARKET_UP_RGB, width=self.line_width)
        self.down_pen = pg.mkPen(color=MARKET_DOWN_RGB, width=self.line_width)
        self.slow_pen = pg.mkPen(color=(245, 180, 50), width=self.line_width)
        self.reference_pen = pg.mkPen(
            color=(170, 170, 170, 130), width=1, style=QtCore.Qt.DashLine
        )
        self.up_brush = pg.mkBrush(MARKET_UP_RGB)
        self.down_brush = pg.mkBrush(MARKET_DOWN_RGB)

    def _recalculate(self) -> None:
        self.states.clear()
        self._calculator = NqqeCalculator()
        bars = self._manager.get_all_bars()
        for bar in bars:
            self.states.append(self._calculator.update(bar))
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
            self.states.append(self._calculator.update(bar))
            super().update_bar(bar)
            return
        self._recalculate()

    def clear_all(self) -> None:
        self.states.clear()
        self._calculator = NqqeCalculator()
        self._rect_area = None
        super().clear_all()

    def get_y_range(
        self, min_ix: int | None = None, max_ix: int | None = None
    ) -> tuple[float, float]:
        """参考线与可见 QQEF/QQES 的真实极值共同决定范围。"""

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
                value for value in (state.qqef, state.qqes) if math.isfinite(value)
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

    def _draw_cross_marker(
        self, painter: QtGui.QPainter, index: int, value: float, crossover: bool
    ) -> None:
        painter.setPen(self.up_pen if crossover else self.down_pen)
        painter.setBrush(self.up_brush if crossover else self.down_brush)
        painter.drawEllipse(QtCore.QPointF(index, value), 0.32, 0.32)

    @staticmethod
    def _cross_marker_index(index: int) -> int:
        """交叉标记显示在确认K线左侧一根，计算与交易时点不变。"""

        return max(0, index - 1)

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        painter.setPen(self.reference_pen)
        for reference in (60.0, 50.0, 40.0):
            painter.drawLine(
                QtCore.QPointF(ix - 0.5, reference),
                QtCore.QPointF(ix + 0.5, reference),
            )
        if ix >= len(self.states):
            painter.end()
            return picture

        state = self.states[ix]
        if ix > 0:
            previous = self.states[ix - 1]
            if math.isfinite(state.qqef) and math.isfinite(previous.qqef):
                painter.setPen(self._trend_pen(state))
                painter.drawLine(
                    QtCore.QPointF(ix - 1, previous.qqef),
                    QtCore.QPointF(ix, state.qqef),
                )
            if math.isfinite(state.qqes) and math.isfinite(previous.qqes):
                painter.setPen(self.slow_pen)
                painter.drawLine(
                    QtCore.QPointF(ix - 1, previous.qqes),
                    QtCore.QPointF(ix, state.qqes),
                )

        if (
            self.show_cross_markers
            and (state.crossover or state.crossunder)
            and math.isfinite(state.qqef)
        ):
            marker_index = self._cross_marker_index(ix)
            marker_qqef = self.states[marker_index].qqef
            self._draw_cross_marker(
                painter, marker_index, marker_qqef, state.crossover
            )

        painter.end()
        return picture

    @staticmethod
    def _display_value(value: float) -> float | None:
        return value if math.isfinite(value) else None

    def get_current_values(self) -> dict[str, Any]:
        if not self.states or not self.states[-1].ready:
            return {}
        state = self.states[-1]
        previous = self.states[-2].qqef if len(self.states) > 1 else math.nan
        return {
            "value": self._display_value(state.qqef),
            "previous": self._display_value(previous),
            "trend": state.trend,
            "qqef": self._display_value(state.qqef),
            "qqes": self._display_value(state.qqes),
            "crossover": state.crossover,
            "crossunder": state.crossunder,
        }

    def get_info_text(self, ix: int) -> str:
        if ix < 0 or ix >= len(self.states):
            return "nQQE - 数据不足"
        state = self.states[ix]
        if not state.ready:
            return "nQQE - 数据不足"

        def format_value(value: float) -> str:
            return f"{value:.2f}" if math.isfinite(value) else "N/A"

        return "\n".join(
            (
                "nQQE (QQEF / QQES)",
                f"QQEF: {format_value(state.qqef)}",
                f"QQES: {format_value(state.qqes)}",
                f"趋势: {state.trend} (60/40)",
                f"交叉: crossover={state.crossover}, crossunder={state.crossunder}",
                "参考线: 60 / 50 / 40",
            )
        )

    def get_config_dialog(self, parent: QtWidgets.QWidget) -> QtWidgets.QDialog:
        return self.create_config_dialog(
            parent,
            "nQQE 显示配置",
            [
                ("show_cross_markers", "显示交叉标记", "checkbox", self.show_cross_markers),
                ("line_width", "线宽", "spinbox", {"min": 1, "max": 6, "value": self.line_width}),
            ],
        )

    def apply_config(self, config: dict[str, Any]) -> None:
        line_width = int(config.get("line_width", self.line_width))
        if line_width < 1:
            raise ValueError("line_width must be positive")
        self.show_cross_markers = bool(
            config.get("show_cross_markers", self.show_cross_markers)
        )
        self.line_width = line_width
        self._create_pens()
        self._recalculate()

    def get_current_config(self) -> dict[str, Any]:
        return {
            "show_cross_markers": self.show_cross_markers,
            "line_width": self.line_width,
        }

    def _get_default_config(self) -> dict[str, Any]:
        return {"show_cross_markers": True, "line_width": 2}

    def _get_config_help_text(self) -> str:
        return "这里只配置交叉标记和线宽，显示设置不会改变计算结果。"
