#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版K线图表组件
重构版本 - 使用组件化架构，便于扩展AI分析面板和交易面板
"""

from datetime import datetime, time, timedelta
from typing import List, Optional
from functools import partial

import pyqtgraph as pg

from vnpy.trader.ui import QtCore, QtWidgets
from vnpy.trader.constant import Interval
from vnpy.trader.object import BarData
from vnpy.chart import ChartWidget, CandleItem
from vnpy.chart.base import NORMAL_FONT

# 基础指标
from core.indicators.boll_item import BollItem
from core.indicators.multi_sma_item import MultiSmaItem
from core.indicators.multi_ema_item import MultiEmaItem
from core.indicators.rsi_item import RsiItem
from core.indicators.macd_item import Macd3Item
from core.indicators.dmi_item import DmiItem
from core.indicators.indicator_base import ConfigurableIndicator

# Volume指标
try:
    from core.indicators.enhanced_volume_item import EnhancedVolumeItem
    VolumeItem = EnhancedVolumeItem
    VOLUME_CONFIGURABLE = True
except ImportError:
    from vnpy.chart import VolumeItem
    VOLUME_CONFIGURABLE = False

# 组件导入
from core.charts.components.extendable_viewbox import ExtendableViewBox
from core.charts.components.cursor_manager import CursorManager

# 扩展指标配置
EXTENDED_INDICATORS_CONFIG = {
    "fibonacci": {"module": "fibonacci_entry_bands_item", "class": "FibonacciEntryBandsItem", "type": "main", "default_visible": False, "configurable": True},
    "smart_money": {"module": "smart_money_channels", "class": "SmartMoneyChannelsItem", "type": "main", "default_visible": False, "configurable": True},
    "zlema": {"module": "zlema_item", "class": "ZlemaItem", "type": "main", "default_visible": False, "configurable": True},
    "supertrend": {"module": "supertrend_item", "class": "SupertrendItem", "type": "main", "default_visible": False, "configurable": True},
    "smc": {"module": "smc.smart_money_concept_item", "class": "SmartMoneyConceptItem", "type": "main", "default_visible": False, "configurable": True},
    "harmonic": {"module": "harmonic_pattern_item", "class": "HarmonicPatternItem", "type": "main", "default_visible": False, "configurable": True},
    "kalman": {"module": "kalman_item", "class": "KalmanItem", "type": "main", "default_visible": False, "configurable": True},
    "adaptive_macd": {"module": "adaptive_macd_deluxe_item", "class": "AdaptiveMacdDeluxeItem", "type": "sub", "default_visible": True, "min_height": 120, "max_height": 180, "configurable": True},
    "squeeze": {"module": "squeeze_momentum_item", "class": "SqueezeMomentumItem", "type": "sub", "default_visible": False, "min_height": 100, "max_height": 180, "configurable": True},
    "supertrended_rsi": {"module": "supertrended_rsi_item", "class": "SupertrendedRsiItem", "type": "sub", "default_visible": True, "min_height": 100, "max_height": 180, "configurable": True},
    "wavetrend": {"module": "wavetrend_item", "class": "WaveTrendItem", "type": "sub", "default_visible": False, "min_height": 100, "max_height": 180, "configurable": True},
}

# 动态导入扩展指标
EXTENDED_INDICATORS_CLASSES = {}
for name, cfg in EXTENDED_INDICATORS_CONFIG.items():
    try:
        mod = __import__(f"core.indicators.{cfg['module']}", fromlist=[cfg["class"]])
        EXTENDED_INDICATORS_CLASSES[name] = getattr(mod, cfg["class"])
    except (ImportError, AttributeError):
        pass


class EnhancedChartWidget(ChartWidget):
    """增强版K线图表组件"""

    def __init__(self, parent: QtWidgets.QWidget = None):
        # 指标配置
        self.main_indicators = {
            "boll": [BollItem, "boll", False, True],
            "sma": [MultiSmaItem, "sma", False, True],
            "ema": [MultiEmaItem, "ema", False, True],
        }
        self.sub_indicators = {
            "volume": [VolumeItem, "volume", True, 120, 180, VOLUME_CONFIGURABLE],
            "macd": [Macd3Item, "macd", False, 120, 180, True],
            "rsi": [RsiItem, "rsi", False, 100, 180, True],
            "dmi": [DmiItem, "dmi", False, 100, 180, True],
        }
        
        # 加载扩展指标
        for name, cls in EXTENDED_INDICATORS_CLASSES.items():
            cfg = EXTENDED_INDICATORS_CONFIG[name]
            if cfg["type"] == "main":
                self.main_indicators[name] = [cls, name, cfg["default_visible"], cfg["configurable"]]
            else:
                self.sub_indicators[name] = [cls, name, cfg["default_visible"], cfg["min_height"], cfg["max_height"], cfg["configurable"]]

        # 状态
        self.main_indicator_visibility = {n: c[2] for n, c in self.main_indicators.items()}
        self.sub_indicator_visibility = {n: c[2] for n, c in self.sub_indicators.items()}
        self.original_heights = {}
        self.enlarged_plots = set()
        
        # 周期相关
        self.current_interval = Interval.MINUTE
        self._actual_interval = "1m"
        self.current_symbol = ""
        self.current_exchange = None
        self.base_minute_bars = []
        self.interval_buttons = {}
        self.trading_session = None
        
        # Tick追踪
        self._last_tick_volume = 0
        self._last_tick_volume_for_base = 0
        self.on_interval_changed_callback = None
        
        # 专注模式
        self.focus_mode = None
        self.saved_plot_visibility = {}
        
        # 光标管理器
        self.cursor_manager = None

        # 独立的K线形态指标（不继承ChartItem）
        self.candlestick_patterns = None

        super().__init__(parent)
        self.setWindowTitle("增强版K线图表")
        
        self._init_charts()
        self._create_controls()
        self._create_interval_panel()
        self._setup_double_click_handlers()

    def _init_charts(self):
        """初始化图表"""
        self.add_plot("candle", minimum_height=250, hide_x_axis=True)
        self.add_item(CandleItem, "candle", "candle")
        self._init_price_line()

        for name, (cls, key, visible, _) in self.main_indicators.items():
            self.add_item(cls, key, "candle")
            if not visible:
                self._items[key].hide()

        for name, (cls, key, visible, min_h, max_h, _) in self.sub_indicators.items():
            self.add_plot(name, minimum_height=min_h, maximum_height=max_h, hide_x_axis=True)
            self.add_item(cls, name, key)
            self.original_heights[name] = {"minimum_height": min_h, "maximum_height": max_h}
            if not visible:
                self._plots[name].hide()

        self.add_cursor()
        self._update_xaxis_visibility()
        
        self.cursor_manager = CursorManager(self)
        self.cursor_manager.setup()
        self.cursor_manager.relocate_x_label()

        # 初始化独立的K线形态指标
        self.init_candlestick_patterns()

    def init_candlestick_patterns(self):
        """初始化蜡烛图形态指标"""
        if self.candlestick_patterns is None:
            try:
                from core.indicators.candlestick_patterns_item import CandlestickPatternsItem
                self.candlestick_patterns = CandlestickPatternsItem()
                self.candlestick_patterns.set_chart(self)
            except ImportError:
                pass

    def add_plot(self, plot_name: str, minimum_height: int = 80, maximum_height: int = None, hide_x_axis: bool = False) -> None:
        """重写add_plot使用ExtendableViewBox"""
        viewbox = ExtendableViewBox(self)
        plot = pg.PlotItem(axisItems={"bottom": self._get_new_x_axis()}, viewBox=viewbox, name=plot_name)
        plot.setMenuEnabled(False)
        plot.setClipToView(True)
        plot.hideAxis("left")
        plot.showAxis("right")
        plot.setDownsampling(mode="peak")
        plot.setRange(xRange=(0, 1), yRange=(0, 1))
        plot.hideButtons()
        plot.setMinimumHeight(minimum_height)
        if maximum_height is not None:
            plot.setMaximumHeight(maximum_height)
        if hide_x_axis:
            plot.hideAxis("bottom")
        if not self._first_plot:
            self._first_plot = plot
        view = plot.getViewBox()
        view.sigXRangeChanged.connect(self._update_y_range)
        view.setMouseEnabled(x=True, y=True)
        right_axis = plot.getAxis("right")
        right_axis.setWidth(60)
        right_axis.tickFont = NORMAL_FONT
        if self._plots:
            plot.setXLink(list(self._plots.values())[0])
        self._plots[plot_name] = plot
        self._layout.nextRow()
        self._layout.addItem(plot)

    def _init_price_line(self):
        """初始化价格线"""
        candle_plot = self._plots.get("candle")
        if not candle_plot:
            return
        self.price_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(color=(255, 165, 0), width=1, style=QtCore.Qt.PenStyle.DashLine), movable=False)
        candle_plot.addItem(self.price_line)
        self.price_label = pg.TextItem(anchor=(0, 0.5), color=(255, 165, 0))
        candle_plot.addItem(self.price_label)
        self.price_line.hide()
        self.price_label.hide()

    def _update_price_line(self, price: float):
        """更新价格线"""
        if not hasattr(self, "price_line"):
            return
        self.price_line.setPos(price)
        self.price_label.setText(f" {price:.2f} ")
        candle_plot = self._plots.get("candle")
        if candle_plot:
            vr = candle_plot.getViewBox().viewRange()
            x_pos = vr[0][1] - (vr[0][1] - vr[0][0]) * 0.05
            self.price_label.setPos(x_pos, price)
        self.price_line.show()
        self.price_label.show()


    def _create_controls(self):
        """创建控制面板"""
        self._create_main_indicator_controls()
        self._create_sub_indicator_controls()

    def _create_main_indicator_controls(self):
        """创建主图指标控制"""
        w = QtWidgets.QWidget(self)
        w.setStyleSheet("QWidget { background-color: rgba(30, 30, 30, 128); border-radius: 5px; }")
        layout = QtWidgets.QHBoxLayout(w)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(5)
        layout.addWidget(QtWidgets.QLabel("主图指标："))
        
        self.main_checkboxes = {}
        for name, config in self.main_indicators.items():
            container = QtWidgets.QHBoxLayout()
            container.setContentsMargins(0, 0, 0, 0)
            container.setSpacing(0)
            cb = QtWidgets.QCheckBox()
            cb.setChecked(config[2])
            cb.setFixedSize(16, 16)
            cb.stateChanged.connect(partial(self._toggle_main_indicator, name))
            self.main_checkboxes[name] = cb
            container.addWidget(cb)
            lbl = QtWidgets.QLabel(name)
            lbl.setStyleSheet("QLabel { margin: 0; padding: 0; }")
            container.addWidget(lbl)
            if len(config) > 3 and config[3]:
                btn = QtWidgets.QPushButton("[x]")
                btn.setFixedSize(20, 20)
                btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 12px; }")
                btn.clicked.connect(partial(self._configure_indicator, name, True))
                container.addWidget(btn)
            layout.addLayout(container)
        
        w.adjustSize()
        w.setFixedHeight(30)
        w.move(10, 5)
        self.main_controls_widget = w

        # 手动添加蜡烛图形态指标控制（独立组件，不在 main_indicators 中）
        if self.candlestick_patterns:
            container = QtWidgets.QHBoxLayout()
            container.setContentsMargins(0, 0, 0, 0)
            container.setSpacing(0)
            cb = QtWidgets.QCheckBox()
            cb.setChecked(True)  # 默认启用
            cb.setFixedSize(16, 16)
            cb.stateChanged.connect(self._toggle_candlestick_patterns)
            self.candlestick_patterns_checkbox = cb
            container.addWidget(cb)
            lbl = QtWidgets.QLabel("candlestick_patterns")
            lbl.setStyleSheet("QLabel { margin: 0; padding: 0; }")
            container.addWidget(lbl)
            # 配置按钮
            btn = QtWidgets.QPushButton("[x]")
            btn.setFixedSize(20, 20)
            btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 12px; }")
            btn.clicked.connect(self._configure_candlestick_patterns)
            container.addWidget(btn)
            layout.addLayout(container)
            w.adjustSize()

    def _create_sub_indicator_controls(self):
        """创建副图指标控制"""
        w = QtWidgets.QWidget(self)
        w.setStyleSheet("QWidget { background-color: rgba(30, 30, 30, 128); border-radius: 5px; }")
        layout = QtWidgets.QHBoxLayout(w)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(5)
        layout.addWidget(QtWidgets.QLabel("副图指标："))
        
        self.sub_checkboxes = {}
        for name, config in self.sub_indicators.items():
            container = QtWidgets.QHBoxLayout()
            container.setContentsMargins(0, 0, 0, 0)
            container.setSpacing(0)
            cb = QtWidgets.QCheckBox()
            cb.setChecked(config[2])
            cb.setFixedSize(16, 16)
            cb.stateChanged.connect(partial(self._toggle_sub_indicator, name))
            self.sub_checkboxes[name] = cb
            container.addWidget(cb)
            lbl = QtWidgets.QLabel(name)
            lbl.setStyleSheet("QLabel { margin: 0; padding: 0; }")
            container.addWidget(lbl)
            if len(config) > 5 and config[5]:
                btn = QtWidgets.QPushButton("[x]")
                btn.setFixedSize(20, 20)
                btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 12px; }")
                btn.clicked.connect(partial(self._configure_indicator, name, False))
                container.addWidget(btn)
            layout.addLayout(container)
        
        w.adjustSize()
        w.setFixedHeight(30)
        w.move(10, self.height() - 60)
        self.sub_controls_widget = w
        
        orig_resize = self.resizeEvent
        def resize_handler(event):
            if orig_resize:
                orig_resize(event)
            if hasattr(self, "sub_controls_widget"):
                self.sub_controls_widget.move(10, self.height() - 60)
        self.resizeEvent = resize_handler

    def _toggle_main_indicator(self, name: str, state: int):
        """切换主图指标"""
        if name not in self.main_indicators:
            return
        cls, key, _, _ = self.main_indicators[name]
        checked = state == QtCore.Qt.Checked.value
        
        if checked:
            if key not in self._items:
                self.add_item(cls, key, "candle")
            plot = self._plots["candle"]
            item = self._items[key]
            if item not in plot.items:
                plot.addItem(item)
            item.show()
            history = self._manager.get_all_bars()
            if history:
                item.update_history(history)
                item.update()
        else:
            if key in self._items:
                self._plots["candle"].removeItem(self._items[key])
        
        self.main_indicator_visibility[name] = checked
        self.update()

    def _toggle_sub_indicator(self, name: str, state: int):
        """切换副图指标"""
        if name not in self.sub_indicators:
            return
        cls, key, _, min_h, max_h, _ = self.sub_indicators[name]
        checked = state == QtCore.Qt.Checked.value
        
        if checked:
            if name not in self._plots:
                self.add_plot(name, minimum_height=min_h, maximum_height=max_h)
                self.add_item(cls, name, key)
            self._plots[name].show()
            if key in self._items:
                self._items[key].setVisible(True)
                history = self._manager.get_all_bars()
                if history:
                    self._items[key].update_history(history)
                    self._items[key].update()
        else:
            if name in self._plots:
                self._plots[name].hide()
                if key in self._items:
                    self._items[key].setVisible(False)
        
        self.sub_indicator_visibility[name] = checked
        self._layout.updateGeometry()
        self.update()
        self._update_xaxis_visibility()
        
        if self.cursor_manager:
            self.cursor_manager.setup()
            self.cursor_manager.relocate_x_label()

    def _configure_indicator(self, name: str, is_main: bool):
        """配置指标"""
        key = self.main_indicators[name][1] if is_main else self.sub_indicators[name][1]
        if key not in self._items:
            return
        item = self._items[key]
        if not isinstance(item, ConfigurableIndicator):
            QtWidgets.QMessageBox.information(self, "提示", f"{name} 指标不支持配置")
            return
        dialog = item.get_config_dialog(self)
        orig = item.apply_config
        def wrapped(cfg):
            orig(cfg)
            history = self._manager.get_all_bars()
            if history:
                item.update_history(history)
                item.update()
            self.update()
        item.apply_config = wrapped
        try:
            dialog.exec_()
        finally:
            item.apply_config = orig

    def _toggle_candlestick_patterns(self, state: int):
        """切换蜡烛图形态指标显示"""
        if not self.candlestick_patterns:
            return
        checked = state == QtCore.Qt.Checked.value
        if checked:
            # 重新检测并显示形态
            bars = []
            for ix in range(self._manager.get_count()):
                bars.append(self._manager.get_bar(ix))
            if bars:
                self.candlestick_patterns.on_history_updated(bars)
        else:
            # 清除形态显示
            self.candlestick_patterns.clear_visualization()

    def _configure_candlestick_patterns(self):
        """配置蜡烛图形态指标"""
        if not self.candlestick_patterns:
            return
        dialog = self.candlestick_patterns.get_config_dialog(self)
        try:
            dialog.exec_()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "配置错误", f"配置蜡烛图形态指标时发生错误：\n{str(e)}")

    def _create_interval_panel(self):
        """创建周期面板"""
        w = QtWidgets.QWidget(self)
        w.setStyleSheet("QWidget { background-color: transparent; }")
        layout = QtWidgets.QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        intervals = [("1m", "1\n分\n钟", Interval.MINUTE, 60), ("3m", "3\n分\n钟", "3m", 60),
                     ("5m", "5\n分\n钟", "5m", 60), ("15m", "15\n分\n钟", "15m", 70),
                     ("30m", "30\n分\n钟", "30m", 70), ("1h", "1\n小\n时", Interval.HOUR, 60),
                     ("d", "日\n线", Interval.DAILY, 50)]

        for key, label, interval, height in intervals:
            btn = QtWidgets.QPushButton(label)
            btn.setFixedSize(40, height)
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton { background-color: rgba(60, 60, 60, 200); color: white; border: none; font-size: 11px; }
                QPushButton:hover { background-color: rgba(80, 80, 80, 220); }
                QPushButton:checked { background-color: rgba(0, 120, 215, 220); font-weight: bold; }
            """)
            if key == "1m":
                btn.setChecked(True)
            btn.clicked.connect(lambda c, i=interval, b=btn: self._on_interval_changed(i, b))
            self.interval_buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()
        w.setFixedWidth(40)
        w.adjustSize()
        self.interval_panel = w

        orig_resize = self.resizeEvent
        def resize_handler(event):
            if orig_resize:
                orig_resize(event)
            if hasattr(self, "interval_panel"):
                y = max(50, (self.height() - self.interval_panel.height()) // 2)
                self.interval_panel.move(0, y)
        self.resizeEvent = resize_handler
        w.move(0, max(50, (self.height() - w.height()) // 2))

    def _on_interval_changed(self, interval, btn):
        """周期切换"""
        if isinstance(interval, str):
            self.current_interval = {"3m": Interval.MINUTE, "5m": Interval.MINUTE, "15m": Interval.MINUTE, "30m": Interval.MINUTE, "1h": Interval.HOUR, "d": Interval.DAILY}.get(interval, Interval.MINUTE)
            self._actual_interval = interval
        else:
            self.current_interval = interval
            self._actual_interval = interval.value
        
        for b in self.interval_buttons.values():
            b.setChecked(False)
        btn.setChecked(True)
        
        if self.base_minute_bars:
            bars = self.base_minute_bars if self._actual_interval == "1m" else self._aggregate_bars(self.base_minute_bars, self._actual_interval)

            # 清理所有指标（包括独立的K线形态指标）
            for item in self._items.values():
                if hasattr(item, "clear_all"):
                    try: item.clear_all()
                    except: pass
            # 清理独立的K线形态指标
            if self.candlestick_patterns:
                try: self.candlestick_patterns.clear_all()
                except: pass

            self._manager.clear_all()
            for bar in bars:
                self._manager.update_bar(bar)
            for item in self._items.values():
                try:
                    if hasattr(item, "update_history"): item.update_history(bars)
                    if hasattr(item, "update"): item.update()
                except: pass

            # 更新独立的K线形态指标（仅在勾选时）
            if self.candlestick_patterns and hasattr(self, 'candlestick_patterns_checkbox'):
                if self.candlestick_patterns_checkbox.isChecked():
                    try: self.candlestick_patterns.on_history_updated(bars)
                    except: pass

            self._update_plot_limits()
            self.move_to_right()
            self.update()
            if self.on_interval_changed_callback:
                try: self.on_interval_changed_callback(bars, self._actual_interval)
                except: pass

    def _update_xaxis_visibility(self):
        """更新X轴可见性"""
        for name, plot in self._plots.items():
            if name != "candle":
                plot.hideAxis("bottom")
        visible = [n for n in self.sub_indicators.keys() if n in self._plots and self._plots[n].isVisible()]
        if visible:
            self._plots.get(visible[-1]).showAxis("bottom")

    def _setup_double_click_handlers(self):
        """设置双击处理"""
        candle = self._plots.get("candle")
        if candle:
            orig = getattr(candle, "mouseDoubleClickEvent", None)
            def handler(e):
                if orig: orig(e)
                self._toggle_main_focus()
            candle.mouseDoubleClickEvent = handler
        
        for name, plot in self._plots.items():
            if name != "candle":
                orig = getattr(plot, "mouseDoubleClickEvent", None)
                def make_handler(n, o):
                    def h(e):
                        if o: o(e)
                        self._toggle_sub_focus(n)
                    return h
                plot.mouseDoubleClickEvent = make_handler(name, orig)

    def _toggle_main_focus(self):
        """切换主图专注"""
        if self.focus_mode == "main":
            self._restore_plot_visibility()
            self._restore_plot_heights()
            self.focus_mode = None
        else:
            self._save_plot_visibility()
            self._hide_all_sub_plots()
            self.focus_mode = "main"

    def _toggle_sub_focus(self, name: str):
        """切换副图专注"""
        if self.focus_mode == name:
            self._restore_plot_visibility()
            self._restore_plot_heights()
            self.focus_mode = None
        else:
            self._save_plot_visibility()
            self._hide_all_sub_plots_except(name)
            self._remove_plot_max_height(name)
            self.focus_mode = name

    def _save_plot_visibility(self):
        self.saved_plot_visibility = {n: p.isVisible() for n, p in self._plots.items() if n != "candle"}

    def _restore_plot_visibility(self):
        for n, v in self.saved_plot_visibility.items():
            if n in self._plots:
                self._plots[n].show() if v else self._plots[n].hide()
        self._layout.updateGeometry()
        self._update_xaxis_visibility()
        if self.cursor_manager:
            self.cursor_manager.setup()
            self.cursor_manager.relocate_x_label()

    def _remove_plot_max_height(self, plot_name: str):
        """移除副图的最大高度限制（专注模式）"""
        if plot_name in self._plots:
            self._plots[plot_name].setMaximumHeight(16777215)  # Qt的默认最大值

    def _restore_plot_heights(self):
        """恢复副图的高度限制（退出专注模式）"""
        for name in self.sub_indicators:
            if name in self._plots and name in self.original_heights:
                max_h = self.original_heights[name]["maximum_height"]
                self._plots[name].setMaximumHeight(max_h)

    def _hide_all_sub_plots(self):
        for n, p in self._plots.items():
            if n != "candle": p.hide()
        self._layout.updateGeometry()
        self._update_xaxis_visibility()
        if self.cursor_manager:
            self.cursor_manager.setup()
            self.cursor_manager.relocate_x_label()

    def _hide_all_sub_plots_except(self, except_name: str):
        for n, p in self._plots.items():
            if n != "candle":
                p.show() if n == except_name else p.hide()
        self._layout.updateGeometry()
        self._update_xaxis_visibility()
        if self.cursor_manager:
            self.cursor_manager.setup()
            self.cursor_manager.relocate_x_label()


    # ==================== 数据更新方法 ====================
    
    def update_history(self, history: List[BarData]) -> None:
        """更新历史数据"""
        if history and history[0].interval == Interval.MINUTE:
            self.base_minute_bars = history.copy()
        if self.current_interval != Interval.MINUTE and self.base_minute_bars:
            super().update_history(self._aggregate_bars(self.base_minute_bars, self.current_interval))
        else:
            super().update_history(history)

        # 触发K线形态指标更新（仅在勾选时）
        if self.candlestick_patterns and hasattr(self, 'candlestick_patterns_checkbox'):
            if self.candlestick_patterns_checkbox.isChecked():
                # 获取当前显示的K线数据
                display_bars = []
                for ix in range(self._manager.get_count()):
                    display_bars.append(self._manager.get_bar(ix))
                self.candlestick_patterns.on_history_updated(display_bars)

        self._last_tick_volume = 0
        self.move_to_right()

    def update_bar(self, bar: BarData) -> None:
        """更新K线"""
        self._manager.update_bar(bar)
        for item in self._items.values():
            item.update_bar(bar)
        self._update_plot_limits()
        for item in self._items.values():
            if hasattr(item, "update"): item.update()

        # 触发K线形态指标更新（仅在勾选时）
        if self.candlestick_patterns and hasattr(self, 'candlestick_patterns_checkbox'):
            if self.candlestick_patterns_checkbox.isChecked():
                # 获取所有K线数据
                all_bars = []
                for ix in range(self._manager.get_count()):
                    all_bars.append(self._manager.get_bar(ix))
                self.candlestick_patterns.on_bar_updated(bar, all_bars)

    def update_tick(self, tick) -> None:
        """更新Tick"""
        self._update_base_minute_bars(tick)
        if not hasattr(self, "_manager") or self._manager.get_count() == 0:
            return
        last_bar = self._manager.get_bar(self._manager.get_count() - 1)
        if not last_bar:
            return
        
        bar_start, bar_end = self._get_bar_time_range(last_bar, tick.datetime)
        
        if bar_start <= tick.datetime < bar_end:
            new_vol = self._calc_volume(last_bar, tick)
            updated = BarData(
                symbol=last_bar.symbol, exchange=last_bar.exchange, datetime=last_bar.datetime,
                interval=last_bar.interval, gateway_name=last_bar.gateway_name,
                open_price=last_bar.open_price, high_price=max(last_bar.high_price, tick.last_price),
                low_price=min(last_bar.low_price, tick.last_price), close_price=tick.last_price,
                volume=new_vol, turnover=last_bar.turnover,
                open_interest=getattr(tick, 'open_interest', last_bar.open_interest)
            )
            self.update_bar(updated)
            self._update_price_line(tick.last_price)
        else:
            self._create_new_bar_from_tick(tick)

    def _get_bar_time_range(self, last_bar, tick_time):
        """获取K线时间范围"""
        if self._actual_interval == "1m":
            start = last_bar.datetime.replace(second=0, microsecond=0)
            return start, start + timedelta(minutes=1)
        elif self._actual_interval == "3m":
            m = (last_bar.datetime.minute // 3) * 3
            start = last_bar.datetime.replace(minute=m, second=0, microsecond=0)
            return start, start + timedelta(minutes=3)
        elif self._actual_interval == "5m":
            m = (last_bar.datetime.minute // 5) * 5
            start = last_bar.datetime.replace(minute=m, second=0, microsecond=0)
            return start, start + timedelta(minutes=5)
        elif self._actual_interval == "15m":
            m = (last_bar.datetime.minute // 15) * 15
            start = last_bar.datetime.replace(minute=m, second=0, microsecond=0)
            return start, start + timedelta(minutes=15)
        elif self._actual_interval == "30m":
            # 半小时K线：如果配置了half_hour_sessions，使用交易时段；否则使用自然30分钟
            if self.trading_session and self.trading_session.half_hour_sessions:
                idx = self._get_half_hour_session_index(last_bar.datetime.time())
                if idx is not None:
                    sessions = self.trading_session.half_hour_sessions[:]
                    if self.trading_session.has_night_session and self.trading_session.night_half_hour_sessions:
                        sessions.extend(self.trading_session.night_half_hour_sessions)
                    if idx < len(sessions):
                        s, e = sessions[idx]
                        start = last_bar.datetime.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
                        end = last_bar.datetime.replace(hour=e.hour, minute=e.minute, second=59, microsecond=999999)
                        if e < s:
                            if tick_time.time() <= e: start -= timedelta(days=1)
                            else: end += timedelta(days=1)
                        return start, end
            # 默认使用自然30分钟
            m = (last_bar.datetime.minute // 30) * 30
            start = last_bar.datetime.replace(minute=m, second=0, microsecond=0)
            return start, start + timedelta(minutes=30)
        elif self._actual_interval in ("1h", Interval.HOUR.value):
            if self.trading_session and self.trading_session.hour_sessions:
                idx = self._get_hour_session_index(last_bar.datetime.time())
                if idx is not None:
                    sessions = self.trading_session.hour_sessions[:]
                    if self.trading_session.has_night_session and self.trading_session.night_sessions:
                        sessions.extend(self.trading_session.night_sessions)
                    if idx < len(sessions):
                        s, e = sessions[idx]
                        start = last_bar.datetime.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
                        end = last_bar.datetime.replace(hour=e.hour, minute=e.minute, second=59, microsecond=999999)
                        if e < s:
                            if tick_time.time() <= e: start -= timedelta(days=1)
                            else: end += timedelta(days=1)
                        return start, end
            start = last_bar.datetime.replace(minute=0, second=0, microsecond=0)
            return start, start + timedelta(hours=1)
        elif self._actual_interval in ("d", Interval.DAILY.value):
            start = last_bar.datetime.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1)
        start = last_bar.datetime.replace(second=0, microsecond=0)
        return start, start + timedelta(minutes=1)

    def _calc_volume(self, last_bar, tick) -> float:
        """计算成交量"""
        if hasattr(tick, "volume") and tick.volume > 0:
            if self._last_tick_volume == 0:
                self._last_tick_volume = tick.volume
                return last_bar.volume
            delta = tick.volume - self._last_tick_volume
            self._last_tick_volume = tick.volume
            return last_bar.volume + delta if delta > 0 else last_bar.volume
        return last_bar.volume

    def _update_base_minute_bars(self, tick):
        """更新基础1分钟K线"""
        if not self.base_minute_bars:
            return
        last = self.base_minute_bars[-1]
        start = last.datetime.replace(second=0, microsecond=0)
        end = start + timedelta(minutes=1)
        
        if start <= tick.datetime < end:
            if hasattr(tick, "volume") and tick.volume > 0:
                if self._last_tick_volume_for_base == 0:
                    self._last_tick_volume_for_base = tick.volume
                    new_vol = last.volume
                else:
                    delta = tick.volume - self._last_tick_volume_for_base
                    self._last_tick_volume_for_base = tick.volume
                    new_vol = last.volume + delta if delta > 0 else last.volume
            else:
                new_vol = last.volume
            self.base_minute_bars[-1] = BarData(
                symbol=last.symbol, exchange=last.exchange, datetime=last.datetime,
                interval=Interval.MINUTE, gateway_name=last.gateway_name,
                open_price=last.open_price, high_price=max(last.high_price, tick.last_price),
                low_price=min(last.low_price, tick.last_price), close_price=tick.last_price,
                volume=new_vol, turnover=last.turnover,
                open_interest=getattr(tick, 'open_interest', last.open_interest)
            )
        else:
            self._last_tick_volume_for_base = getattr(tick, 'volume', 0)
            self.base_minute_bars.append(BarData(
                symbol=last.symbol, exchange=last.exchange,
                datetime=tick.datetime.replace(second=0, microsecond=0),
                interval=Interval.MINUTE, gateway_name=last.gateway_name,
                open_price=tick.last_price, high_price=tick.last_price,
                low_price=tick.last_price, close_price=tick.last_price,
                volume=0, turnover=0, open_interest=getattr(tick, 'open_interest', 0)
            ))

    def _create_new_bar_from_tick(self, tick):
        """从Tick创建新K线"""
        if self._manager.get_count() == 0:
            return
        last = self._manager.get_bar(self._manager.get_count() - 1)
        if not last:
            return
        new_time = self._calc_new_bar_time(tick.datetime)
        new_bar = BarData(
            symbol=last.symbol, exchange=last.exchange, datetime=new_time,
            interval=last.interval, gateway_name=last.gateway_name,
            open_price=tick.last_price, high_price=tick.last_price,
            low_price=tick.last_price, close_price=tick.last_price,
            volume=0, turnover=0, open_interest=getattr(tick, 'open_interest', 0)
        )
        self._manager.update_bar(new_bar)
        for item in self._items.values():
            item.update_bar(new_bar)
        self._update_plot_limits()
        self._update_price_line(tick.last_price)
        if hasattr(tick, "volume"):
            self._last_tick_volume = tick.volume

    def _calc_new_bar_time(self, tick_time):
        """计算新K线时间"""
        if self._actual_interval == "1m":
            return tick_time.replace(second=0, microsecond=0)
        elif self._actual_interval == "3m":
            return tick_time.replace(minute=(tick_time.minute // 3) * 3, second=0, microsecond=0)
        elif self._actual_interval == "5m":
            return tick_time.replace(minute=(tick_time.minute // 5) * 5, second=0, microsecond=0)
        elif self._actual_interval == "15m":
            return tick_time.replace(minute=(tick_time.minute // 15) * 15, second=0, microsecond=0)
        elif self._actual_interval == "30m":
            # 半小时K线：如果配置了half_hour_sessions，使用交易时段；否则使用自然30分钟
            if self.trading_session and self.trading_session.half_hour_sessions:
                idx = self._get_half_hour_session_index(tick_time.time())
                if idx is not None:
                    sessions = self.trading_session.half_hour_sessions[:]
                    if self.trading_session.has_night_session and self.trading_session.night_half_hour_sessions:
                        sessions.extend(self.trading_session.night_half_hour_sessions)
                    if idx < len(sessions):
                        s, _ = sessions[idx]
                        return tick_time.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
            return tick_time.replace(minute=(tick_time.minute // 30) * 30, second=0, microsecond=0)
        elif self._actual_interval in ("1h", Interval.HOUR.value):
            if self.trading_session and self.trading_session.hour_sessions:
                idx = self._get_hour_session_index(tick_time.time())
                if idx is not None:
                    sessions = self.trading_session.hour_sessions[:]
                    if self.trading_session.has_night_session and self.trading_session.night_sessions:
                        sessions.extend(self.trading_session.night_sessions)
                    if idx < len(sessions):
                        s, _ = sessions[idx]
                        return tick_time.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
            return tick_time.replace(minute=0, second=0, microsecond=0)
        elif self._actual_interval in ("d", Interval.DAILY.value):
            return tick_time.replace(hour=0, minute=0, second=0, microsecond=0)
        return tick_time.replace(second=0, microsecond=0)


    # ==================== 聚合与交易时段 ====================

    def _get_hour_session_index(self, bar_time: time) -> Optional[int]:
        """获取小时时段索引"""
        if not self.trading_session or not self.trading_session.hour_sessions:
            return None
        for idx, (s, e) in enumerate(self.trading_session.hour_sessions):
            if s <= bar_time <= e:
                return idx
        if self.trading_session.has_night_session and self.trading_session.night_sessions:
            offset = len(self.trading_session.hour_sessions)
            for idx, (s, e) in enumerate(self.trading_session.night_sessions):
                if s <= e:
                    if s <= bar_time <= e:
                        return offset + idx
                else:
                    if bar_time >= s or bar_time <= e:
                        return offset + idx
        return None

    def _get_half_hour_session_index(self, bar_time: time) -> Optional[int]:
        """获取半小时时段索引"""
        if not self.trading_session or not self.trading_session.half_hour_sessions:
            return None
        for idx, (s, e) in enumerate(self.trading_session.half_hour_sessions):
            if s <= bar_time <= e:
                return idx
        if self.trading_session.has_night_session and self.trading_session.night_half_hour_sessions:
            offset = len(self.trading_session.half_hour_sessions)
            for idx, (s, e) in enumerate(self.trading_session.night_half_hour_sessions):
                if s <= e:
                    if s <= bar_time <= e:
                        return offset + idx
                else:
                    if bar_time >= s or bar_time <= e:
                        return offset + idx
        return None

    def _aggregate_bars(self, minute_bars: List[BarData], target_interval) -> List[BarData]:
        """聚合K线"""
        if not minute_bars:
            return []
        interval_str = target_interval.value if isinstance(target_interval, Interval) else target_interval
        # 支持多种时间间隔格式：简写（1m, 5m, 15m, 1h）和完整格式（1min, 5min, 15min, 1hour）
        minutes = {
            "1m": 1, "1min": 1,
            "3m": 3, "3min": 3,
            "5m": 5, "5min": 5,
            "15m": 15, "15min": 15,
            "30m": 30, "30min": 30,
            "1h": 60, "1hour": 60,
            "4h": 240, "4hour": 240,
            "d": 1440, "day": 1440
        }.get(interval_str, 1)
        if minutes == 1:
            return minute_bars

        aggregated, current, current_key = [], None, None
        for bar in minute_bars:
            if interval_str == "d":
                # 日线：根据daily_end时间划分交易日
                if self.trading_session and self.trading_session.daily_end:
                    daily_end = self.trading_session.daily_end
                    bar_time = bar.datetime.time()

                    # 判断是否在夜盘时段（夜盘属于下一个交易日）
                    in_night_session = False
                    if self.trading_session.has_night_session and self.trading_session.night_sessions:
                        for night_start, night_end in self.trading_session.night_sessions:
                            if night_start <= night_end:
                                # 正常时段（不跨日）
                                if night_start <= bar_time <= night_end:
                                    in_night_session = True
                                    break
                            else:
                                # 跨日时段（如23:00-02:00）
                                if bar_time >= night_start or bar_time <= night_end:
                                    in_night_session = True
                                    break

                    # 夜盘属于下一个交易日
                    if in_night_session:
                        # 如果是夜盘且在午夜之前，属于下一个交易日
                        if bar_time > daily_end:
                            key = bar.datetime.date() + timedelta(days=1)
                        else:
                            # 午夜之后的夜盘，已经是下一个自然日，但仍属于当天交易日
                            key = bar.datetime.date()
                    else:
                        # 日盘：正常按当天划分
                        key = bar.datetime.date()
                else:
                    # 默认按自然日划分
                    key = bar.datetime.date()
            elif interval_str == "1h":
                idx = self._get_hour_session_index(bar.datetime.time())
                key = (bar.datetime.date(), f"s{idx}") if idx is not None else (bar.datetime.date(), bar.datetime.hour)
            elif interval_str == "30m":
                # 半小时K线：如果配置了half_hour_sessions，使用交易时段合成；否则使用自然30分钟
                idx = self._get_half_hour_session_index(bar.datetime.time())
                key = (bar.datetime.date(), f"h{idx}") if idx is not None else (bar.datetime.date(), (bar.datetime.hour * 60 + bar.datetime.minute) // minutes)
            else:
                key = (bar.datetime.date(), (bar.datetime.hour * 60 + bar.datetime.minute) // minutes)

            if current is None:
                current = BarData(symbol=bar.symbol, exchange=bar.exchange, datetime=bar.datetime,
                    interval=target_interval, open_price=bar.open_price, high_price=bar.high_price,
                    low_price=bar.low_price, close_price=bar.close_price, volume=bar.volume,
                    turnover=bar.turnover, open_interest=bar.open_interest, gateway_name=bar.gateway_name)
                current_key = key
            elif key != current_key:
                aggregated.append(current)
                current = BarData(symbol=bar.symbol, exchange=bar.exchange, datetime=bar.datetime,
                    interval=target_interval, open_price=bar.open_price, high_price=bar.high_price,
                    low_price=bar.low_price, close_price=bar.close_price, volume=bar.volume,
                    turnover=bar.turnover, open_interest=bar.open_interest, gateway_name=bar.gateway_name)
                current_key = key
            else:
                current.high_price = max(current.high_price, bar.high_price)
                current.low_price = min(current.low_price, bar.low_price)
                current.close_price = bar.close_price
                current.volume += bar.volume
                current.turnover += bar.turnover
                current.open_interest = bar.open_interest

        if current:
            aggregated.append(current)
        return aggregated

    def set_trading_session(self, trading_session):
        """设置交易时段"""
        from config.trading_sessions_config import MarketType, get_trading_session
        self.trading_session = get_trading_session(trading_session) if isinstance(trading_session, MarketType) else trading_session

    def set_trading_session_by_symbol(self, symbol: str, exchange: str = ""):
        """根据品种设置交易时段"""
        from config.trading_sessions_config import get_trading_session_by_symbol
        self.trading_session = get_trading_session_by_symbol(symbol, exchange)
        self.current_symbol = symbol
        self.current_exchange = exchange

    def clear_all(self) -> None:
        """清空数据"""
        for item in self._items.values():
            if hasattr(item, "clear_all"):
                item.clear_all()
        self.update()

    # ==================== 视图控制 ====================

    def _update_plot_limits(self) -> None:
        """更新绘图限制"""
        for item, plot in self._item_plot_map.items():
            min_v, max_v = item.get_y_range()
            y_range = max_v - min_v
            view = plot.getViewBox()
            if view:
                view.setLimits(xMin=-1, xMax=self._manager.get_count() + 100,
                    yMin=min_v - y_range * 2, yMax=max_v + y_range * 2)

    def _update_x_range(self) -> None:
        """更新X轴范围"""
        for plot in self._plots.values():
            view = plot.getViewBox()
            if view:
                view.setRange(xRange=(self._right_ix - self._bar_count, self._right_ix), padding=0.03)

    def _on_key_right(self) -> None:
        """右键"""
        self._right_ix += 1
        count = self._manager.get_count()
        self._right_ix = min(self._right_ix, count - 1 + 50)
        self._update_x_range()
        if self._cursor and self._cursor._x < count - 1:
            self._cursor._x += 1
            bar = self._manager.get_bar(self._cursor._x)
            if bar:
                self._cursor._y = bar.close_price
                self._cursor._update_line()
                self._cursor._update_label()
            self._cursor.update_info()

    def _on_key_left(self) -> None:
        """左键"""
        self._right_ix -= 1
        count = self._manager.get_count()
        self._right_ix = max(self._right_ix, count - 1 if count <= self._bar_count else self._bar_count)
        self._update_x_range()
        if self._cursor and self._cursor._x > 0:
            self._cursor._x -= 1
            bar = self._manager.get_bar(self._cursor._x)
            if bar:
                self._cursor._y = bar.close_price
                self._cursor._update_line()
                self._cursor._update_label()
            self._cursor.update_info()

    # 兼容旧接口
    def _relocate_cursor_x_label(self):
        if self.cursor_manager:
            self.cursor_manager.relocate_x_label()

    def _setup_cursor_fix(self):
        if self.cursor_manager:
            self.cursor_manager.setup()
