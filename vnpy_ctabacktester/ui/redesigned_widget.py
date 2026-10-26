"""
重新设计的回测界面组件
按照原型图实现两列布局(1:3比例)的回测界面
"""
import os
import platform
import csv
import shutil
import subprocess
from datetime import datetime, timedelta
from copy import copy
from typing import Any

import numpy as np
import pyqtgraph as pg
from pandas import DataFrame

from vnpy.trader.constant import Interval, Direction, Exchange
from vnpy.trader.engine import MainEngine, BaseEngine
from vnpy.trader.ui import QtCore, QtWidgets, QtGui
from vnpy.trader.ui.widget import BaseMonitor, BaseCell, DirectionCell, EnumCell
from vnpy.event import Event, EventEngine
# from vnpy.chart import ChartWidget, CandleItem, VolumeItem
from vnpy.trader.utility import load_json, save_json
from vnpy.trader.object import BarData, TradeData, OrderData
from vnpy.trader.database import DB_TZ
from vnpy_ctastrategy.backtesting import DailyResult

from ..locale import _
from ..engine import (
    APP_NAME,
    EVENT_BACKTESTER_LOG,
    EVENT_BACKTESTER_BACKTESTING_FINISHED,
    EVENT_BACKTESTER_OPTIMIZATION_FINISHED,
    OptimizationSetting
)

# 导入增强的统计监控器
from .enhanced_widget import EnhancedStatisticsMonitor

# 避免循环导入，在需要时动态导入对话框类


class RedesignedBacktesterManager(QtWidgets.QWidget):
    """
    重新设计的回测管理器
    采用两列布局：左侧参数设置+控制台，右侧选项卡+图表
    """

    setting_filename: str = "cta_backtester_setting.json"

    signal_log: QtCore.Signal = QtCore.Signal(Event)
    signal_backtesting_finished: QtCore.Signal = QtCore.Signal(Event)
    signal_optimization_finished: QtCore.Signal = QtCore.Signal(Event)

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine) -> None:
        """"""
        super().__init__()

        self.main_engine: MainEngine = main_engine
        self.event_engine: EventEngine = event_engine

        self.backtester_engine: BaseEngine = main_engine.get_engine(APP_NAME)
        self.class_names: list = []
        self.settings: dict = {}

        self.target_display: str = ""

        # 延迟初始化标志，避免 Qt + multiprocessing 冲突（macOS bus error）
        self._engine_initialized: bool = False

        self.init_ui()

        # 记录界面初始值，用于切换到无历史配置的策略时恢复默认
        self.default_setting: dict = {
            "vt_symbol": self.symbol_line.text(),
            "interval": self.interval_combo.currentText(),
            "start": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "end": self.end_date_edit.date().toString("yyyy-MM-dd"),
            "rate": self.rate_line.text(),
            "slippage": self.slippage_line.text(),
            "size": self.size_line.text(),
            "pricetick": self.pricetick_line.text(),
            "capital": self.capital_line.text(),
        }

        self.register_event()

        # 在UI初始化完成后，立即初始化引擎和策略列表（用于填充下拉列表）
        # 注意：这里只初始化引擎和加载策略名称，不会创建多进程池
        self.ensure_engine_initialized()

        self.load_backtesting_setting()

        # 切换策略时自动恢复该策略的历史配置
        self.class_combo.currentTextChanged.connect(self.on_strategy_changed)

        # 初始化对话框（延迟导入避免循环依赖）
        self.trade_dialog = None
        self.order_dialog = None
        self.daily_dialog = None

    def init_strategy_settings(self) -> None:
        """"""
        self.class_names = self.backtester_engine.get_strategy_class_names()
        self.class_names.sort()

        for class_name in self.class_names:
            setting: dict = self.backtester_engine.get_default_setting(class_name)
            self.settings[class_name] = setting

        self.class_combo.addItems(self.class_names)

    def ensure_engine_initialized(self) -> None:
        """
        确保引擎已初始化（延迟初始化模式）

        这个方法解决了 macOS 上的 Qt + multiprocessing 冲突问题：
        - 在 __init__() 中过早初始化引擎会触发多进程池创建
        - macOS 的 spawn 模式会尝试序列化 Qt 对象到子进程
        - Qt 对象不可序列化，导致 bus error 和信号量泄漏

        延迟初始化策略：
        - 构造函数中不初始化引擎
        - 在真正需要时（用户点击操作按钮）才初始化
        - 使用标志位确保只初始化一次
        """
        if not self._engine_initialized:
            self.backtester_engine.init_engine()
            self.init_strategy_settings()
            self._engine_initialized = True

    def init_ui(self) -> None:
        """"""
        self.setWindowTitle(_("CTA回测"))
        self.setMinimumSize(1400, 800)

        # 设置深色主题样式
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px 8px;
                color: #fff;
                font-size: 12px;
                min-height: 18px;
                max-height: 30px;
            }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus {
                border-color: #007acc;
                background-color: #3a3a3a;
            }
            QComboBox {
                padding-right: 25px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
                background-color: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                width: 0;
                height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 7px solid #ccc;
                margin: 0px;
            }
            QComboBox::down-arrow:hover {
                border-top-color: #fff;
            }
            QComboBox::down-arrow:pressed {
                border-top-color: #007acc;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #fff;
                selection-background-color: #007acc;
                border: 1px solid #555;
                border-radius: 4px;
                outline: none;
                padding: 2px;
                margin: 0px;
            }
            QComboBox QAbstractItemView::item {
                height: 24px;
                padding: 4px 8px;
                margin: 1px;
                border: none;
                border-radius: 2px;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #007acc;
                color: #fff;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #444;
                color: #fff;
            }
            QPushButton {
                background-color: #007acc;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004578;
            }
            QPushButton.primary {
                background-color: #28a745;
            }
            QPushButton.primary:hover {
                background-color: #218838;
            }
            QTabWidget::pane {
                border: 1px solid #444;
                background-color: #2a2a2a;
            }
            QTabBar::tab {
                background-color: #333;
                color: #ccc;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #007acc;
                color: white;
            }
            QTabBar::tab:hover:not(:selected) {
                background-color: #444;
            }
            QTableWidget {
                background-color: #2a2a2a;
                alternate-background-color: #333;
                gridline-color: #444;
                color: #fff;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #007acc;
            }
            QHeaderView::section {
                background-color: #333;
                color: #ccc;
                padding: 5px;
                border: none;
                border-right: 1px solid #444;
            }
            QTextEdit {
                background-color: #000;
                color: #28a745;
                border: 1px solid #333;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
            }
        """)

        # 创建主布局
        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # 左侧列 (25% 宽度)
        left_panel = self.create_left_panel()
        left_panel.setMaximumWidth(350)
        left_panel.setMinimumWidth(300)

        # 右侧列 (75% 宽度)
        right_panel = self.create_right_panel()

        # 设置布局比例
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 3)

        self.setLayout(main_layout)

    def create_left_panel(self) -> QtWidgets.QWidget:
        """创建左侧面板"""
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(10)

        # 参数设置区域
        param_group = self.create_parameter_group()
        left_layout.addWidget(param_group)

        # 按钮区域
        button_group = self.create_button_group()
        left_layout.addWidget(button_group)

        # 控制台区域
        console_group = self.create_console_group()
        left_layout.addWidget(console_group)

        left_widget.setLayout(left_layout)
        return left_widget

    def create_parameter_group(self) -> QtWidgets.QGroupBox:
        """创建参数设置组"""
        group = QtWidgets.QGroupBox("回测参数设置")
        layout = QtWidgets.QFormLayout()
        layout.setSpacing(8)

        # 创建输入控件
        self.class_combo = QtWidgets.QComboBox()
        self.symbol_line = QtWidgets.QLineEdit("jm2601.DCE")
        self.interval_combo = QtWidgets.QComboBox()
        
        # 添加K线周期选项
        for interval in Interval:
            self.interval_combo.addItem(interval.value)

        # 设置默认日期
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=3 * 365)

        self.start_date_edit = QtWidgets.QDateEdit(
            QtCore.QDate(start_dt.year, start_dt.month, start_dt.day)
        )
        self.start_date_edit.setCalendarPopup(True)
        
        self.end_date_edit = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.end_date_edit.setCalendarPopup(True)

        self.rate_line = QtWidgets.QLineEdit("0.0001")
        self.slippage_line = QtWidgets.QLineEdit("0.0")
        self.size_line = QtWidgets.QLineEdit("60.0")
        self.pricetick_line = QtWidgets.QLineEdit("0.5")
        self.capital_line = QtWidgets.QLineEdit("100000.0")

        # 添加到布局
        layout.addRow("交易策略:", self.class_combo)
        layout.addRow("本地代码:", self.symbol_line)
        layout.addRow("K线周期:", self.interval_combo)
        layout.addRow("开始日期:", self.start_date_edit)
        layout.addRow("结束日期:", self.end_date_edit)
        layout.addRow("手续费率:", self.rate_line)
        layout.addRow("交易滑点:", self.slippage_line)
        layout.addRow("合约乘数:", self.size_line)
        layout.addRow("价格跳动:", self.pricetick_line)
        layout.addRow("回测资金:", self.capital_line)

        group.setLayout(layout)
        return group

    def create_button_group(self) -> QtWidgets.QGroupBox:
        """创建按钮组"""
        group = QtWidgets.QGroupBox("操作控制")
        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(8)

        # 创建按钮
        self.backtesting_button = QtWidgets.QPushButton("开始回测")
        self.backtesting_button.setProperty("class", "primary")
        self.backtesting_button.clicked.connect(self.start_backtesting)

        self.candle_button = QtWidgets.QPushButton("K线图表")
        self.candle_button.clicked.connect(self.show_candle_chart)
        self.candle_button.setEnabled(False)

        self.optimization_button = QtWidgets.QPushButton("参数优化")
        self.optimization_button.clicked.connect(self.start_optimization)

        self.result_button = QtWidgets.QPushButton("优化结果")
        self.result_button.clicked.connect(self.show_optimization_result)
        self.result_button.setEnabled(False)  # 初始状态禁用

        self.downloading_button = QtWidgets.QPushButton("下载数据")
        self.downloading_button.clicked.connect(self.start_downloading)

        self.reload_button = QtWidgets.QPushButton("策略重载")
        self.reload_button.clicked.connect(self.reload_strategy_class)

        # 设置按钮高度
        for button in [self.backtesting_button, self.candle_button, self.optimization_button,
                      self.result_button, self.downloading_button, self.reload_button]:
            button.setFixedHeight(32)  # 稍微减小高度以适应两列布局

        # 开始回测按钮单独一行（重要操作）
        layout.addWidget(self.backtesting_button)

        # 创建两列网格布局
        grid_layout = QtWidgets.QGridLayout()
        grid_layout.setSpacing(6)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        # 第一行：K线图表 | 下载数据
        grid_layout.addWidget(self.candle_button, 0, 0)
        grid_layout.addWidget(self.downloading_button, 0, 1)

        # 第二行：参数优化 | 优化结果
        grid_layout.addWidget(self.optimization_button, 1, 0)
        grid_layout.addWidget(self.result_button, 1, 1)

        # 第三行：策略重载（跨两列）
        grid_layout.addWidget(self.reload_button, 2, 0, 1, 2)

        # 创建网格容器
        grid_widget = QtWidgets.QWidget()
        grid_widget.setLayout(grid_layout)
        
        layout.addWidget(grid_widget)

        group.setLayout(layout)
        return group

    def create_console_group(self) -> QtWidgets.QGroupBox:
        """创建控制台组"""
        group = QtWidgets.QGroupBox("控制台输出")
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.log_monitor = QtWidgets.QTextEdit()
        self.log_monitor.setReadOnly(True)
        self.log_monitor.setMaximumHeight(300)
        self.log_monitor.setMinimumHeight(200)

        layout.addWidget(self.log_monitor)
        group.setLayout(layout)
        return group

    def create_right_panel(self) -> QtWidgets.QWidget:
        """创建右侧面板"""
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(5)

        # 上半部分 - 选项卡区域 (50%高度)
        tabs_widget = self.create_tabs_widget()
        right_layout.addWidget(tabs_widget, 1)

        # 下半部分 - 图表区域 (50%高度)
        charts_widget = self.create_charts_widget()
        right_layout.addWidget(charts_widget, 1)

        right_widget.setLayout(right_layout)
        return right_widget

    def create_tabs_widget(self) -> QtWidgets.QWidget:
        """创建选项卡组件"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建选项卡
        self.tab_widget = QtWidgets.QTabWidget()
        
        # 核心指标概览选项卡
        self.core_metrics_tab = self.create_core_metrics_tab()
        self.tab_widget.addTab(self.core_metrics_tab, "核心指标概览")
        
        # 完整指标分组选项卡
        self.metrics_tab = self.create_metrics_tab()
        self.tab_widget.addTab(self.metrics_tab, "完整指标分组")

        # 成交记录选项卡
        self.trades_tab = self.create_trades_tab()
        self.tab_widget.addTab(self.trades_tab, "成交记录")

        # 委托记录选项卡
        self.orders_tab = self.create_orders_tab()
        self.tab_widget.addTab(self.orders_tab, "委托记录")

        # 每日盈亏选项卡
        self.daily_tab = self.create_daily_tab()
        self.tab_widget.addTab(self.daily_tab, "每日盈亏")

        # 月度统计选项卡
        self.monthly_chart_tab = self.create_monthly_chart_tab()
        self.tab_widget.addTab(self.monthly_chart_tab, "月度统计")

        # 半小时区间统计选项卡
        self.interval_chart_tab = self.create_interval_chart_tab()
        self.tab_widget.addTab(self.interval_chart_tab, "区间统计")

        layout.addWidget(self.tab_widget)
        widget.setLayout(layout)
        return widget

    def create_core_metrics_tab(self) -> QtWidgets.QWidget:
        """创建核心指标概览选项卡"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # 创建核心指标网格
        self.core_metrics_widget = CoreMetricsWidget()
        layout.addWidget(self.core_metrics_widget)

        widget.setLayout(layout)
        return widget

    def create_metrics_tab(self) -> QtWidgets.QWidget:
        """创建完整指标分组选项卡"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        # 使用增强的统计监控器（双列布局）
        self.metrics_widget = EnhancedStatisticsMonitor()
        layout.addWidget(self.metrics_widget)

        widget.setLayout(layout)
        return widget

    def create_trades_tab(self) -> QtWidgets.QWidget:
        """创建成交记录选项卡"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.trades_table = QtWidgets.QTableWidget()
        self.trades_table.setColumnCount(10)
        self.trades_table.setHorizontalHeaderLabels([
            _("成交号"), _("委托号"), _("代码"), _("交易所"), _("方向"), 
            _("开平"), _("价格"), _("数量"), _("时间"), _("接口")
        ])
        self.trades_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.trades_table)
        widget.setLayout(layout)
        return widget

    def create_orders_tab(self) -> QtWidgets.QWidget:
        """创建委托记录选项卡"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.orders_table = QtWidgets.QTableWidget()
        self.orders_table.setColumnCount(12)
        self.orders_table.setHorizontalHeaderLabels([
            _("委托号"), _("代码"), _("交易所"), _("类型"), _("方向"), 
            _("开平"), _("价格"), _("总数量"), _("已成交"), _("状态"), _("时间"), _("接口")
        ])
        self.orders_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.orders_table)
        widget.setLayout(layout)
        return widget

    def create_daily_tab(self) -> QtWidgets.QWidget:
        """创建每日盈亏选项卡"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.daily_table = QtWidgets.QTableWidget()
        self.daily_table.setColumnCount(11)
        self.daily_table.setHorizontalHeaderLabels([
            _("日期"), _("成交笔数"), _("开盘持仓"), _("收盘持仓"), _("成交额"), 
            _("手续费"), _("滑点"), _("交易盈亏"), _("持仓盈亏"), _("总盈亏"), _("净盈亏")
        ])
        self.daily_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.daily_table)
        widget.setLayout(layout)
        return widget

    def create_monthly_chart_tab(self) -> QtWidgets.QWidget:
        """创建月度统计图表选项卡"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # 创建容器widget用于放置图表
        self.monthly_chart_container = QtWidgets.QWidget()
        monthly_chart_layout = QtWidgets.QVBoxLayout()
        monthly_chart_layout.setContentsMargins(0, 0, 0, 0)
        self.monthly_chart_container.setLayout(monthly_chart_layout)
        layout.addWidget(self.monthly_chart_container)

        widget.setLayout(layout)
        return widget

    def create_interval_chart_tab(self) -> QtWidgets.QWidget:
        """创建半小时区间统计图表选项卡"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # 创建容器widget用于放置图表
        self.interval_chart_container = QtWidgets.QWidget()
        interval_chart_layout = QtWidgets.QVBoxLayout()
        interval_chart_layout.setContentsMargins(0, 0, 0, 0)
        self.interval_chart_container.setLayout(interval_chart_layout)
        layout.addWidget(self.interval_chart_container)

        widget.setLayout(layout)
        return widget

    def create_charts_widget(self) -> QtWidgets.QWidget:
        """创建图表组件"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建两行两列图表布局
        charts_container = QtWidgets.QWidget()
        charts_layout = QtWidgets.QGridLayout()
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(2)

        # 第一行：账户净值、净值回撤
        self.chart1 = ChartWidget("账户净值")
        self.chart2 = ChartWidget("净值回撤")

        # 第二行：每日盈亏、滚动夏普比率
        self.chart3 = ChartWidget("每日盈亏")
        self.chart4 = ChartWidget("滚动夏普比率")

        # 添加到网格布局，两行两列
        charts_layout.addWidget(self.chart1, 0, 0)
        charts_layout.addWidget(self.chart2, 0, 1)
        charts_layout.addWidget(self.chart3, 1, 0)
        charts_layout.addWidget(self.chart4, 1, 1)

        # 设置行和列的拉伸因子，保持1:1比例
        charts_layout.setRowStretch(0, 1)
        charts_layout.setRowStretch(1, 1)
        charts_layout.setColumnStretch(0, 1)
        charts_layout.setColumnStretch(1, 1)

        charts_container.setLayout(charts_layout)

        layout.addWidget(charts_container)
        widget.setLayout(layout)
        return widget

    def load_backtesting_setting(self) -> None:
        """加载回测配置，支持按策略名存储多组配置"""
        all_settings: dict = load_json(self.setting_filename)
        if not all_settings:
            return

        # 兼容旧版单一配置格式（含 class_name 键的 flat dict）
        if "class_name" in all_settings:
            class_name: str = all_settings["class_name"]
            migrated: dict = {
                "_last_used": class_name,
                class_name: {k: v for k, v in all_settings.items() if k != "class_name"}
            }
            all_settings = migrated
            save_json(self.setting_filename, all_settings)

        # 恢复上次使用的策略
        last_used: str = all_settings.get("_last_used", "")
        if last_used:
            idx: int = self.class_combo.findText(last_used)
            if idx >= 0:
                self.class_combo.setCurrentIndex(idx)

        # 加载当前策略的配置
        current_class: str = self.class_combo.currentText()
        if current_class:
            self._apply_strategy_setting(all_settings.get(current_class, {}))

    def _apply_strategy_setting(self, setting: dict) -> None:
        """将配置项应用到界面控件"""
        if not setting:
            return

        if "vt_symbol" in setting:
            self.symbol_line.setText(setting["vt_symbol"])

        if "interval" in setting:
            self.interval_combo.setCurrentIndex(
                self.interval_combo.findText(setting["interval"])
            )

        start_str: str = setting.get("start", "")
        if start_str:
            start_dt: QtCore.QDate = QtCore.QDate.fromString(start_str, "yyyy-MM-dd")
            self.start_date_edit.setDate(start_dt)

        end_str: str = setting.get("end", "")
        if end_str:
            end_dt: QtCore.QDate = QtCore.QDate.fromString(end_str, "yyyy-MM-dd")
            self.end_date_edit.setDate(end_dt)

        if "rate" in setting:
            self.rate_line.setText(str(setting["rate"]))
        if "slippage" in setting:
            self.slippage_line.setText(str(setting["slippage"]))
        if "size" in setting:
            self.size_line.setText(str(setting["size"]))
        if "pricetick" in setting:
            self.pricetick_line.setText(str(setting["pricetick"]))
        if "capital" in setting:
            self.capital_line.setText(str(setting["capital"]))

    def on_strategy_changed(self, class_name: str) -> None:
        """切换策略时恢复该策略配置；没有记录时回到界面初始值。"""
        if not class_name:
            return

        all_settings: dict = load_json(self.setting_filename)
        self._apply_strategy_setting(all_settings.get(class_name) or self.default_setting)

    def register_event(self) -> None:
        """注册事件"""
        self.signal_log.connect(self.process_log_event)
        self.signal_backtesting_finished.connect(self.process_backtesting_finished_event)
        self.signal_optimization_finished.connect(self.process_optimization_finished_event)

        self.event_engine.register(EVENT_BACKTESTER_LOG, self.signal_log.emit)
        self.event_engine.register(EVENT_BACKTESTER_BACKTESTING_FINISHED, self.signal_backtesting_finished.emit)
        self.event_engine.register(EVENT_BACKTESTER_OPTIMIZATION_FINISHED, self.signal_optimization_finished.emit)

    def process_log_event(self, event: Event) -> None:
        """处理日志事件"""
        msg = event.data
        self.write_log(msg)

    def write_log(self, msg: str) -> None:
        """写入日志"""
        timestamp: str = datetime.now().strftime("%H:%M:%S")
        msg = f"{timestamp}\t{msg}"
        self.log_monitor.append(msg)
        # 自动滚动到底部
        self.log_monitor.verticalScrollBar().setValue(
            self.log_monitor.verticalScrollBar().maximum()
        )

    def process_backtesting_finished_event(self, event: Event) -> None:
        """处理回测完成事件"""
        statistics: dict = self.backtester_engine.get_result_statistics()

        # 更新核心指标和完整指标
        self.core_metrics_widget.update_core_metrics(statistics)
        self.metrics_widget.set_data(statistics)

        # 更新月度统计和区间统计图表 - 使用MetricsGridWidget的create方法
        # 清除旧的图表
        for i in reversed(range(self.monthly_chart_container.layout().count())):
            self.monthly_chart_container.layout().itemAt(i).widget().deleteLater()
        for i in reversed(range(self.interval_chart_container.layout().count())):
            self.interval_chart_container.layout().itemAt(i).widget().deleteLater()

        # 创建临时MetricsGridWidget来生成图表
        temp_metrics_widget = MetricsGridWidget()
        temp_metrics_widget.df_statistics = self.backtester_engine.get_result_df()

        # 生成月度统计图表
        if "monthly_statistics" in statistics and statistics["monthly_statistics"] is not None:
            monthly_stats = statistics["monthly_statistics"]
            # 转换DataFrame为图表期望的格式
            if hasattr(monthly_stats, 'to_dict') and not monthly_stats.empty:
                monthly_stats_dict = {}
                for _, row in monthly_stats.iterrows():
                    month_key = str(row.get('month', ''))
                    # 解析win_rate字符串（去除%并转换为小数）
                    win_rate_str = row.get('win_rate', '0%')
                    if isinstance(win_rate_str, str) and '%' in win_rate_str:
                        win_rate = float(win_rate_str.replace('%', '')) / 100
                    else:
                        win_rate = float(win_rate_str) if win_rate_str else 0

                    monthly_stats_dict[month_key] = {
                        'return': row.get('total_pnl', 0),  # total_pnl作为return
                        'win_rate': win_rate,
                    }
            else:
                monthly_stats_dict = monthly_stats if isinstance(monthly_stats, dict) else {}

            monthly_chart = temp_metrics_widget.create_monthly_chart(monthly_stats_dict)
            if monthly_chart and "月度统计图表" in monthly_chart:
                canvas = monthly_chart["月度统计图表"]
                self.monthly_chart_container.layout().addWidget(canvas)

        # 生成区间统计图表
        if "interval_statistics" in statistics and statistics["interval_statistics"] is not None:
            interval_stats = statistics["interval_statistics"]
            # 转换DataFrame为图表期望的格式
            if hasattr(interval_stats, 'to_dict') and not interval_stats.empty:
                interval_stats_dict = {}
                for _, row in interval_stats.iterrows():
                    interval_key = str(row.get('interval_start', ''))
                    # 解析win_rate字符串（去除%并转换为小数）
                    win_rate_str = row.get('win_rate', '0%')
                    if isinstance(win_rate_str, str) and '%' in win_rate_str:
                        win_rate = float(win_rate_str.replace('%', '')) / 100
                    else:
                        win_rate = float(win_rate_str) if win_rate_str else 0

                    interval_stats_dict[interval_key] = {
                        'return': row.get('total_pnl', 0),  # total_pnl作为return
                        'win_rate': win_rate,
                        'trades': int(row.get('total_trades', 0)),
                    }
            else:
                interval_stats_dict = interval_stats if isinstance(interval_stats, dict) else {}

            interval_chart = temp_metrics_widget.create_interval_chart(interval_stats_dict)
            if interval_chart and "半小时区间统计图表" in interval_chart:
                canvas = interval_chart["半小时区间统计图表"]
                self.interval_chart_container.layout().addWidget(canvas)

        # 更新表格数据
        self.update_tables()

        # 更新图表
        self.update_charts()

        # 启用相关按钮
        self.candle_button.setEnabled(True)
        # 注意：result_button只在优化完成后才启用，回测完成不启用

    def process_optimization_finished_event(self, event: Event) -> None:
        """处理优化完成事件"""
        self.result_button.setEnabled(True)

    def update_tables(self) -> None:
        """更新表格数据"""
        # 更新成交记录表格
        trades = self.backtester_engine.get_all_trades()
        self.update_trades_table(trades)
        
        # 更新委托记录表格
        orders = self.backtester_engine.get_all_orders()
        self.update_orders_table(orders)
        
        # 更新每日盈亏表格
        daily_results = self.backtester_engine.get_all_daily_results()
        self.update_daily_table(daily_results)

    def update_trades_table(self, trades: list) -> None:
        """更新成交记录表格"""
        self.trades_table.setRowCount(len(trades))
        
        for row, trade in enumerate(trades):
            # 成交号
            tradeid_item = QtWidgets.QTableWidgetItem(str(trade.tradeid))
            self.trades_table.setItem(row, 0, tradeid_item)
            
            # 委托号
            orderid_item = QtWidgets.QTableWidgetItem(str(trade.orderid))
            self.trades_table.setItem(row, 1, orderid_item)
            
            # 代码
            symbol_item = QtWidgets.QTableWidgetItem(trade.symbol)
            self.trades_table.setItem(row, 2, symbol_item)
            
            # 交易所
            exchange_item = QtWidgets.QTableWidgetItem(trade.exchange.value)
            self.trades_table.setItem(row, 3, exchange_item)
            
            # 方向
            direction_item = QtWidgets.QTableWidgetItem(trade.direction.value)
            self.trades_table.setItem(row, 4, direction_item)
            
            # 开平
            offset_item = QtWidgets.QTableWidgetItem(trade.offset.value)
            self.trades_table.setItem(row, 5, offset_item)
            
            # 价格
            price_item = QtWidgets.QTableWidgetItem(f"{trade.price:.2f}")
            self.trades_table.setItem(row, 6, price_item)
            
            # 数量
            volume_item = QtWidgets.QTableWidgetItem(str(trade.volume))
            self.trades_table.setItem(row, 7, volume_item)
            
            # 时间
            time_item = QtWidgets.QTableWidgetItem(trade.datetime.strftime("%Y-%m-%d %H:%M:%S"))
            self.trades_table.setItem(row, 8, time_item)
            
            # 接口
            gateway_item = QtWidgets.QTableWidgetItem(trade.gateway_name)
            self.trades_table.setItem(row, 9, gateway_item)

    def update_orders_table(self, orders: list) -> None:
        """更新委托记录表格"""
        self.orders_table.setRowCount(len(orders))
        
        for row, order in enumerate(orders):
            # 委托号
            orderid_item = QtWidgets.QTableWidgetItem(str(order.orderid))
            self.orders_table.setItem(row, 0, orderid_item)
            
            # 代码
            symbol_item = QtWidgets.QTableWidgetItem(order.symbol)
            self.orders_table.setItem(row, 1, symbol_item)
            
            # 交易所
            exchange_item = QtWidgets.QTableWidgetItem(order.exchange.value)
            self.orders_table.setItem(row, 2, exchange_item)
            
            # 类型
            type_item = QtWidgets.QTableWidgetItem(order.type.value)
            self.orders_table.setItem(row, 3, type_item)
            
            # 方向
            direction_item = QtWidgets.QTableWidgetItem(order.direction.value)
            self.orders_table.setItem(row, 4, direction_item)
            
            # 开平
            offset_item = QtWidgets.QTableWidgetItem(order.offset.value)
            self.orders_table.setItem(row, 5, offset_item)
            
            # 价格
            price_item = QtWidgets.QTableWidgetItem(f"{order.price:.2f}")
            self.orders_table.setItem(row, 6, price_item)
            
            # 总数量
            volume_item = QtWidgets.QTableWidgetItem(str(order.volume))
            self.orders_table.setItem(row, 7, volume_item)
            
            # 已成交
            traded_item = QtWidgets.QTableWidgetItem(str(order.traded))
            self.orders_table.setItem(row, 8, traded_item)
            
            # 状态
            status_item = QtWidgets.QTableWidgetItem(order.status.value)
            self.orders_table.setItem(row, 9, status_item)
            
            # 时间
            time_item = QtWidgets.QTableWidgetItem(order.datetime.strftime("%Y-%m-%d %H:%M:%S"))
            self.orders_table.setItem(row, 10, time_item)
            
            # 接口
            gateway_item = QtWidgets.QTableWidgetItem(order.gateway_name)
            self.orders_table.setItem(row, 11, gateway_item)

    def update_daily_table(self, daily_results: list) -> None:
        """更新每日盈亏表格"""
        self.daily_table.setRowCount(len(daily_results))
        
        for row, result in enumerate(daily_results):
            # 日期
            date_item = QtWidgets.QTableWidgetItem(result.date.strftime("%Y-%m-%d"))
            self.daily_table.setItem(row, 0, date_item)
            
            # 成交笔数
            trade_count_item = QtWidgets.QTableWidgetItem(str(result.trade_count))
            self.daily_table.setItem(row, 1, trade_count_item)
            
            # 开盘持仓
            start_pos_item = QtWidgets.QTableWidgetItem(str(result.start_pos))
            self.daily_table.setItem(row, 2, start_pos_item)
            
            # 收盘持仓
            end_pos_item = QtWidgets.QTableWidgetItem(str(result.end_pos))
            self.daily_table.setItem(row, 3, end_pos_item)
            
            # 成交额
            turnover_item = QtWidgets.QTableWidgetItem(f"{result.turnover:.2f}")
            self.daily_table.setItem(row, 4, turnover_item)
            
            # 手续费
            commission_item = QtWidgets.QTableWidgetItem(f"{result.commission:.2f}")
            self.daily_table.setItem(row, 5, commission_item)
            
            # 滑点
            slippage_item = QtWidgets.QTableWidgetItem(f"{result.slippage:.2f}")
            self.daily_table.setItem(row, 6, slippage_item)
            
            # 交易盈亏
            trading_pnl_item = QtWidgets.QTableWidgetItem(f"{result.trading_pnl:.2f}")
            if result.trading_pnl > 0:
                trading_pnl_item.setForeground(QtGui.QColor("#ff4444"))  # 红色表示盈利
            elif result.trading_pnl < 0:
                trading_pnl_item.setForeground(QtGui.QColor("#00aa00"))  # 绿色表示亏损
            self.daily_table.setItem(row, 7, trading_pnl_item)
            
            # 持仓盈亏
            holding_pnl_item = QtWidgets.QTableWidgetItem(f"{result.holding_pnl:.2f}")
            if result.holding_pnl > 0:
                holding_pnl_item.setForeground(QtGui.QColor("#ff4444"))  # 红色表示盈利
            elif result.holding_pnl < 0:
                holding_pnl_item.setForeground(QtGui.QColor("#00aa00"))  # 绿色表示亏损
            self.daily_table.setItem(row, 8, holding_pnl_item)
            
            # 总盈亏
            total_pnl_item = QtWidgets.QTableWidgetItem(f"{result.total_pnl:.2f}")
            if result.total_pnl > 0:
                total_pnl_item.setForeground(QtGui.QColor("#ff4444"))  # 红色表示盈利
            elif result.total_pnl < 0:
                total_pnl_item.setForeground(QtGui.QColor("#00aa00"))  # 绿色表示亏损
            self.daily_table.setItem(row, 9, total_pnl_item)
            
            # 净盈亏
            net_pnl_item = QtWidgets.QTableWidgetItem(f"{result.net_pnl:.2f}")
            if result.net_pnl > 0:
                net_pnl_item.setForeground(QtGui.QColor("#ff4444"))  # 红色表示盈利
            elif result.net_pnl < 0:
                net_pnl_item.setForeground(QtGui.QColor("#00aa00"))  # 绿色表示亏损
            self.daily_table.setItem(row, 10, net_pnl_item)

    def update_charts(self) -> None:
        """更新图表数据"""
        # 获取回测结果数据
        df = self.backtester_engine.get_result_df()
        if df is not None and not df.empty:
            # 更新所有图表的数据
            self.chart1.update_chart_data(df)
            self.chart2.update_chart_data(df)
            self.chart3.update_chart_data(df)
            self.chart4.update_chart_data(df)

    def start_backtesting(self) -> None:
        """开始回测"""
        # 确保引擎已初始化（延迟初始化）
        self.ensure_engine_initialized()

        class_name: str = self.class_combo.currentText()
        if not class_name:
            self.write_log(_("请选择要回测的策略"))
            return

        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        start: datetime = self.start_date_edit.dateTime().toPython()
        end: datetime = self.end_date_edit.dateTime().toPython()
        rate: float = float(self.rate_line.text())
        slippage: float = float(self.slippage_line.text())
        size: float = float(self.size_line.text())
        pricetick: float = float(self.pricetick_line.text())
        capital: float = float(self.capital_line.text())

        # Check validity of vt_symbol
        if "." not in vt_symbol:
            self.write_log(_("本地代码缺失交易所后缀，请检查"))
            return

        __, exchange_str = vt_symbol.split(".")
        if exchange_str not in Exchange.__members__:
            self.write_log(_("本地代码的交易所后缀不正确，请检查"))
            return

        # Save backtesting parameters (按策略名分组存储)
        backtesting_setting: dict = {
            "vt_symbol": vt_symbol,
            "interval": interval,
            "start": start.strftime("%Y-%m-%d"),
            "rate": rate,
            "slippage": slippage,
            "size": size,
            "pricetick": pricetick,
            "capital": capital
        }
        all_settings: dict = load_json(self.setting_filename)
        all_settings[class_name] = backtesting_setting
        all_settings["_last_used"] = class_name
        save_json(self.setting_filename, all_settings)

        # Get strategy setting
        from .widget import BacktestingSettingEditor
        old_setting: dict = self.settings[class_name]
        dialog: BacktestingSettingEditor = BacktestingSettingEditor(class_name, old_setting, vt_symbol)
        i: int = dialog.exec()
        if i != dialog.DialogCode.Accepted:
            return

        new_setting: dict = dialog.get_setting()
        self.settings[class_name] = new_setting

        result: bool = self.backtester_engine.start_backtesting(
            class_name,
            vt_symbol,
            interval,
            start,
            end,
            rate,
            slippage,
            size,
            pricetick,
            capital,
            new_setting
        )

        if result:
            # 清除之前的数据
            self.core_metrics_widget.update_core_metrics({})
            self.metrics_widget.clear_data()
            # 清除图表容器中的内容
            for i in reversed(range(self.monthly_chart_container.layout().count())):
                self.monthly_chart_container.layout().itemAt(i).widget().deleteLater()
            for i in reversed(range(self.interval_chart_container.layout().count())):
                self.interval_chart_container.layout().itemAt(i).widget().deleteLater()

            # 禁用按钮
            self.candle_button.setEnabled(False)
            # result_button在回测时不需要禁用，因为它只与优化相关

    def save_backtesting_setting(self) -> None:
        """保存回测设置（按策略名分组存储）"""
        class_name: str = self.class_combo.currentText()
        setting: dict = {
            "vt_symbol": self.symbol_line.text(),
            "interval": self.interval_combo.currentText(),
            "start": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "end": self.end_date_edit.date().toString("yyyy-MM-dd"),
            "rate": float(self.rate_line.text()),
            "slippage": float(self.slippage_line.text()),
            "size": float(self.size_line.text()),
            "pricetick": float(self.pricetick_line.text()),
            "capital": float(self.capital_line.text()),
        }
        all_settings: dict = load_json(self.setting_filename)
        all_settings[class_name] = setting
        all_settings["_last_used"] = class_name
        save_json(self.setting_filename, all_settings)

    def start_optimization(self) -> None:
        """开始参数优化"""
        # 确保引擎已初始化（延迟初始化）
        self.ensure_engine_initialized()

        class_name: str = self.class_combo.currentText()
        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        start: datetime = self.start_date_edit.dateTime().toPython()
        end: datetime = self.end_date_edit.dateTime().toPython()
        rate: float = float(self.rate_line.text())
        slippage: float = float(self.slippage_line.text())
        size: float = float(self.size_line.text())
        pricetick: float = float(self.pricetick_line.text())
        capital: float = float(self.capital_line.text())

        from .widget import OptimizationSettingEditor
        parameters: dict = self.settings[class_name]
        dialog: OptimizationSettingEditor = OptimizationSettingEditor(class_name, parameters)
        i: int = dialog.exec()
        if i != dialog.DialogCode.Accepted:
            return

        optimization_setting, use_ga, max_workers = dialog.get_setting()
        self.target_display = dialog.target_display

        self.backtester_engine.start_optimization(
            class_name,
            vt_symbol,
            interval,
            start,
            end,
            rate,
            slippage,
            size,
            pricetick,
            capital,
            optimization_setting,
            use_ga,
            max_workers
        )

        self.result_button.setEnabled(False)

    def show_optimization_result(self) -> None:
        """显示优化结果"""
        result_values: list = self.backtester_engine.get_result_values()

        # 使用增强的优化结果监控器
        try:
            from .enhanced_widget import EnhancedOptimizationResultMonitor
            dialog = EnhancedOptimizationResultMonitor(result_values, self.target_display)
        except ImportError:
            from .widget import OptimizationResultMonitor
            dialog = OptimizationResultMonitor(result_values, self.target_display)
        
        dialog.exec_()

    def start_downloading(self) -> None:
        """开始下载数据"""
        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        start_date: QtCore.QDate = self.start_date_edit.date()
        end_date: QtCore.QDate = self.end_date_edit.date()

        start: datetime = datetime(
            start_date.year(),
            start_date.month(),
            start_date.day(),
        )
        start = start.replace(tzinfo=DB_TZ)

        end: datetime = datetime(
            end_date.year(),
            end_date.month(),
            end_date.day(),
            23,
            59,
            59,
        )
        end = end.replace(tzinfo=DB_TZ)

        self.backtester_engine.start_downloading(
            vt_symbol,
            interval,
            start,
            end
        )

    def reload_strategy_class(self) -> None:
        """重载策略类"""
        # 确保引擎已初始化（延迟初始化）
        self.ensure_engine_initialized()

        self.backtester_engine.reload_strategy_class()

        current_strategy_name: str = self.class_combo.currentText()

        self.class_combo.clear()
        self.init_strategy_settings()

        ix: int = self.class_combo.findText(current_strategy_name)
        self.class_combo.setCurrentIndex(ix)

    def show_candle_chart(self) -> None:
        """显示K线图表"""
        from .widget import CandleChartDialog
        if not hasattr(self, 'candle_dialog'):
            self.candle_dialog: CandleChartDialog = CandleChartDialog()

        if not self.candle_dialog.is_updated():
            history: list = self.backtester_engine.get_history_data()
            self.candle_dialog.update_history(history)

            trades: list[TradeData] = self.backtester_engine.get_all_trades()
            self.candle_dialog.update_trades(trades)

        self.candle_dialog.exec_()

    def show_backtesting_trades(self) -> None:
        """显示成交记录"""
        from .widget import BacktestingResultDialog, BacktestingTradeMonitor
        if not self.trade_dialog:
            self.trade_dialog = BacktestingResultDialog(
                self.main_engine,
                self.event_engine,
                _("回测成交记录"),
                BacktestingTradeMonitor
            )
        
        if not self.trade_dialog.is_updated():
            trades: list[TradeData] = self.backtester_engine.get_all_trades()
            self.trade_dialog.update_data(trades)

        self.trade_dialog.exec_()

    def show_backtesting_orders(self) -> None:
        """显示委托记录"""
        from .widget import BacktestingResultDialog, BacktestingOrderMonitor
        if not self.order_dialog:
            self.order_dialog = BacktestingResultDialog(
                self.main_engine,
                self.event_engine,
                _("回测委托记录"),
                BacktestingOrderMonitor
            )
        
        if not self.order_dialog.is_updated():
            orders: list[OrderData] = self.backtester_engine.get_all_orders()
            self.order_dialog.update_data(orders)

        self.order_dialog.exec_()

    def show_daily_results(self) -> None:
        """显示每日盈亏"""
        from .widget import BacktestingResultDialog, DailyResultMonitor
        if not self.daily_dialog:
            self.daily_dialog = BacktestingResultDialog(
                self.main_engine,
                self.event_engine,
                _("回测每日盈亏"),
                DailyResultMonitor
            )
        
        if not self.daily_dialog.is_updated():
            results: list[DailyResult] = self.backtester_engine.get_all_daily_results()
            self.daily_dialog.update_data(results)

        self.daily_dialog.exec_()


class CoreMetricsWidget(QtWidgets.QWidget):
    """核心指标概览组件"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """初始化界面"""
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建核心指标网格 - 优化后的紧凑布局
        self.grid_layout = QtWidgets.QGridLayout()
        self.grid_layout.setSpacing(10)  # 卡片之间的间距
        self.grid_layout.setContentsMargins(0, 0, 0, 0)  # 整体布局边距

        # 创建占位符卡片
        self.create_placeholder_cards()

        container = QtWidgets.QWidget()
        container.setLayout(self.grid_layout)

        layout.addWidget(container)
        layout.addStretch()
        self.setLayout(layout)
        
    def create_placeholder_cards(self):
        """创建24个核心指标卡片 - 6x4统一网格布局（完整指标分组）"""
        # 第一行 - 收益指标
        self.create_minor_card(0, 0, "总收益率", "0.00%", False, "收益")
        self.create_minor_card(0, 1, "年化收益", "0.00%", False, "收益")
        self.create_minor_card(0, 2, "总盈亏", "0.00", False, "收益")
        self.create_minor_card(0, 3, "日均盈亏", "0.00", False, "收益")

        # 第二行 - 风险指标
        self.create_minor_card(1, 0, "最大回撤", "0.00", False, "风险")
        self.create_minor_card(1, 1, "百分比最大回撤", "0.00%", False, "风险")
        self.create_minor_card(1, 2, "最大回撤天数", "0", False, "风险")
        self.create_minor_card(1, 3, "综合评分", "0.0000", False, "风险")

        # 第三行 - 风险调整收益
        self.create_minor_card(2, 0, "夏普比率", "0.00", False, "风险调整")
        self.create_minor_card(2, 1, "索提诺比率", "0.00", False, "风险调整")
        self.create_minor_card(2, 2, "卡尔马比率", "0.00", False, "风险调整")
        self.create_minor_card(2, 3, "收益回撤比", "0.00", False, "风险调整")

        # 第四行 - 风险调整收益（续）+ 交易统计
        self.create_minor_card(3, 0, "EWM夏普", "0.00", False, "风险调整")
        self.create_minor_card(3, 1, "胜率", "0.00%", False, "交易")
        self.create_minor_card(3, 2, "盈亏比", "0.00", False, "交易")
        self.create_minor_card(3, 3, "获利因子", "0.00", False, "交易")

        # 第五行 - 交易统计
        self.create_minor_card(4, 0, "总成交笔数", "0", False, "交易")
        self.create_minor_card(4, 1, "多头笔数", "0", False, "交易")
        self.create_minor_card(4, 2, "空头笔数", "0", False, "交易")
        self.create_minor_card(4, 3, "平均每笔盈亏", "0.00", False, "交易")

        # 第六行 - 高级交易统计
        self.create_minor_card(5, 0, "最大连续盈利次数", "0", False, "交易")
        self.create_minor_card(5, 1, "最大连续亏损次数", "0", False, "交易")
        self.create_minor_card(5, 2, "最优仓位比例", "0.00%", False, "交易")
        self.create_minor_card(5, 3, "平均持仓时间", "0.00天", False, "交易")

    def create_major_card(self, row: int, col: int, name: str, value: str, highlight: bool, colspan: int, rowspan: int):
        """创建大卡片 - 用于核心指标"""
        card = QtWidgets.QWidget()
        card.setFixedHeight(120)  # 大卡片高度

        # 设置样式 - 渐变背景 + 阴影效果
        base_style = """
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3a3a3a, stop:1 #2a2a2a);
                border: 2px solid #666;
                border-radius: 12px;
                padding: 20px;
            }
            QWidget:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #4a4a4a, stop:1 #3a3a3a);
                border-color: #007acc;
            }
        """

        if highlight:
            base_style = """
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(0, 122, 204, 0.3), stop:1 #2a2a2a);
                    border: 2px solid #007acc;
                    border-radius: 12px;
                    padding: 20px;
                }
                QWidget:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(0, 122, 204, 0.4), stop:1 #333);
                    border-color: #0099ff;
                }
            """

        card.setStyleSheet(base_style)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 指标名称 - 更大字体
        name_label = QtWidgets.QLabel(name)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #bbb;
                font-weight: 600;
                background: transparent;
                border: none;
                padding: 2px;
                letter-spacing: 1px;
            }
        """)
        name_label.setAlignment(QtCore.Qt.AlignLeft)
        name_label.setWordWrap(True)

        # 指标值 - 更大字体 + 发光效果
        value_label = QtWidgets.QLabel(value)
        base_value_style = """
            QLabel {
                font-size: 32px;
                font-weight: 900;
                background: transparent;
                border: none;
                line-height: 1;
                padding: 4px;
            }
        """

        # 使用智能分级着色系统
        color = self.get_metric_color(name, value)
        value_label.setStyleSheet(base_value_style + f"color: {color};")

        value_label.setAlignment(QtCore.Qt.AlignLeft)
        value_label.setWordWrap(True)

        layout.addWidget(name_label)
        layout.addStretch()
        layout.addWidget(value_label)
        card.setLayout(layout)

        # 存储标签引用和卡片类型
        setattr(card, 'name_label', name_label)
        setattr(card, 'value_label', value_label)
        setattr(card, 'metric_name', name)
        setattr(card, 'card_type', 'major')  # 标记为大卡片

        self.grid_layout.addWidget(card, row, col, rowspan, colspan)

    def create_minor_card(self, row: int, col: int, name: str, value: str, highlight: bool, category: str = ""):
        """创建小卡片 - 用于次要指标"""
        card = QtWidgets.QWidget()
        card.setFixedHeight(60) 

        # 设置样式
        base_style = """
            QWidget {
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 10px;
            }
            QWidget:hover {
                background-color: #333;
                border-color: #555;
            }
        """

        card.setStyleSheet(base_style)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 顶部水平布局：左边是指标名称，右边是类型标签
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        # 指标名称
        name_label = QtWidgets.QLabel(name)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                color: #999;
                font-weight: 600;
                background: transparent;
                border: none;
                padding: 1px;
            }
        """)
        name_label.setAlignment(QtCore.Qt.AlignLeft)
        name_label.setWordWrap(True)

        # 类型标签（右上角小标签）
        if category:
            category_label = QtWidgets.QLabel(category)
            category_label.setStyleSheet("""
                QLabel {
                    font-size: 10px;
                    color: #666;
                    background: rgba(255, 255, 255, 0.05);
                    padding: 2px 6px;
                    border-radius: 8px;
                    font-weight: 600;
                    border: none;
                }
            """)
            category_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)

        header_layout.addWidget(name_label)
        if category:
            header_layout.addStretch()
            header_layout.addWidget(category_label)

        # 指标值
        value_label = QtWidgets.QLabel(value)
        base_style = """
            QLabel {
                font-size: 18px;
                font-weight: bold;
                background: transparent;
                border: none;
                line-height: 1;
                padding: 1px;
            }
        """

        # 使用智能分级着色系统
        color = self.get_metric_color(name, value)
        value_label.setStyleSheet(base_style + f"color: {color};")

        value_label.setAlignment(QtCore.Qt.AlignLeft)
        value_label.setWordWrap(True)

        # 等级说明标签（右下角）
        grade_text = self.get_metric_grade_text(name, value, color)
        grade_label = QtWidgets.QLabel(grade_text)
        grade_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                color: #888;
                font-weight: 500;
                background: transparent;
                border: none;
                padding: 1px;
            }
        """)
        grade_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom)

        # 底部水平布局：左边是数值，右边是等级说明
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)
        bottom_layout.addWidget(value_label)
        bottom_layout.addStretch()
        bottom_layout.addWidget(grade_label)

        layout.addLayout(header_layout)
        layout.addStretch()
        layout.addLayout(bottom_layout)
        card.setLayout(layout)

        # 存储标签引用和卡片类型
        setattr(card, 'name_label', name_label)
        setattr(card, 'value_label', value_label)
        setattr(card, 'grade_label', grade_label)
        setattr(card, 'metric_name', name)
        setattr(card, 'card_type', 'minor')  # 标记为小卡片

        self.grid_layout.addWidget(card, row, col)
    
    def create_core_metric_card(self, name: str, value: str, highlight: bool = False) -> QtWidgets.QWidget:
        """创建核心指标卡片 - 优化后的紧凑设计"""
        card = QtWidgets.QWidget()
        card.setFixedHeight(60)  # 从80px减小到60px

        # 设置样式 - 减小内边距
        base_style = """
            QWidget {
                background-color: #333;
                border: 2px solid #555;
                border-radius: 8px;
                padding: 12px;
            }
            QWidget:hover {
                background-color: #3a3a3a;
                border-color: #666;
            }
        """

        if highlight:
            base_style = """
                QWidget {
                    background: linear-gradient(135deg, #333 0%, #3a3a3a 100%);
                    border: 2px solid #007acc;
                    border-radius: 8px;
                    padding: 12px;
                }
                QWidget:hover {
                    border-color: #0099ff;
                }
            """

        card.setStyleSheet(base_style)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)  # 从8px减小到4px

        # 指标名称 - 减小字体
        name_label = QtWidgets.QLabel(name)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #ddd;
                font-weight: 600;
                background: transparent;
                border: none;
                padding: 1px;
            }
        """)
        name_label.setAlignment(QtCore.Qt.AlignCenter)
        name_label.setWordWrap(True)

        # 指标值 - 减小字体并使用智能分级着色
        value_label = QtWidgets.QLabel(value)
        base_style = """
            QLabel {
                font-size: 18px;
                font-weight: bold;
                background: transparent;
                border: none;
                line-height: 1.1;
                padding: 1px;
            }
        """

        # 使用智能分级着色系统
        color = self.get_metric_color(name, value)
        value_label.setStyleSheet(base_style + f"color: {color};")

        value_label.setAlignment(QtCore.Qt.AlignCenter)
        value_label.setWordWrap(True)

        layout.addWidget(name_label)
        layout.addWidget(value_label)
        card.setLayout(layout)

        # 存储标签引用以便后续更新
        setattr(card, 'name_label', name_label)
        setattr(card, 'value_label', value_label)
        setattr(card, 'metric_name', name)

        return card

    def get_metric_grade_text(self, metric_name: str, value_str: str, color: str) -> str:
        """
        根据指标名称、值和颜色，返回等级说明文本
        例如: "深红 - 优秀 (>20%)" 或 "深绿 - 优秀 (<5%)"
        """
        try:
            # 尝试解析数值
            value_str_clean = value_str.replace('%', '').replace(',', '').replace('天', '')
            value = float(value_str_clean)
        except (ValueError, AttributeError):
            return ""

        # 根据颜色确定等级名称
        color_grade_map = {
            "#ff2222": "深红 - 优秀",
            "#ff4444": "浅红 - 良好",
            "#ffffff": "白色 - 中性",
            "#00aa00": "浅绿 - 一般",
            "#008800": "深绿 - 较差"
        }

        grade_text = color_grade_map.get(color, "")
        if not grade_text:
            return ""

        # 根据指标名称和数值，确定标准值说明
        standard_text = ""

        # 收益类指标（越高越好，红色为优）
        if metric_name == "总收益率":
            if color == "#ff2222":
                standard_text = "(>20%)"
            elif color == "#ff4444":
                standard_text = "(>10%)"
            elif color == "#ffffff":
                standard_text = "(±10%)"
            elif color == "#00aa00":
                standard_text = "(<-10%)"
            else:
                standard_text = "(<-20%)"

        elif metric_name == "年化收益":
            if color == "#ff2222":
                standard_text = "(>15%)"
            elif color == "#ff4444":
                standard_text = "(>5%)"
            elif color == "#ffffff":
                standard_text = "(±5%)"
            elif color == "#00aa00":
                standard_text = "(<-5%)"
            else:
                standard_text = "(<-15%)"

        elif metric_name in ["总盈亏", "日均盈亏", "平均每笔盈亏"]:
            if color == "#ff2222":
                standard_text = "(>1000)"
            elif color == "#ff4444":
                standard_text = "(>100)"
            elif color == "#ffffff":
                standard_text = "(±100)"
            elif color == "#00aa00":
                standard_text = "(<-100)"
            else:
                standard_text = "(<-1000)"

        # 风险类指标（越小越好，绿色为优）
        elif metric_name in ["最大回撤", "百分比最大回撤"]:
            if color == "#008800":
                standard_text = "(<5%)"
            elif color == "#00aa00":
                standard_text = "(<10%)"
            elif color == "#ffffff":
                standard_text = "(10-15%)"
            elif color == "#ff4444":
                standard_text = "(>15%)"
            else:
                standard_text = "(>25%)"

        elif metric_name == "最大回撤天数":
            # 注意：回撤天数的颜色逻辑是绿色为优
            if color == "#008800":
                standard_text = "(<10天)"
            elif color == "#00aa00":
                standard_text = "(<20天)"
            elif color == "#ffffff":
                standard_text = "(20-30天)"
            elif color == "#ff4444":
                standard_text = "(>30天)"
            else:
                standard_text = "(>60天)"

        # 风险调整收益类（越高越好，红色为优）
        elif metric_name in ["夏普比率", "卡尔马比率", "收益回撤比", "EWM夏普"]:
            if color == "#ff2222":
                standard_text = "(>2.0)"
            elif color == "#ff4444":
                standard_text = "(>1.0)"
            elif color == "#ffffff":
                standard_text = "(>0.5)"
            elif color == "#00aa00":
                standard_text = "(>0)"
            else:
                standard_text = "(≤0)"

        elif metric_name == "索提诺比率":
            if color == "#ff2222":
                standard_text = "(>3.0)"
            elif color == "#ff4444":
                standard_text = "(>1.5)"
            elif color == "#ffffff":
                standard_text = "(>0.75)"
            elif color == "#00aa00":
                standard_text = "(>0)"
            else:
                standard_text = "(≤0)"

        elif metric_name == "综合评分":
            if color == "#ff2222":
                standard_text = "(>0.8)"
            elif color == "#ff4444":
                standard_text = "(>0.6)"
            elif color == "#ffffff":
                standard_text = "(>0.4)"
            elif color == "#00aa00":
                standard_text = "(>0.2)"
            else:
                standard_text = "(≤0.2)"

        # 交易统计类
        elif metric_name == "胜率":
            if color == "#ff2222":
                standard_text = "(>60%)"
            elif color == "#ff4444":
                standard_text = "(>50%)"
            elif color == "#ffffff":
                standard_text = "(40-50%)"
            elif color == "#00aa00":
                standard_text = "(30-40%)"
            else:
                standard_text = "(<30%)"

        elif metric_name in ["盈亏比", "获利因子"]:
            if color == "#ff2222":
                standard_text = "(>2.5)"
            elif color == "#ff4444":
                standard_text = "(>1.5)"
            elif color == "#ffffff":
                standard_text = "(1.0-1.5)"
            elif color == "#00aa00":
                standard_text = "(0.5-1.0)"
            else:
                standard_text = "(<0.5)"

        elif metric_name == "最大连续盈利次数":
            if color == "#ff2222":
                standard_text = "(>10次)"
            elif color == "#ff4444":
                standard_text = "(>5次)"
            elif color == "#ffffff":
                standard_text = "(3-5次)"
            elif color == "#00aa00":
                standard_text = "(2次)"
            else:
                standard_text = "(≤1次)"

        elif metric_name == "最大连续亏损次数":
            if color == "#008800":
                standard_text = "(≤1次)"
            elif color == "#00aa00":
                standard_text = "(<3次)"
            elif color == "#ffffff":
                standard_text = "(3-5次)"
            elif color == "#ff4444":
                standard_text = "(>5次)"
            else:
                standard_text = "(>10次)"

        # 中性指标不显示标准
        elif metric_name in ["总成交笔数", "多头笔数", "空头笔数", "最优仓位比例", "平均持仓时间"]:
            return ""

        return f"{grade_text} {standard_text}"

    def get_metric_color(self, metric_name: str, value_str: str) -> str:
        """
        智能分级着色系统 - 根据指标值返回对应颜色

        颜色分级（中国市场：红涨绿跌）：
        - 深红 #ff2222：优秀（>20%收益率，>2.0夏普，>60%胜率，>0.8评分）
        - 浅红 #ff4444：良好（>5%收益率，>1.0夏普，>50%胜率，>0.6评分）
        - 白色 #ffffff：中性（±5%收益率，0.5-1.0夏普，40-50%胜率，0.4-0.6评分）
        - 浅绿 #00aa00：一般（<-5%收益率，≤0.5夏普，<40%胜率，≤0.4评分）
        - 深绿 #008800：较差（<-20%收益率，<0夏普，<30%胜率，<0.2评分）

        特殊处理：
        - 最大回撤：反向逻辑（越小越好），用绿色表示
        """
        try:
            # 提取数值
            numeric_str = value_str.replace('%', '').replace(',', '').replace('N/A', '0')
            if not numeric_str:
                return "#ffffff"
            value = float(numeric_str)

            # 收益类指标（总收益率、年化收益）- 深红>20%, 浅红>5%, 白色±5%, 浅绿<-5%, 深绿<-20%
            if metric_name in ["总收益率", "年化收益"]:
                if value > 20:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 5:
                    return "#ff4444"  # 浅红 - 良好
                elif value >= -5:
                    return "#ffffff"  # 白色 - 中性
                elif value >= -20:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 最大回撤 - 特殊处理：越小越好，用绿色系（使用绝对值）
            # 深绿<5%, 浅绿<10%, 白色10-15%, 浅红>15%, 深红>25%
            elif metric_name == "最大回撤":
                abs_value = abs(value)  # 使用绝对值
                if abs_value < 5:
                    return "#008800"  # 深绿 - 优秀（回撤小）
                elif abs_value < 10:
                    return "#00aa00"  # 浅绿 - 良好
                elif abs_value <= 15:
                    return "#ffffff"  # 白色 - 中性
                elif abs_value <= 25:
                    return "#ff4444"  # 浅红 - 一般
                else:
                    return "#ff2222"  # 深红 - 较差（回撤大）

            # 夏普比率、卡尔马比率、收益回撤比 - 深红>2.0, 浅红>1.0, 白色>0.5, 浅绿≤0.5, 深绿≤0
            elif metric_name in ["夏普比率", "卡尔马比率", "收益回撤比"]:
                if value > 2.0:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 1.0:
                    return "#ff4444"  # 浅红 - 良好
                elif value > 0.5:
                    return "#ffffff"  # 白色 - 中性
                elif value > 0:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 胜率 - 深红>60%, 浅红>50%, 白色40-50%, 浅绿<40%, 深绿<30%
            elif metric_name == "胜率":
                if value > 60:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 50:
                    return "#ff4444"  # 浅红 - 良好
                elif value >= 40:
                    return "#ffffff"  # 白色 - 中性
                elif value >= 30:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 盈亏比 - 深红>2.5, 浅红>1.5, 白色1.0-1.5, 浅绿<1.0, 深绿<0.5
            elif metric_name == "盈亏比":
                if value > 2.5:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 1.5:
                    return "#ff4444"  # 浅红 - 良好
                elif value >= 1.0:
                    return "#ffffff"  # 白色 - 中性
                elif value >= 0.5:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 综合评分 - 深红>0.8, 浅红>0.6, 白色>0.4, 浅绿≤0.4, 深绿≤0.2
            elif metric_name == "综合评分":
                if value > 0.8:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 0.6:
                    return "#ff4444"  # 浅红 - 良好
                elif value > 0.4:
                    return "#ffffff"  # 白色 - 中性
                elif value > 0.2:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 月均收益/日均收益 - 深红>2%, 浅红>0.5%, 白色±0.5%, 浅绿<-0.5%, 深绿<-2%
            elif metric_name in ["月均收益", "日均收益"]:
                if value > 2:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 0.5:
                    return "#ff4444"  # 浅红 - 良好
                elif value >= -0.5:
                    return "#ffffff"  # 白色 - 中性
                elif value >= -2:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 回撤天数 - 深绿<10天, 浅绿<20天, 白色20-30天, 浅红>30天, 深红>60天
            elif metric_name == "回撤天数":
                if value < 10:
                    return "#008800"  # 深绿 - 优秀（恢复快）
                elif value < 20:
                    return "#00aa00"  # 浅绿 - 良好
                elif value <= 30:
                    return "#ffffff"  # 白色 - 中性
                elif value <= 60:
                    return "#ff4444"  # 浅红 - 一般
                else:
                    return "#ff2222"  # 深红 - 较差（恢复慢）

            # 收益波动/下行标准差 - 深绿<5%, 浅绿<10%, 白色10-15%, 浅红>15%, 深红>25%（使用绝对值）
            elif metric_name in ["收益波动", "下行标准差"]:
                abs_value = abs(value)  # 使用绝对值
                if abs_value < 5:
                    return "#008800"  # 深绿 - 优秀（波动小）
                elif abs_value < 10:
                    return "#00aa00"  # 浅绿 - 良好
                elif abs_value <= 15:
                    return "#ffffff"  # 白色 - 中性
                elif abs_value <= 25:
                    return "#ff4444"  # 浅红 - 一般
                else:
                    return "#ff2222"  # 深红 - 较差（波动大）

            # 索提诺比率 - 深红>3.0, 浅红>1.5, 白色>0.75, 浅绿≤0.75, 深绿≤0
            elif metric_name == "索提诺比率":
                if value > 3.0:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 1.5:
                    return "#ff4444"  # 浅红 - 良好
                elif value > 0.75:
                    return "#ffffff"  # 白色 - 中性
                elif value > 0:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 获利因子 - 深红>2.5, 浅红>1.5, 白色1.0-1.5, 浅绿<1.0, 深绿<0.5
            elif metric_name == "获利因子":
                if value > 2.5:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 1.5:
                    return "#ff4444"  # 浅红 - 良好
                elif value >= 1.0:
                    return "#ffffff"  # 白色 - 中性
                elif value >= 0.5:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 总交易次数、多头笔数、空头笔数 - 中性指标，不做颜色分级
            elif metric_name in ["总交易次数", "总成交笔数", "多头笔数", "空头笔数"]:
                return "#ffffff"  # 白色 - 中性

            # 总盈亏、日均盈亏、平均每笔盈亏 - 正盈利红色，负盈利绿色
            elif metric_name in ["总盈亏", "日均盈亏", "平均每笔盈亏"]:
                if value > 1000:
                    return "#ff2222"  # 深红 - 优秀（大额盈利）
                elif value > 100:
                    return "#ff4444"  # 浅红 - 良好
                elif value >= -100:
                    return "#ffffff"  # 白色 - 中性
                elif value >= -1000:
                    return "#00aa00"  # 浅绿 - 一般（小额亏损）
                else:
                    return "#008800"  # 深绿 - 较差（大额亏损）

            # 百分比最大回撤 - 与"最大回撤"相同逻辑，使用绝对值
            elif metric_name == "百分比最大回撤":
                abs_value = abs(value)
                if abs_value < 5:
                    return "#008800"  # 深绿 - 优秀（回撤小）
                elif abs_value < 10:
                    return "#00aa00"  # 浅绿 - 良好
                elif abs_value <= 15:
                    return "#ffffff"  # 白色 - 中性
                elif abs_value <= 25:
                    return "#ff4444"  # 浅红 - 一般
                else:
                    return "#ff2222"  # 深红 - 较差（回撤大）

            # EWM夏普 - 与夏普比率相同逻辑
            elif metric_name == "EWM夏普":
                if value > 2.0:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 1.0:
                    return "#ff4444"  # 浅红 - 良好
                elif value > 0.5:
                    return "#ffffff"  # 白色 - 中性
                elif value > 0:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 最大连续盈利次数 - 深红>10次, 浅红>5次, 白色3-5次, 浅绿<3次, 深绿≤1次
            elif metric_name == "最大连续盈利次数":
                if value > 10:
                    return "#ff2222"  # 深红 - 优秀
                elif value > 5:
                    return "#ff4444"  # 浅红 - 良好
                elif value >= 3:
                    return "#ffffff"  # 白色 - 中性
                elif value >= 2:
                    return "#00aa00"  # 浅绿 - 一般
                else:
                    return "#008800"  # 深绿 - 较差

            # 最大连续亏损次数 - 深绿≤1次, 浅绿<3次, 白色3-5次, 浅红>5次, 深红>10次
            elif metric_name == "最大连续亏损次数":
                if value <= 1:
                    return "#008800"  # 深绿 - 优秀（连续亏损少）
                elif value < 3:
                    return "#00aa00"  # 浅绿 - 良好
                elif value <= 5:
                    return "#ffffff"  # 白色 - 中性
                elif value <= 10:
                    return "#ff4444"  # 浅红 - 一般
                else:
                    return "#ff2222"  # 深红 - 较差（连续亏损多）

            # 最优仓位比例、平均持仓时间 - 中性指标，不做颜色分级
            elif metric_name in ["最优仓位比例", "平均持仓时间"]:
                return "#ffffff"  # 白色 - 中性

            # 默认白色
            return "#ffffff"

        except (ValueError, TypeError):
            return "#ffffff"
        
    def update_core_metrics(self, statistics: dict):
        """更新核心指标显示 - 使用智能分级着色系统"""
        if not statistics:
            return

        # 获取原始数据并正确处理百分比
        # vnpy返回的total_return/annual_return/max_ddpercent/daily_return/return_std已经是百分比形式(如25.0表示25%)
        # win_rate/optimal_position_ratio是小数形式(如0.5表示50%)
        total_return = statistics.get('total_return', 0)
        annual_return = statistics.get('annual_return', 0)
        max_ddpercent = statistics.get('max_ddpercent', 0)

        # 百分比形式的数据直接用{:.2f}%格式化
        total_return_str = f"{total_return:.2f}%"
        annual_return_str = f"{annual_return:.2f}%"
        max_ddpercent_str = f"{max_ddpercent:.2f}%"

        # 胜率是小数形式(0-1)，用{:.2%}格式化
        win_rate = statistics.get('win_rate', 0)
        win_rate_str = f"{win_rate:.2%}"

        # 格式化月均收益（从总收益和总天数计算，total_return已是百分比）
        total_days = statistics.get('total_days', 0)
        if total_days > 0:
            monthly_return = (total_return / total_days) * 30
            monthly_return_str = f"{monthly_return:.2f}%"
        else:
            monthly_return_str = "0.00%"

        # 格式化日均收益（已是百分比形式）
        daily_return = statistics.get('daily_return', 0)
        daily_return_str = f"{daily_return:.2f}%"

        # 格式化收益波动（已是百分比形式）
        return_std = statistics.get('return_std', 0)
        return_std_str = f"{return_std:.2f}%"

        # 24个核心指标映射（与create_placeholder_cards中的顺序一致）
        metric_mapping = {
            # 第一行 - 收益指标
            "总收益率": total_return_str,
            "年化收益": annual_return_str,
            "总盈亏": f"{statistics.get('total_net_pnl', 0):,.2f}",
            "日均盈亏": f"{statistics.get('daily_net_pnl', 0):,.2f}",
            # 第二行 - 风险指标
            "最大回撤": f"{statistics.get('max_drawdown', 0):,.2f}",
            "百分比最大回撤": max_ddpercent_str,
            "最大回撤天数": f"{statistics.get('max_drawdown_duration', 0)}",
            "综合评分": f"{statistics.get('overall_rating', 0):.4f}",
            # 第三行 - 风险调整收益
            "夏普比率": f"{statistics.get('sharpe_ratio', 0):.2f}",
            "索提诺比率": f"{statistics.get('sortino_ratio', 0):.2f}",
            "卡尔马比率": f"{statistics.get('calmar_ratio', 0):.2f}",
            "收益回撤比": f"{statistics.get('return_drawdown_ratio', 0):.2f}",
            # 第四行 - 风险调整收益（续）+ 交易统计
            "EWM夏普": f"{statistics.get('ewm_sharpe', 0):.2f}",
            "胜率": win_rate_str,
            "盈亏比": f"{statistics.get('average_win_loss_ratio', 0):.2f}",
            "获利因子": f"{statistics.get('profit_factor', 0):.2f}",
            # 第五行 - 交易统计
            "总成交笔数": f"{statistics.get('total_trade_count', 0)}",
            "多头笔数": f"{statistics.get('long_trade_count', 0)}",
            "空头笔数": f"{statistics.get('short_trade_count', 0)}",
            "平均每笔盈亏": f"{statistics.get('average_trade', 0):,.2f}",
            # 第六行 - 高级交易统计
            "最大连续盈利次数": f"{statistics.get('max_consecutive_wins', 0)}",
            "最大连续亏损次数": f"{statistics.get('max_consecutive_losses', 0)}",
            "最优仓位比例": f"{statistics.get('optimal_position_ratio', 0):.2%}",
            "平均持仓时间": f"{statistics.get('average_holding_time_days', 0):.2f}天",
        }

        # 更新所有卡片
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                card = item.widget()
                metric_name = getattr(card, 'metric_name', '')
                if metric_name in metric_mapping:
                    value_label = getattr(card, 'value_label', None)
                    grade_label = getattr(card, 'grade_label', None)

                    if value_label:
                        new_value = metric_mapping[metric_name]
                        # 确保值是字符串类型
                        if new_value is None:
                            new_value = 'N/A'
                        else:
                            new_value = str(new_value)
                        value_label.setText(new_value)

                        # 使用智能分级着色系统更新颜色
                        color = self.get_metric_color(metric_name, new_value)

                        # 根据卡片类型使用正确的字体大小和颜色
                        card_type = getattr(card, 'card_type', 'minor')
                        if card_type == 'major':
                            # 大卡片样式（包含颜色）
                            style = f"""
                                QLabel {{
                                    font-size: 32px;
                                    font-weight: 900;
                                    background: transparent;
                                    border: none;
                                    line-height: 1;
                                    padding: 4px;
                                    color: {color};
                                }}
                            """
                        else:
                            # 小卡片样式（包含颜色）
                            style = f"""
                                QLabel {{
                                    font-size: 16px;
                                    font-weight: bold;
                                    background: transparent;
                                    border: none;
                                    line-height: 1;
                                    padding: 1px;
                                    color: {color};
                                }}
                            """

                        value_label.setStyleSheet(style)

                        # 更新等级说明标签
                        if grade_label:
                            grade_text = self.get_metric_grade_text(metric_name, new_value, color)
                            grade_label.setText(grade_text)


class MetricsGridWidget(QtWidgets.QWidget):
    """指标网格显示组件"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """初始化界面"""
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建滚动区域
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        
        # 创建内容组件
        content_widget = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.setSpacing(15)
        content_widget.setLayout(self.content_layout)
        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)
        
        # 设置样式
        self.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #2a2a2a;
            }
            QScrollBar:vertical {
                background-color: #333;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
        """)
        
    def create_metric_group(self, title: str, metrics: dict) -> QtWidgets.QWidget:
        """创建指标组"""
        group_widget = QtWidgets.QWidget()
        group_layout = QtWidgets.QVBoxLayout()
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(10)
        
        # 检查是否只有一个卡片，如果是则不显示标题栏
        show_header = len(metrics) > 1
        
        if show_header:
            # 创建标题栏
            header_widget = QtWidgets.QWidget()
            header_widget.setFixedHeight(40)
            header_widget.setStyleSheet("""
                QWidget {
                    background-color: #333;
                    border-radius: 8px;
                }
            """)
            
            header_layout = QtWidgets.QHBoxLayout()
            header_layout.setContentsMargins(15, 0, 15, 0)
            
            title_label = QtWidgets.QLabel(title)
            title_label.setStyleSheet("""
                QLabel {
                    font-size: 15px;
                    font-weight: bold;
                    color: #fff;
                    background: transparent;
                    padding: 2px;
                }
            """)
            
            header_layout.addWidget(title_label)
            header_layout.addStretch()
            header_widget.setLayout(header_layout)
        
        # 创建指标网格
        metrics_widget = QtWidgets.QWidget()
        metrics_widget.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 18px;
                margin: 2px;
            }
        """)
        
        grid_layout = QtWidgets.QGridLayout()
        grid_layout.setSpacing(15)  # 增加间距
        
        # 添加指标卡片 - 根据指标数量和类型动态调整列数
        chart_items = []
        normal_items = []
        
        for metric_name, metric_value in metrics.items():
            if hasattr(metric_value, 'setParent') and hasattr(metric_value, 'setFixedHeight'):
                # 这是图表组件
                chart_items.append((metric_name, metric_value))
            else:
                # 普通指标
                normal_items.append((metric_name, metric_value))
        
        current_row = 0
        
        # 先添加普通指标
        if normal_items:
            max_cols = 4 if len(normal_items) > 12 else 3  # 大量指标时使用4列
            
            for i, (metric_name, metric_value) in enumerate(normal_items):
                row = current_row + i // max_cols
                col = i % max_cols
                card = self.create_metric_card(metric_name, metric_value)
                grid_layout.addWidget(card, row, col)
            
            current_row += (len(normal_items) - 1) // max_cols + 1
        
        # 再添加图表组件，每个图表占一整行
        for metric_name, metric_value in chart_items:
            card = self.create_metric_card(metric_name, metric_value)
            grid_layout.addWidget(card, current_row, 0, 1, 4)  # 跨4列
            current_row += 1
                
        metrics_widget.setLayout(grid_layout)
        
        if show_header:
            group_layout.addWidget(header_widget)
        group_layout.addWidget(metrics_widget)
        group_widget.setLayout(group_layout)
        
        return group_widget
        
    def create_metric_card(self, name: str, value: Any) -> QtWidgets.QWidget:
        """创建指标卡片"""
        # 检查是否是图表组件
        if hasattr(value, 'setParent') and hasattr(value, 'setFixedHeight'):
            # 这是一个图表组件，创建特殊的图表卡片
            card = QtWidgets.QWidget()
            card.setStyleSheet("""
                QWidget {
                    background-color: #333;
                    border: 1px solid #555;
                    border-radius: 6px;
                    padding: 10px;
                }
                QWidget:hover {
                    background-color: #3a3a3a;
                    border-color: #666;
                }
            """)
            
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(5, 5, 5, 5)
            layout.setSpacing(8)
            
            # 图表标题
            title_label = QtWidgets.QLabel(name)
            title_label.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    color: #fff;
                    font-weight: bold;
                    background: transparent;
                    border: none;
                    padding: 5px;
                }
            """)
            title_label.setAlignment(QtCore.Qt.AlignCenter)
            
            layout.addWidget(title_label)
            layout.addWidget(value)
            card.setLayout(layout)
            
            return card
        
        # 普通指标卡片
        card = QtWidgets.QWidget()
        card.setFixedHeight(95)  # 增加高度以完整显示数值
        card.setStyleSheet("""
            QWidget {
                background-color: #333;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 10px;
            }
            QWidget:hover {
                background-color: #3a3a3a;
                border-color: #666;
            }
        """)
        
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)
        
        # 指标名称
        name_label = QtWidgets.QLabel(name)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                color: #ddd;
                font-weight: 600;
                background: transparent;
                border: none;
                padding: 2px;
            }
        """)
        name_label.setAlignment(QtCore.Qt.AlignCenter)
        name_label.setWordWrap(True)
        
        # 指标值
        value_label = QtWidgets.QLabel(str(value))
        base_style = """
            QLabel {
                font-size: 20px;
                font-weight: bold;
                background: transparent;
                border: none;
                padding: 2px;
                line-height: 1.2;
            }
        """
        
        # 根据值的类型设置颜色（中国市场：红涨绿跌）
        if isinstance(value, (int, float)):
            if value > 0:
                value_label.setStyleSheet(base_style + "color: #ff4444;")  # 红色表示盈利
            elif value < 0:
                value_label.setStyleSheet(base_style + "color: #00aa00;")  # 绿色表示亏损
            else:
                value_label.setStyleSheet(base_style + "color: #fff;")
        else:
            # 对于字符串值，尝试解析数值
            try:
                str_val = str(value).replace('%', '').replace(',', '').replace('N/A', '0')
                if str_val and str_val != '0':
                    numeric_value = float(str_val)
                    if numeric_value > 0:
                        value_label.setStyleSheet(base_style + "color: #ff4444;")
                    elif numeric_value < 0:
                        value_label.setStyleSheet(base_style + "color: #00aa00;")
                    else:
                        value_label.setStyleSheet(base_style + "color: #fff;")
                else:
                    value_label.setStyleSheet(base_style + "color: #fff;")
            except:
                value_label.setStyleSheet(base_style + "color: #fff;")
                
        value_label.setAlignment(QtCore.Qt.AlignCenter)
        value_label.setWordWrap(True)
        
        layout.addWidget(name_label)
        layout.addWidget(value_label)
        card.setLayout(layout)
        
        return card
        
    def update_metrics(self, statistics: dict):
        """更新指标显示"""
        # 清除现有内容
        for i in reversed(range(self.content_layout.count())):
            child = self.content_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        if not statistics:
            return
            
        # 百分比格式化函数 - vnpy返回的百分比指标(如total_return)已是百分比形式(如25.0表示25%)
        def format_pct_value(value):
            """格式化已经是百分比形式的值(如25.0 -> 25.00%)"""
            if value is None:
                return "0.00%"
            return f"{value:.2f}%"

        # 小数格式化函数 - vnpy返回的小数指标(如win_rate)是小数形式(如0.5表示50%)
        def format_decimal_pct(value):
            """格式化小数形式的百分比值(如0.5 -> 50.00%)"""
            if value is None:
                return "0.00%"
            return f"{value:.2%}"
        
        # 日期格式化函数
        def format_date(date_value):
            """格式化日期"""
            if hasattr(date_value, 'strftime'):
                return date_value.strftime('%Y-%m-%d')
            elif date_value is not None:
                return str(date_value)
            else:
                return 'N/A'
        
        # 按照enhanced_widget中的GROUPED_INDICATORS完整实现所有指标组
        
        # 【基础信息】
        basic_info = {
            "首个交易日": format_date(statistics.get('start_date')),
            "最后交易日": format_date(statistics.get('end_date')),
            "总交易日": f"{statistics.get('total_days', 0)}",
            "盈利交易日": f"{statistics.get('profit_days', 0)}",
            "亏损交易日": f"{statistics.get('loss_days', 0)}",
            "起始资金": f"{statistics.get('capital', 0):,.2f}",
            "结束资金": f"{statistics.get('end_balance', 0):,.2f}",
        }
        
        # 【收益指标】 - total_return/annual_return/daily_return已是百分比形式
        return_metrics = {
            "总收益率": format_pct_value(statistics.get('total_return', 0)),
            "年化收益": format_pct_value(statistics.get('annual_return', 0)),
            "日均收益率": format_pct_value(statistics.get('daily_return', 0)),
            "总盈亏": f"{statistics.get('total_net_pnl', 0):,.2f}",
            "日均盈亏": f"{statistics.get('daily_net_pnl', 0):,.2f}",
        }

        # 【风险指标】 - max_ddpercent/return_std已是百分比形式
        risk_metrics = {
            "最大回撤": f"{statistics.get('max_drawdown', 0):,.2f}",
            "百分比最大回撤": format_pct_value(statistics.get('max_ddpercent', 0)),
            "最大回撤天数": f"{statistics.get('max_drawdown_duration', 0)}",
            "收益标准差": format_pct_value(statistics.get('return_std', 0)),
        }

        # 【风险调整收益】
        risk_adjusted_metrics = {
            "夏普比率": f"{statistics.get('sharpe_ratio', 0):.2f}",
            "EWM夏普": f"{statistics.get('ewm_sharpe', 0):.2f}",
            "索提诺比率": f"{statistics.get('sortino_ratio', 0):.2f}",
            "卡尔马比率": f"{statistics.get('calmar_ratio', 0):.2f}",
            "收益回撤比": f"{statistics.get('return_drawdown_ratio', 0):.2f}",
        }

        # 【交易统计】 - win_rate/optimal_position_ratio是小数形式
        trading_metrics = {
            "总成交笔数": f"{statistics.get('total_trade_count', 0)}",
            "多头笔数": f"{statistics.get('long_trade_count', 0)}",
            "空头笔数": f"{statistics.get('short_trade_count', 0)}",
            "胜率": format_decimal_pct(statistics.get('win_rate', 0)),
            "平均盈亏比": f"{statistics.get('average_win_loss_ratio', 0):.2f}",
            "获利因子": f"{statistics.get('profit_factor', 0):.2f}",
            "平均每笔盈亏": f"{statistics.get('average_trade', 0):.2f}",
            "最大连续盈利次数": f"{statistics.get('max_consecutive_wins', 0)}",
            "最大连续亏损次数": f"{statistics.get('max_consecutive_losses', 0)}",
            "最优仓位比例": format_decimal_pct(statistics.get('optimal_position_ratio', 0)),
        }
        
        # 【持仓统计】
        holding_metrics = {
            "平均持仓时间(天)": f"{statistics.get('average_holding_time_days', 0):.2f}",
            "最大持仓时间(天)": f"{statistics.get('max_holding_time_days', 0):.2f}",
            "最小持仓时间(天)": f"{statistics.get('min_holding_time_days', 0):.2f}",
            "中位数持仓时间(天)": f"{statistics.get('median_holding_time_days', 0):.2f}",
        }
        
        # 【成本统计】
        cost_metrics = {
            "总手续费": f"{statistics.get('total_commission', 0):,.2f}",
            "总滑点": f"{statistics.get('total_slippage', 0):,.2f}",
            "总成交额": f"{statistics.get('total_turnover', 0):,.2f}",
            "日均手续费": f"{statistics.get('daily_commission', 0):,.2f}",
            "日均滑点": f"{statistics.get('daily_slippage', 0):,.2f}",
            "日均成交额": f"{statistics.get('daily_turnover', 0):,.2f}",
            "日均成交笔数": f"{statistics.get('daily_trade_count', 0):.2f}",
        }
        
        # 【综合评分】
        rating_metrics = {
            "综合评分": f"{statistics.get('overall_rating', 0):.4f}",
        }
        
        # 【月度统计数据】
        monthly_stats = statistics.get('monthly_statistics', {})
        
        # 检查monthly_stats是否为字典类型
        if isinstance(monthly_stats, dict) and monthly_stats:
            try:
                # 创建月度统计图表
                monthly_metrics = self.create_monthly_chart(monthly_stats)
            except Exception as e:
                monthly_metrics = {"月度数据": "数据格式错误"}
        else:
            monthly_metrics = {
                "月度数据": "暂无数据",
            }
        
        # 【半小时区间统计】
        interval_stats = statistics.get('interval_statistics', {})
        
        # 检查interval_stats是否为字典类型
        if isinstance(interval_stats, dict) and interval_stats:
            try:
                # 创建半小时区间统计图表
                interval_metrics = self.create_interval_chart(interval_stats)
            except Exception as e:
                interval_metrics = {"区间数据": "数据格式错误"}
        else:
            # 提供默认的时间区间统计
            default_intervals = {
                "09:30-10:00": {"return": 0, "win_rate": 0},
                "10:00-10:30": {"return": 0, "win_rate": 0},
                "10:30-11:00": {"return": 0, "win_rate": 0},
                "11:00-11:30": {"return": 0, "win_rate": 0},
                "13:30-14:00": {"return": 0, "win_rate": 0},
                "14:00-14:30": {"return": 0, "win_rate": 0},
                "14:30-15:00": {"return": 0, "win_rate": 0},
            }
            interval_metrics = self.create_interval_chart(default_intervals)
        
        # 创建各个指标组
        groups = [
            ("基础信息", basic_info),
            ("收益指标", return_metrics),
            ("风险指标", risk_metrics),
            ("风险调整收益", risk_adjusted_metrics),
            ("交易统计", trading_metrics),
            ("持仓统计", holding_metrics),
            ("成本统计", cost_metrics),
            ("综合评分", rating_metrics),
            ("月度统计数据", monthly_metrics),
            ("半小时区间统计", interval_metrics),
        ]
        
        for title, metrics in groups:
            group_widget = self.create_metric_group(title, metrics)
            self.content_layout.addWidget(group_widget)
            
        self.content_layout.addStretch()
    
    def calculate_long_short_trades(self, statistics: dict) -> tuple:
        """从交易数据计算多头空头笔数"""
        try:
            # 尝试从父组件获取回测引擎
            if hasattr(self, 'parent') and hasattr(self.parent(), 'backtester_engine'):
                backtester_engine = self.parent().backtester_engine
                trades = backtester_engine.get_all_trades()
                
                long_count = 0
                short_count = 0
                
                for trade in trades:
                    if hasattr(trade, 'direction'):
                        if trade.direction.value == 'LONG' or trade.direction.value == '多':
                            long_count += 1
                        elif trade.direction.value == 'SHORT' or trade.direction.value == '空':
                            short_count += 1
                
                return long_count, short_count
        except:
            pass
        
        # 如果无法获取实际数据，返回0
        return 0, 0
    
    def create_monthly_chart(self, monthly_stats: dict) -> dict:
        """创建月度统计图表"""
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
            import matplotlib
            matplotlib.use('Qt5Agg')

            # 准备数据
            months = []
            pnls = []  # 改为pnl，表示绝对盈亏（元）
            win_rates = []

            for month, stats in sorted(monthly_stats.items()):
                if isinstance(stats, dict):
                    months.append(f"{month}月")
                    # return字段现在是total_pnl（绝对盈亏，元），不需要乘以100
                    pnls.append(stats.get('return', 0))
                    win_rates.append(stats.get('win_rate', 0) * 100)  # 转换为百分比

            if not months:
                return {"月度图表": "无有效数据"}

            # 创建图表
            fig = Figure(figsize=(8, 4), facecolor='#2a2a2a')
            ax1 = fig.add_subplot(111)
            ax1.set_facecolor('#2a2a2a')

            # 绘制盈亏柱状图，根据正负值使用不同颜色
            colors = ['#ff4444' if p >= 0 else '#00aa00' for p in pnls]  # 红涨绿跌
            bars = ax1.bar(months, pnls, color=colors, alpha=0.7, label='月度盈亏(元)')

            # 创建第二个y轴用于胜率折线
            ax2 = ax1.twinx()
            line = ax2.plot(months, win_rates, color='#ffc107', marker='o', linewidth=2,
                           markersize=6, label='胜率(%)')

            # 设置样式
            ax1.set_ylabel('盈亏 (元)', color='#fff', fontsize=10)
            ax2.set_ylabel('胜率 (%)', color='#fff', fontsize=10)
            ax1.set_xlabel('月份', color='#fff', fontsize=10)
            
            # 设置颜色
            ax1.tick_params(colors='#fff', labelsize=9)
            ax2.tick_params(colors='#fff', labelsize=9)
            ax1.spines['bottom'].set_color('#fff')
            ax1.spines['top'].set_color('#fff')
            ax1.spines['right'].set_color('#fff')
            ax1.spines['left'].set_color('#fff')
            ax2.spines['bottom'].set_color('#fff')
            ax2.spines['top'].set_color('#fff')
            ax2.spines['right'].set_color('#fff')
            ax2.spines['left'].set_color('#fff')
            
            # 添加网格
            ax1.grid(True, alpha=0.3, color='#666')
            
            # 添加图例
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', 
                      facecolor='#333', edgecolor='#666', labelcolor='#fff', fontsize=9)
            
            plt.tight_layout()
            fig.subplots_adjust(bottom=0.20, top=0.95, left=0.08, right=0.92) 
            # 创建Canvas并嵌入到Qt组件中
            canvas = FigureCanvas(fig)
            canvas.setFixedHeight(300)
            canvas.setStyleSheet("background-color: #2a2a2a;")
            
            return {"月度统计图表": canvas}
            
        except ImportError:
            # 如果没有matplotlib，返回文本数据
            print("matplotlib未安装，无法生成月度图表，返回文本数据。")
            text_data = {}
            for month, stats in sorted(monthly_stats.items()):
                if isinstance(stats, dict):
                    text_data[f"{month}月收益"] = f"{stats.get('return', 0):.2%}"
                    text_data[f"{month}月胜率"] = f"{stats.get('win_rate', 0):.2%}"
            return text_data
        except Exception as e:
            return {"月度图表": f"生成失败: {str(e)}"}
    
    def create_interval_chart(self, interval_stats: dict) -> dict:
        """创建半小时区间统计图表"""
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
            import matplotlib
            matplotlib.use('Qt5Agg')
            
            if not interval_stats:
                return {"区间图表": "无有效数据"}
            
            # 从实际数据中获取时间区间并排序
            def parse_time(time_str):
                """解析时间字符串为分钟数，用于排序
                期货市场时间排序规则：
                - 夜盘品种：21:00-2:30, 9:00-15:00
                - 日盘品种：9:00-15:00
                """
                try:
                    # 提取时间部分（去掉区间后缀）
                    if '-' in time_str:
                        time_part = time_str.split('-')[0]
                    else:
                        time_part = time_str
                    
                    if ':' in time_part:
                        hour, minute = time_part.split(':')
                        hour = int(hour)
                        minute = int(minute)
                    else:
                        hour = int(time_part)
                        minute = 0
                    
                    total_minutes = hour * 60 + minute
                    
                    # 期货市场时间排序逻辑
                    if hour >= 21:  # 夜盘开始 21:00-23:59
                        return total_minutes - 21 * 60  # 从0开始计算
                    elif hour <= 2:  # 夜盘结束 0:00-2:30
                        return total_minutes + (24 - 21) * 60  # 接在夜盘后面
                    elif hour >= 9 and hour <= 15:  # 日盘 9:00-15:00
                        return total_minutes + (24 - 21 + 2.5) * 60  # 接在夜盘后面
                    else:
                        # 其他时间（不应该有交易）
                        return total_minutes + 1000 * 60  # 排在最后
                        
                except:
                    return 0
            
            # 按时间顺序排序区间
            sorted_intervals = sorted(interval_stats.keys(), key=parse_time)
            
            # 准备数据
            intervals = []
            pnls = []  # 改为pnl，表示绝对盈亏（元）
            win_rates = []
            trade_counts = []

            for interval in sorted_intervals:
                stats = interval_stats[interval]
                if isinstance(stats, dict):
                    intervals.append(interval)
                    # return字段现在是total_pnl（绝对盈亏，元），不需要乘以100
                    pnls.append(stats.get('return', 0))
                    win_rates.append(stats.get('win_rate', 0) * 100)  # 转换为百分比
                    trade_counts.append(stats.get('trades', 0))
            
            if not intervals:
                return {"区间图表": "无有效数据"}
            
            # 创建图表
            fig = Figure(figsize=(max(12, len(intervals) * 1.2), 5), facecolor='#2a2a2a')
            ax1 = fig.add_subplot(111)
            ax1.set_facecolor('#2a2a2a')
            
            # 创建X轴位置
            x_pos = range(len(intervals))
            
            # 绘制盈亏柱状图，根据正负值使用不同颜色
            colors = ['#ff4444' if p >= 0 else '#00aa00' for p in pnls]  # 红涨绿跌
            bars = ax1.bar(x_pos, pnls, color=colors, alpha=0.7, label='区间盈亏(元)', width=0.6)
            
            # 创建第二个y轴用于胜率折线
            ax2 = ax1.twinx()
            line = ax2.plot(x_pos, win_rates, color='#ffc107', marker='o', linewidth=2, 
                           markersize=8, label='胜率(%)', markerfacecolor='#ffc107', 
                           markeredgecolor='#fff', markeredgewidth=1)
            
            # 设置x轴
            ax1.set_xticks(x_pos)
            
            # 处理X轴标签 - 根据数据量调整显示方式
            if len(intervals) <= 10:
                # 数据点较少时，显示完整时间，减少旋转角度
                ax1.set_xticklabels(intervals, rotation=30, ha='right', fontsize=9)
            else:
                # 数据点较多时，只显示开始时间
                simplified_labels = []
                for interval in intervals:
                    if ':' in interval:
                        # 如果包含冒号，提取小时:分钟部分
                        time_part = interval.split('-')[0] if '-' in interval else interval
                        simplified_labels.append(time_part)
                    else:
                        # 如果不包含冒号，直接使用
                        simplified_labels.append(interval)
                ax1.set_xticklabels(simplified_labels, rotation=30, ha='right', fontsize=9)
            
            # 调整X轴标签位置，确保完全显示
            ax1.tick_params(axis='x', pad=5)  # 增加标签与轴的距离
            
            # 添加分隔线区分夜盘和日盘
            night_day_boundary = None
            has_night_session = False
            has_day_session = False
            
            for i, interval in enumerate(intervals):
                try:
                    # 提取时间部分
                    if '-' in interval:
                        time_part = interval.split('-')[0]
                    else:
                        time_part = interval
                    
                    if ':' in time_part:
                        hour = int(time_part.split(':')[0])
                    else:
                        hour = int(time_part)
                    
                    # 判断是否有夜盘和日盘
                    if hour >= 21 or hour <= 2:
                        has_night_session = True
                    elif hour >= 9 and hour <= 15:
                        has_day_session = True
                    
                    # 找到夜盘到日盘的分界点
                    if i > 0 and night_day_boundary is None:
                        prev_interval = intervals[i-1]
                        if '-' in prev_interval:
                            prev_time_part = prev_interval.split('-')[0]
                        else:
                            prev_time_part = prev_interval
                        
                        if ':' in prev_time_part:
                            prev_hour = int(prev_time_part.split(':')[0])
                        else:
                            prev_hour = int(prev_time_part)
                        
                        # 从夜盘时间跳到日盘时间
                        if (prev_hour >= 21 or prev_hour <= 2) and (hour >= 9 and hour <= 15):
                            night_day_boundary = i - 0.5
                            
                except:
                    continue
            
            # 只有同时存在夜盘和日盘时才添加分隔线
            if night_day_boundary is not None and has_night_session and has_day_session:
                ax1.axvline(x=night_day_boundary, color='#666', linestyle='--', alpha=0.5, linewidth=1)
            
            # 设置样式
            ax1.set_ylabel('盈亏 (元)', color='#fff', fontsize=11)
            ax2.set_ylabel('胜率 (%)', color='#fff', fontsize=11)
            ax1.set_xlabel('交易时间区间', color='#fff', fontsize=11)

            # 设置Y轴范围，确保数据可见
            if pnls and (max(pnls) > 0 or min(pnls) < 0):
                y_margin = max(abs(max(pnls)), abs(min(pnls))) * 0.1
                ax1.set_ylim(min(pnls) - y_margin, max(pnls) + y_margin)

            if win_rates and max(win_rates) > 0:
                ax2.set_ylim(0, max(win_rates) * 1.1)

            # 设置颜色
            ax1.tick_params(colors='#fff', labelsize=9)
            ax2.tick_params(colors='#fff', labelsize=9)

            # 设置边框颜色
            for spine in ax1.spines.values():
                spine.set_color('#fff')
            for spine in ax2.spines.values():
                spine.set_color('#fff')

            # 添加网格
            ax1.grid(True, alpha=0.3, color='#666', axis='y')

            # 在柱状图上显示数值（只在数据点不太多时显示）
            if len(intervals) <= 15:
                for i, (bar, pnl_val, trade_count) in enumerate(zip(bars, pnls, trade_counts)):
                    if trade_count > 0:  # 只在有交易的区间显示数值
                        height = bar.get_height()
                        ax1.text(bar.get_x() + bar.get_width()/2., height + (y_margin * 0.1 if height >= 0 else -y_margin * 0.3),
                                f'{pnl_val:.0f}', ha='center', va='bottom' if height >= 0 else 'top',
                                color='#fff', fontsize=8, fontweight='bold')
            
            # 在折线图上显示胜率数值（只在数据点不太多时显示）
            if len(intervals) <= 15:
                for i, (x, win_rate, trade_count) in enumerate(zip(x_pos, win_rates, trade_counts)):
                    if trade_count > 0:  # 只在有交易的区间显示数值
                        ax2.text(x, win_rate + 2, f'{win_rate:.0f}%', ha='center', va='bottom',
                                color='#ffc107', fontsize=8, fontweight='bold')
            
            # 添加图例
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', 
                      facecolor='#333', edgecolor='#666', labelcolor='#fff', fontsize=10)
            
            # 不添加标题，节省空间
            
            # 使用fig对象调整布局，确保X轴标签完全显示
            fig.subplots_adjust(bottom=0.22, top=0.95, left=0.08, right=0.92)
            
            # 创建Canvas并嵌入到Qt组件中
            canvas = FigureCanvas(fig)
            canvas.setFixedHeight(350)  # 进一步增加高度
            canvas.setStyleSheet("background-color: #2a2a2a;")
            
            return {"半小时区间统计图表": canvas}
            
        except ImportError:
            # 如果没有matplotlib，返回文本数据
            print("matplotlib未安装，无法生成区间图表，返回文本数据。")
            text_data = {}
            for interval, stats in interval_stats.items():
                if isinstance(stats, dict):
                    text_data[f"{interval}收益"] = f"{stats.get('return', 0):.2%}"
                    text_data[f"{interval}胜率"] = f"{stats.get('win_rate', 0):.2%}"
            return text_data
        except Exception as e:
            return {"区间图表": f"生成失败: {str(e)}"}


class ChartWidget(QtWidgets.QWidget):
    """图表组件"""
    
    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.init_ui()
        
    def init_ui(self):
        """初始化界面"""
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # 创建标题栏
        header_layout = QtWidgets.QHBoxLayout()
        
        self.title_label = QtWidgets.QLabel(self.title)
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #ccc;
                font-weight: bold;
            }
        """)
        
        self.chart_selector = QtWidgets.QComboBox()
        self.chart_selector.addItems(["账户净值", "净值回撤", "每日盈亏", "滚动夏普比率"])
        self.chart_selector.setCurrentText(self.title)
        self.chart_selector.currentTextChanged.connect(self.on_chart_changed)
        self.chart_selector.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                background-color: #333;
                border: 1px solid #555;
                color: #fff;
                border-radius: 3px;
                font-size: 10px;
                min-width: 100px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }
            QComboBox::down-arrow {
                image: none;
                width: 0;
                height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #ccc;
                margin: 0px;
            }
            QComboBox::down-arrow:hover {
                border-top-color: #fff;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #fff;
                selection-background-color: #007acc;
                border: 1px solid #555;
                outline: none;
                padding: 0px;
                margin: 0px;
            }
            QComboBox QAbstractItemView::item {
                height: 22px;
                padding: 2px 6px;
                margin: 0px;
                border: none;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #007acc;
            }
        """)
        
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.chart_selector)
        
        # 创建图表区域
        self.chart_area = QtWidgets.QWidget()
        self.chart_area.setStyleSheet("""
            QWidget {
                background-color: #000;
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)
        
        chart_layout = QtWidgets.QVBoxLayout()
        chart_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建占位符（移除 emoji 避免 macOS bus error）
        self.placeholder_label = QtWidgets.QLabel(f"{self.title}图表")
        self.placeholder_label.setAlignment(QtCore.Qt.AlignCenter)
        self.placeholder_label.setStyleSheet("""
            QLabel {
                color: #666;
                font-size: 12px;
                background: transparent;
                border: none;
            }
        """)
        
        chart_layout.addWidget(self.placeholder_label)
        self.chart_area.setLayout(chart_layout)
        
        layout.addLayout(header_layout)
        layout.addWidget(self.chart_area)
        
        self.setLayout(layout)
        
    def on_chart_changed(self, text: str):
        """图表类型改变"""
        self.title_label.setText(text)

        # 更新占位符（移除 emoji 避免 macOS bus error）
        self.placeholder_label.setText(f"{text}图表")

        # 如果有数据，重新绘制图表
        if hasattr(self, 'current_data') and self.current_data is not None:
            self.update_chart_data(self.current_data)
        
    def update_chart_data(self, df):
        """更新图表数据"""
        if df is None or df.empty:
            return
            
        # 保存数据以便切换图表类型时使用
        self.current_data = df
            
        # 移除占位符
        self.placeholder_label.hide()
        
        # 创建真实的图表
        try:
            import pyqtgraph as pg
            
            # 清除现有图表
            for i in reversed(range(self.chart_area.layout().count())):
                child = self.chart_area.layout().itemAt(i).widget()
                if child and hasattr(child, 'clear'):
                    child.setParent(None)
            
            # 创建pyqtgraph图表
            chart_widget = pg.PlotWidget()
            chart_widget.setBackground('#000')
            chart_widget.showGrid(x=True, y=True, alpha=0.3)
            
            # 根据图表类型显示不同数据
            current_type = self.chart_selector.currentText()
            
            if current_type == "账户净值":
                if 'balance' in df.columns:
                    chart_widget.plot(df['balance'].values, pen=pg.mkPen('#ffc107', width=2))
                    chart_widget.setLabel('left', '净值')
                    chart_widget.setLabel('bottom', '时间')
                    
            elif current_type == "净值回撤":
                if 'drawdown' in df.columns:
                    chart_widget.plot(df['drawdown'].values, pen=pg.mkPen('#00aa00', width=2), 
                                    fillLevel=0, brush=pg.mkBrush('#00aa00', alpha=50))  # 绿色表示回撤（负面）
                    chart_widget.setLabel('left', '回撤')
                    chart_widget.setLabel('bottom', '时间')
                    
            elif current_type == "每日盈亏":
                if 'net_pnl' in df.columns:
                    # 创建柱状图
                    x = list(range(len(df)))
                    y = df['net_pnl'].values
                    
                    # 分别处理正负值
                    pos_x = [i for i, val in enumerate(y) if val >= 0]
                    pos_y = [val for val in y if val >= 0]
                    neg_x = [i for i, val in enumerate(y) if val < 0]
                    neg_y = [val for val in y if val < 0]
                    
                    if pos_x:
                        pos_bar = pg.BarGraphItem(x=pos_x, height=pos_y, width=0.8, 
                                                brush=pg.mkBrush('#ff4444'))  # 红色表示盈利
                        chart_widget.addItem(pos_bar)
                    
                    if neg_x:
                        neg_bar = pg.BarGraphItem(x=neg_x, height=neg_y, width=0.8, 
                                                brush=pg.mkBrush('#00aa00'))  # 绿色表示亏损
                        chart_widget.addItem(neg_bar)
                    
                    chart_widget.setLabel('left', '盈亏')
                    chart_widget.setLabel('bottom', '时间')
                    
            elif current_type == "滚动夏普比率":
                # 计算滚动夏普比率
                if 'net_pnl' in df.columns:
                    rolling_sharpe = self.calculate_rolling_sharpe(df['net_pnl'])
                    if len(rolling_sharpe) > 0:
                        chart_widget.plot(rolling_sharpe, pen=pg.mkPen('#2196F3', width=2))
                        # 添加基准线
                        baseline = [1.0] * len(rolling_sharpe)
                        chart_widget.plot(baseline, pen=pg.mkPen('#FF5722', width=1, style=QtCore.Qt.DashLine))
                        chart_widget.setLabel('left', '夏普比率')
                        chart_widget.setLabel('bottom', '时间')
            
            self.chart_area.layout().addWidget(chart_widget)
            
        except ImportError:
            # 如果没有pyqtgraph，显示简单的文本信息
            info_label = QtWidgets.QLabel(f"图表数据已更新\n数据点数: {len(df)}")
            info_label.setAlignment(QtCore.Qt.AlignCenter)
            info_label.setStyleSheet("""
                QLabel {
                    color: #ff4444;
                    font-size: 14px;
                    background: transparent;
                    border: none;
                }
            """)
            self.chart_area.layout().addWidget(info_label)
    
    def calculate_rolling_sharpe(self, pnl_series, window=30):
        """计算滚动夏普比率"""
        import numpy as np
        
        if len(pnl_series) < window:
            return []
        
        rolling_sharpe = []
        
        for i in range(window, len(pnl_series) + 1):
            window_pnl = pnl_series[i-window:i]
            mean_return = np.mean(window_pnl)
            std_return = np.std(window_pnl, ddof=1)
            
            if std_return > 0:
                sharpe = mean_return / std_return * np.sqrt(252)  # 年化
            else:
                sharpe = 0
            
            rolling_sharpe.append(sharpe)
        
        return rolling_sharpe
    