#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CTA回测模块UI组件

本文件是CTA回测的主界面文件，集成了以下功能：
1. 基础回测界面（OriginalBacktesterManager）
2. 增强版K线图表（CandleChartDialog，使用EnhancedChartWidget）
3. 增强版统计监控器（EnhancedStatisticsMonitor，来自enhanced_widget.py）
4. 增强版优化结果显示（EnhancedOptimizationResultMonitor，来自enhanced_widget.py）

相关文件说明：
- widget.py（本文件）：主回测界面，已集成EnhancedChartWidget
- enhanced_widget.py：提供EnhancedStatisticsMonitor和EnhancedOptimizationResultMonitor组件
- redesigned_widget.py：可选的现代化界面（两列布局）
- core/charts/enhanced_chart_widget.py：增强版图表组件（独立维护）

注意：
- CandleChartDialog已经使用EnhancedChartWidget，无需修改
"""

import platform
import csv
import shutil
import subprocess
from datetime import datetime, timedelta
from copy import copy
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
from pandas import DataFrame

from vnpy.trader.constant import Interval, Direction, Exchange
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import QtCore, QtWidgets, QtGui
from vnpy.trader.ui.widget import BaseMonitor, BaseCell, DirectionCell, EnumCell
from vnpy.event import Event, EventEngine
from vnpy.chart import ChartWidget, CandleItem, VolumeItem
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
    OptimizationSetting,
    BacktesterEngine
)

# ===================================
# 导入增强功能组件
# ===================================
# 导入重新设计的现代化界面（可选）
from .redesigned_widget import RedesignedBacktesterManager

# 导入渐进式测试版本（用于排查问题）
from .test_versions import (
    TestVersion1,
    TestVersion2,
    TestVersion3,
    TestVersion4,
    TestVersion5,
    TestVersion6,
)

# 导入增强的统计监控器和优化结果显示器
try:
    from .enhanced_widget import EnhancedStatisticsMonitor, EnhancedOptimizationResultMonitor
    ENHANCED_COMPONENTS_AVAILABLE = True
except ImportError:
    ENHANCED_COMPONENTS_AVAILABLE = False
    print("Warning: Enhanced components not available")


# 保留原有的BacktesterManager类作为备份
class OriginalBacktesterManager(QtWidgets.QWidget):
    """"""

    setting_filename: str = "cta_backtester_setting.json"

    signal_log: QtCore.Signal = QtCore.Signal(Event)
    signal_backtesting_finished: QtCore.Signal = QtCore.Signal(Event)
    signal_optimization_finished: QtCore.Signal = QtCore.Signal(Event)

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine) -> None:
        """"""
        super().__init__()

        self.main_engine: MainEngine = main_engine
        self.event_engine: EventEngine = event_engine

        self.backtester_engine: BacktesterEngine = main_engine.get_engine(APP_NAME)     # type: ignore
        self.class_names: list = []
        self.settings: dict = {}

        self.target_display: str = ""

        # 延迟初始化标志，避免 Qt + multiprocessing 冲突（macOS bus error）
        self._engine_initialized: bool = False

        self.init_ui()
        self.register_event()
        # 注释掉：延迟到真正需要时才初始化引擎（避免 Qt + multiprocessing 冲突）
        # self.backtester_engine.init_engine()
        # self.init_strategy_settings()
        self.load_backtesting_setting()

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

        # Setting Part
        self.class_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()

        self.symbol_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("IF88.CFFEX")

        self.interval_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()
        for interval in Interval:
            self.interval_combo.addItem(interval.value)

        end_dt: datetime = datetime.now()
        start_dt: datetime = end_dt - timedelta(days=3 * 365)

        self.start_date_edit: QtWidgets.QDateEdit = QtWidgets.QDateEdit(
            QtCore.QDate(
                start_dt.year,
                start_dt.month,
                start_dt.day
            )
        )
        self.end_date_edit: QtWidgets.QDateEdit = QtWidgets.QDateEdit(
            QtCore.QDate.currentDate()
        )

        self.rate_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("0.000025")
        self.slippage_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("0.2")
        self.size_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("300")
        self.pricetick_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("0.2")
        self.capital_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("1000000")

        backtesting_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("开始回测"))
        backtesting_button.clicked.connect(self.start_backtesting)

        optimization_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("参数优化"))
        optimization_button.clicked.connect(self.start_optimization)

        self.result_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("优化结果"))
        self.result_button.clicked.connect(self.show_optimization_result)
        self.result_button.setEnabled(False)

        downloading_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("下载数据"))
        downloading_button.clicked.connect(self.start_downloading)

        self.order_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("委托记录"))
        self.order_button.clicked.connect(self.show_backtesting_orders)
        self.order_button.setEnabled(False)

        self.trade_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("成交记录"))
        self.trade_button.clicked.connect(self.show_backtesting_trades)
        self.trade_button.setEnabled(False)

        self.daily_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("每日盈亏"))
        self.daily_button.clicked.connect(self.show_daily_results)
        self.daily_button.setEnabled(False)

        self.candle_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("K线图表"))
        self.candle_button.clicked.connect(self.show_candle_chart)
        self.candle_button.setEnabled(False)

        edit_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("代码编辑"))
        edit_button.clicked.connect(self.edit_strategy_code)

        reload_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("策略重载"))
        reload_button.clicked.connect(self.reload_strategy_class)

        for button in [
            backtesting_button,
            optimization_button,
            downloading_button,
            self.result_button,
            self.order_button,
            self.trade_button,
            self.daily_button,
            self.candle_button,
            edit_button,
            reload_button
        ]:
            button.setFixedHeight(button.sizeHint().height() * 2)

        form: QtWidgets.QFormLayout = QtWidgets.QFormLayout()
        form.addRow(_("交易策略"), self.class_combo)
        form.addRow(_("本地代码"), self.symbol_line)
        form.addRow(_("K线周期"), self.interval_combo)
        form.addRow(_("开始日期"), self.start_date_edit)
        form.addRow(_("结束日期"), self.end_date_edit)
        form.addRow(_("手续费率"), self.rate_line)
        form.addRow(_("交易滑点"), self.slippage_line)
        form.addRow(_("合约乘数"), self.size_line)
        form.addRow(_("价格跳动"), self.pricetick_line)
        form.addRow(_("回测资金"), self.capital_line)

        result_grid: QtWidgets.QGridLayout = QtWidgets.QGridLayout()
        result_grid.addWidget(self.trade_button, 0, 0)
        result_grid.addWidget(self.order_button, 0, 1)
        result_grid.addWidget(self.daily_button, 1, 0)
        result_grid.addWidget(self.candle_button, 1, 1)

        left_vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        left_vbox.addLayout(form)
        left_vbox.addWidget(backtesting_button)
        left_vbox.addWidget(downloading_button)
        left_vbox.addStretch()
        left_vbox.addLayout(result_grid)
        left_vbox.addStretch()
        left_vbox.addWidget(optimization_button)
        left_vbox.addWidget(self.result_button)
        left_vbox.addStretch()
        left_vbox.addWidget(edit_button)
        left_vbox.addWidget(reload_button)

        # Result part
        # 使用增强的统计监控器（如果可用）
        if ENHANCED_COMPONENTS_AVAILABLE:
            self.statistics_monitor = EnhancedStatisticsMonitor()
        else:
            self.statistics_monitor: StatisticsMonitor = StatisticsMonitor()

        self.log_monitor: QtWidgets.QTextEdit = QtWidgets.QTextEdit()

        self.chart: BacktesterChart = BacktesterChart()
        chart: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        chart.addWidget(self.chart)

        self.trade_dialog: BacktestingResultDialog = BacktestingResultDialog(
            self.main_engine,
            self.event_engine,
            _("回测成交记录"),
            BacktestingTradeMonitor
        )
        self.order_dialog: BacktestingResultDialog = BacktestingResultDialog(
            self.main_engine,
            self.event_engine,
            _("回测委托记录"),
            BacktestingOrderMonitor
        )
        self.daily_dialog: BacktestingResultDialog = BacktestingResultDialog(
            self.main_engine,
            self.event_engine,
            _("回测每日盈亏"),
            DailyResultMonitor
        )

        # Candle Chart
        self.candle_dialog: CandleChartDialog = CandleChartDialog()

        # Layout
        middle_vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        middle_vbox.addWidget(self.statistics_monitor)
        middle_vbox.addWidget(self.log_monitor)

        left_hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        left_hbox.addLayout(left_vbox)
        left_hbox.addLayout(middle_vbox)

        left_widget: QtWidgets.QWidget = QtWidgets.QWidget()
        left_widget.setLayout(left_hbox)

        right_vbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        right_vbox.addWidget(self.chart)

        right_widget: QtWidgets.QWidget = QtWidgets.QWidget()
        right_widget.setLayout(right_vbox)

        hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox.addWidget(left_widget)
        hbox.addWidget(right_widget)
        self.setLayout(hbox)

    def load_backtesting_setting(self) -> None:
        """"""
        setting: dict = load_json(self.setting_filename)
        if not setting:
            return

        self.class_combo.setCurrentIndex(
            self.class_combo.findText(setting["class_name"])
        )

        self.symbol_line.setText(setting["vt_symbol"])

        self.interval_combo.setCurrentIndex(
            self.interval_combo.findText(setting["interval"])
        )

        start_str: str = setting.get("start", "")
        if start_str:
            start_dt: QtCore.QDate = QtCore.QDate.fromString(start_str, "yyyy-MM-dd")
            self.start_date_edit.setDate(start_dt)

        self.rate_line.setText(str(setting["rate"]))
        self.slippage_line.setText(str(setting["slippage"]))
        self.size_line.setText(str(setting["size"]))
        self.pricetick_line.setText(str(setting["pricetick"]))
        self.capital_line.setText(str(setting["capital"]))

    def register_event(self) -> None:
        """"""
        self.signal_log.connect(self.process_log_event)
        self.signal_backtesting_finished.connect(
            self.process_backtesting_finished_event)
        self.signal_optimization_finished.connect(
            self.process_optimization_finished_event)

        self.event_engine.register(EVENT_BACKTESTER_LOG, self.signal_log.emit)
        self.event_engine.register(EVENT_BACKTESTER_BACKTESTING_FINISHED, self.signal_backtesting_finished.emit)
        self.event_engine.register(EVENT_BACKTESTER_OPTIMIZATION_FINISHED, self.signal_optimization_finished.emit)

    def process_log_event(self, event: Event) -> None:
        """"""
        msg = event.data
        self.write_log(msg)

    def write_log(self, msg: str) -> None:
        """"""
        timestamp: str = datetime.now().strftime("%H:%M:%S")
        msg = f"{timestamp}\t{msg}"
        self.log_monitor.append(msg)

    def process_backtesting_finished_event(self, event: Event) -> None:
        """"""
        statistics: dict | None = self.backtester_engine.get_result_statistics()
        if statistics:
            self.statistics_monitor.set_data(statistics)

        df: DataFrame | None = self.backtester_engine.get_result_df()
        if df is not None:
            self.chart.set_data(df)

        self.trade_button.setEnabled(True)
        self.order_button.setEnabled(True)
        self.daily_button.setEnabled(True)

        # Tick data can not be displayed using candle chart
        interval: str = self.interval_combo.currentText()
        if interval != Interval.TICK.value:
            self.candle_button.setEnabled(True)

    def process_optimization_finished_event(self, event: Event) -> None:
        """"""
        self.write_log(_("请点击[优化结果]按钮查看"))
        self.result_button.setEnabled(True)

    def start_backtesting(self) -> None:
        """"""
        # 确保引擎已初始化（延迟初始化）
        self.ensure_engine_initialized()

        class_name: str = self.class_combo.currentText()
        if not class_name:
            self.write_log(_("请选择要回测的策略"))
            return

        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        start: datetime = cast(datetime, self.start_date_edit.dateTime().toPython())
        end: datetime = cast(datetime, self.end_date_edit.dateTime().toPython())
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

        # Save backtesting parameters
        backtesting_setting: dict = {
            "class_name": class_name,
            "vt_symbol": vt_symbol,
            "interval": interval,
            "start": start.strftime("%Y-%m-%d"),
            "rate": rate,
            "slippage": slippage,
            "size": size,
            "pricetick": pricetick,
            "capital": capital
        }
        save_json(self.setting_filename, backtesting_setting)

        # Get strategy setting
        old_setting: dict = self.settings[class_name]
        dialog: BacktestingSettingEditor = BacktestingSettingEditor(class_name, old_setting)
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
            self.statistics_monitor.clear_data()
            self.chart.clear_data()

            self.trade_button.setEnabled(False)
            self.order_button.setEnabled(False)
            self.daily_button.setEnabled(False)
            self.candle_button.setEnabled(False)

            self.trade_dialog.clear_data()
            self.order_dialog.clear_data()
            self.daily_dialog.clear_data()
            self.candle_dialog.clear_data()

    def start_optimization(self) -> None:
        """"""
        # 确保引擎已初始化（延迟初始化）
        self.ensure_engine_initialized()

        class_name: str = self.class_combo.currentText()
        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        start: datetime = cast(datetime, self.start_date_edit.dateTime().toPython())
        end: datetime = cast(datetime, self.end_date_edit.dateTime().toPython())
        rate: float = float(self.rate_line.text())
        slippage: float = float(self.slippage_line.text())
        size: float = float(self.size_line.text())
        pricetick: float = float(self.pricetick_line.text())
        capital: float = float(self.capital_line.text())

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

    def start_downloading(self) -> None:
        """"""
        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        start_date: QtCore.QDate = self.start_date_edit.date()
        end_date: QtCore.QDate = self.end_date_edit.date()

        start: datetime = datetime(
            start_date.year(),
            start_date.month(),
            start_date.day(),
        )
        start= start.replace(tzinfo=DB_TZ)

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

    def show_optimization_result(self) -> None:
        """"""
        result_values: list | None = self.backtester_engine.get_result_values()
        if result_values is None:
            return

        # 使用增强的优化结果监控器（如果可用）
        if ENHANCED_COMPONENTS_AVAILABLE:
            dialog = EnhancedOptimizationResultMonitor(result_values, self.target_display)
        else:
            dialog: OptimizationResultMonitor = OptimizationResultMonitor(
                result_values,
                self.target_display
            )
        dialog.exec_()

    def show_backtesting_trades(self) -> None:
        """"""
        if not self.trade_dialog.is_updated():
            trades: list[TradeData] = self.backtester_engine.get_all_trades()
            self.trade_dialog.update_data(trades)

        self.trade_dialog.exec_()

    def show_backtesting_orders(self) -> None:
        """"""
        if not self.order_dialog.is_updated():
            orders: list[OrderData] = self.backtester_engine.get_all_orders()
            self.order_dialog.update_data(orders)

        self.order_dialog.exec_()

    def show_daily_results(self) -> None:
        """"""
        if not self.daily_dialog.is_updated():
            results: list[DailyResult] = self.backtester_engine.get_all_daily_results()
            self.daily_dialog.update_data(results)

        self.daily_dialog.exec_()

    def show_candle_chart(self) -> None:
        """"""
        if not self.candle_dialog.is_updated():
            history: list = self.backtester_engine.get_history_data()
            self.candle_dialog.update_history(history)

            trades: list[TradeData] = self.backtester_engine.get_all_trades()
            self.candle_dialog.update_trades(trades)

        self.candle_dialog.exec_()

    def edit_strategy_code(self) -> None:
        """"""
        class_name: str = self.class_combo.currentText()
        if not class_name:
            return

        file_path: str = self.backtester_engine.get_strategy_class_file(class_name)

        # 按优先级排序的常用代码编辑器命令列表
        editor_cmds: list[str] = [
            "code",         # VS Code
            "cursor",       # Cursor
            "pycharm64",    # PyCharm (Windows)
            "charm",        # PyCharm (命令行启动器)
        ]

        # 查找可用的编辑器
        editor_cmd: str = ""
        for cmd in editor_cmds:
            if shutil.which(cmd):
                editor_cmd = cmd
                break

        if editor_cmd:
            if platform.system() == "Windows":
                subprocess.run([editor_cmd, file_path], shell=True)
            else:
                subprocess.run([editor_cmd, file_path])
        else:
            QtWidgets.QMessageBox.warning(
                self,
                _("启动代码编辑器失败"),
                _("未检测到可用的代码编辑器，请安装以下任一编辑器并添加到系统PATH：\n"
                  "Cursor、VS Code、PyCharm")
            )

    def reload_strategy_class(self) -> None:
        """"""
        # 确保引擎已初始化（延迟初始化）
        self.ensure_engine_initialized()

        self.backtester_engine.reload_strategy_class()

        current_strategy_name: str = self.class_combo.currentText()

        self.class_combo.clear()
        self.init_strategy_settings()

        ix: int = self.class_combo.findText(current_strategy_name)
        self.class_combo.setCurrentIndex(ix)

    def show(self) -> None:
        """"""
        self.showMaximized()


class StatisticsMonitor(QtWidgets.QTableWidget):
    """"""
    KEY_NAME_MAP: dict = {
        "start_date": _("首个交易日"),
        "end_date": _("最后交易日"),

        "total_days": _("总交易日"),
        "profit_days": _("盈利交易日"),
        "loss_days": _("亏损交易日"),

        "capital": _("起始资金"),
        "end_balance": _("结束资金"),

        "total_return": _("总收益率"),
        "annual_return": _("年化收益"),
        "max_drawdown": _("最大回撤"),
        "max_ddpercent": _("百分比最大回撤"),
        "max_drawdown_duration": _("最大回撤天数"),

        "total_net_pnl": _("总盈亏"),
        "total_commission": _("总手续费"),
        "total_slippage": _("总滑点"),
        "total_turnover": _("总成交额"),
        "total_trade_count": _("总成交笔数"),

        "daily_net_pnl": _("日均盈亏"),
        "daily_commission": _("日均手续费"),
        "daily_slippage": _("日均滑点"),
        "daily_turnover": _("日均成交额"),
        "daily_trade_count": _("日均成交笔数"),

        "daily_return": _("日均收益率"),
        "return_std": _("收益标准差"),
        "sharpe_ratio": _("夏普比率"),
        "ewm_sharpe": _("EWM夏普"),
        "return_drawdown_ratio": _("收益回撤比")
    }

    def __init__(self) -> None:
        """"""
        super().__init__()

        self.cells: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.setRowCount(len(self.KEY_NAME_MAP))
        self.setVerticalHeaderLabels(list(self.KEY_NAME_MAP.values()))

        self.setColumnCount(1)
        self.horizontalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)

        for row, key in enumerate(self.KEY_NAME_MAP.keys()):
            cell: QtWidgets.QTableWidgetItem = QtWidgets.QTableWidgetItem()
            self.setItem(row, 0, cell)
            self.cells[key] = cell

    def clear_data(self) -> None:
        """"""
        for cell in self.cells.values():
            cell.setText("")

    def set_data(self, data: dict) -> None:
        """"""
        data["capital"] = f"{data['capital']:,.2f}"
        data["end_balance"] = f"{data['end_balance']:,.2f}"
        data["total_return"] = f"{data['total_return']:.2f}%"
        data["annual_return"] = f"{data['annual_return']:.2f}%"
        data["max_drawdown"] = f"{data['max_drawdown']:,.2f}"
        data["max_ddpercent"] = f"{data['max_ddpercent']:.2f}%"
        data["total_net_pnl"] = f"{data['total_net_pnl']:,.2f}"
        data["total_commission"] = f"{data['total_commission']:,.2f}"
        data["total_slippage"] = f"{data['total_slippage']:,.2f}"
        data["total_turnover"] = f"{data['total_turnover']:,.2f}"
        data["daily_net_pnl"] = f"{data['daily_net_pnl']:,.2f}"
        data["daily_commission"] = f"{data['daily_commission']:,.2f}"
        data["daily_slippage"] = f"{data['daily_slippage']:,.2f}"
        data["daily_turnover"] = f"{data['daily_turnover']:,.2f}"
        data["daily_trade_count"] = f"{data['daily_trade_count']:,.2f}"
        data["daily_return"] = f"{data['daily_return']:.2f}%"
        data["return_std"] = f"{data['return_std']:.2f}%"
        data["sharpe_ratio"] = f"{data['sharpe_ratio']:,.2f}"
        data["ewm_sharpe"] = f"{data['ewm_sharpe']:,.2f}"
        data["return_drawdown_ratio"] = f"{data['return_drawdown_ratio']:,.2f}"

        for key, cell in self.cells.items():
            value = data.get(key, "")
            cell.setText(str(value))


class BacktestingSettingEditor(QtWidgets.QDialog):
    """
    For creating new strategy and editing strategy parameters.
    """

    def __init__(
        self, class_name: str, parameters: dict, vt_symbol: str = ""
    ) -> None:
        """"""
        super().__init__()

        self.class_name: str = class_name
        self.parameters: dict = parameters
        self.vt_symbol: str = vt_symbol
        self.edits: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        form: QtWidgets.QFormLayout = QtWidgets.QFormLayout()

        # Add vt_symbol and name edit if add new strategy
        self.setWindowTitle(_("策略参数配置：{}").format(self.class_name))
        button_text: str = _("确定")

        # 如果有 vt_symbol，尝试加载最优参数
        if self.vt_symbol:
            self._load_optimized_params()

        parameters: dict = self.parameters

        for name, value in parameters.items():
            type_ = type(value)

            edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(value))
            if type_ is int:
                int_validator: QtGui.QIntValidator = QtGui.QIntValidator()
                edit.setValidator(int_validator)
            elif type_ is float:
                double_validator: QtGui.QDoubleValidator = QtGui.QDoubleValidator()
                edit.setValidator(double_validator)

            form.addRow(f"{name} {type_}", edit)

            self.edits[name] = (edit, type_)

        button: QtWidgets.QPushButton = QtWidgets.QPushButton(button_text)
        button.clicked.connect(self.accept)
        form.addRow(button)

        widget: QtWidgets.QWidget = QtWidgets.QWidget()
        widget.setLayout(form)

        scroll: QtWidgets.QScrollArea = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(scroll)
        self.setLayout(vbox)

    def _load_optimized_params(self) -> None:
        """从配置文件加载最优参数"""
        try:
            print(f"\n=== 开始加载最优参数 ===")
            print(f"策略类名: {self.class_name}")
            print(f"品种代码: {self.vt_symbol}")

            # 延迟导入避免循环依赖
            import sys
            from pathlib import Path
            project_root = Path(__file__).parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))

            from core.utils.strategy_param_manager import get_param_manager

            param_manager = get_param_manager()

            # 转换策略类名为配置文件格式
            import re
            class_name = self.class_name
            if class_name.endswith("Strategy"):
                class_name = class_name[:-8]
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
            strategy_name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

            print(f"策略配置名: {strategy_name}")

            # 获取最优参数
            optimized_params = param_manager.get_params(
                strategy_name=strategy_name,
                symbol=self.vt_symbol
            )

            print(f"获取到的最优参数: {optimized_params}")

            if optimized_params:
                # 填充最优参数（覆盖默认参数）
                # 注意：get_params() 现在只返回交易参数，不包含性能指标
                # 直接覆盖所有默认参数
                count = 0
                for key, value in optimized_params.items():
                    self.parameters[key] = value
                    count += 1

                print(f"✓ 已加载 {self.vt_symbol} 的最优参数: {count} 个参数")
                print(f"更新后的参数: {self.parameters}")
            else:
                print(f"❌ 未找到 {self.vt_symbol} 的最优参数")

        except Exception as e:
            print(f"❌ 加载最优参数失败: {e}")
            import traceback
            traceback.print_exc()

    def get_setting(self) -> dict:
        """"""
        setting: dict = {}

        for name, tp in self.edits.items():
            edit, type_ = tp
            value_text = edit.text()

            if type_ is bool:
                if value_text == "True":
                    value = True
                else:
                    value = False
            else:
                value = type_(value_text)

            setting[name] = value

        return setting


class BacktesterChart(pg.GraphicsLayoutWidget):
    """"""

    def __init__(self) -> None:
        """"""
        super().__init__(title="Backtester Chart")

        self.dates: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        pg.setConfigOptions(antialias=True)

        # Create plot widgets
        self.balance_plot = self.addPlot(
            title=_("账户净值"),
            axisItems={"bottom": DateAxis(self.dates, orientation="bottom")}
        )
        self.nextRow()

        self.drawdown_plot = self.addPlot(
            title=_("净值回撤"),
            axisItems={"bottom": DateAxis(self.dates, orientation="bottom")}
        )
        self.nextRow()

        self.pnl_plot = self.addPlot(
            title=_("每日盈亏"),
            axisItems={"bottom": DateAxis(self.dates, orientation="bottom")}
        )
        self.nextRow()

        self.rolling_sharpe_plot = self.addPlot(
            title=_("滚动夏普比率"),
            axisItems={"bottom": DateAxis(self.dates, orientation="bottom")}
        )

        # Add curves and bars on plot widgets
        self.balance_curve = self.balance_plot.plot(
            pen=pg.mkPen("#ffc107", width=3)
        )

        dd_color: str = "#303f9f"
        self.drawdown_curve = self.drawdown_plot.plot(
            fillLevel=-0.3, brush=dd_color, pen=dd_color
        )

        profit_color: str = 'r'
        loss_color: str = 'g'
        self.profit_pnl_bar = pg.BarGraphItem(
            x=[], height=[], width=0.3, brush=profit_color, pen=profit_color
        )
        self.loss_pnl_bar = pg.BarGraphItem(
            x=[], height=[], width=0.3, brush=loss_color, pen=loss_color
        )
        self.pnl_plot.addItem(self.profit_pnl_bar)
        self.pnl_plot.addItem(self.loss_pnl_bar)

        # 滚动夏普比率曲线
        sharpe_color: str = "#2196F3"
        self.rolling_sharpe_curve = self.rolling_sharpe_plot.plot(
            pen=pg.mkPen(sharpe_color, width=2)
        )
        
        # 添加夏普比率基准线
        baseline_color: str = "#FF5722"
        self.sharpe_baseline = self.rolling_sharpe_plot.plot(
            pen=pg.mkPen(baseline_color, width=1, style=QtCore.Qt.DashLine)
        )

    def clear_data(self) -> None:
        """"""
        self.balance_curve.setData([], [])
        self.drawdown_curve.setData([], [])
        self.profit_pnl_bar.setOpts(x=[], height=[])
        self.loss_pnl_bar.setOpts(x=[], height=[])
        self.rolling_sharpe_curve.setData([], [])
        self.sharpe_baseline.setData([], [])

    def set_data(self, df: DataFrame) -> None:
        """"""
        if df is None:
            return

        count: int = len(df)

        self.dates.clear()
        for n, date in enumerate(df.index):
            self.dates[n] = date

        # Set data for curve of balance and drawdown
        self.balance_curve.setData(df["balance"])
        self.drawdown_curve.setData(df["drawdown"])

        # Set data for daily pnl bar
        profit_pnl_x: list = []
        profit_pnl_height: list = []
        loss_pnl_x: list = []
        loss_pnl_height: list = []

        for count, pnl in enumerate(df["net_pnl"]):
            if pnl >= 0:
                profit_pnl_height.append(pnl)
                profit_pnl_x.append(count)
            else:
                loss_pnl_height.append(pnl)
                loss_pnl_x.append(count)

        self.profit_pnl_bar.setOpts(x=profit_pnl_x, height=profit_pnl_height)
        self.loss_pnl_bar.setOpts(x=loss_pnl_x, height=loss_pnl_height)

        # 计算滚动夏普比率
        rolling_sharpe = self.calculate_rolling_sharpe(df["net_pnl"])
        if len(rolling_sharpe) > 0:
            # 滚动夏普比率曲线
            self.rolling_sharpe_curve.setData(range(len(rolling_sharpe)), rolling_sharpe)
            
            # 夏普比率基准线 (通常设为1.0)
            baseline_y = [1.0] * len(rolling_sharpe)
            self.sharpe_baseline.setData(range(len(baseline_y)), baseline_y)

    def calculate_rolling_sharpe(self, pnl_series, window=30):
        """
        计算滚动夏普比率
        """
        if len(pnl_series) < window:
            return []
        
        rolling_sharpe = []
        
        for i in range(window, len(pnl_series) + 1):
            # 获取窗口内的收益数据
            window_pnl = pnl_series[i-window:i]
            
            # 计算平均收益和标准差
            mean_return = np.mean(window_pnl)
            std_return = np.std(window_pnl, ddof=1)
            
            # 计算夏普比率 (假设无风险利率为0)
            if std_return > 0:
                sharpe = mean_return / std_return * np.sqrt(252)  # 年化
            else:
                sharpe = 0
            
            rolling_sharpe.append(sharpe)
        
        return rolling_sharpe


class DateAxis(pg.AxisItem):
    """Axis for showing date data"""

    def __init__(self, dates: dict, *args: Any, **kwargs: Any) -> None:
        """"""
        super().__init__(*args, **kwargs)
        self.dates: dict = dates

    def tickStrings(self, values: list, scale: float, spacing: float) -> list:
        """"""
        strings: list = []
        for v in values:
            dt = self.dates.get(v, "")
            strings.append(str(dt))
        return strings


class OptimizationSettingEditor(QtWidgets.QDialog):
    """
    For setting up parameters for optimization.
    """
    DISPLAY_NAME_MAP: dict = {
        _("总收益率"): "total_return",
        _("夏普比率"): "sharpe_ratio",
        _("EWM夏普"): "ewm_sharpe",
        _("收益回撤比"): "return_drawdown_ratio",
        _("日均盈亏"): "daily_net_pnl"
    }

    def __init__(
        self, class_name: str, parameters: dict
    ) -> None:
        """"""
        super().__init__()

        self.class_name: str = class_name
        self.parameters: dict = parameters
        self.edits: dict = {}

        self.optimization_setting: OptimizationSetting = None
        self.use_ga: bool = False

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.target_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()
        self.target_combo.addItems(list(self.DISPLAY_NAME_MAP.keys()))

        self.worker_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.worker_spin.setRange(0, 10000)
        self.worker_spin.setValue(0)
        self.worker_spin.setToolTip(_("设为0则自动根据CPU核心数启动对应数量的进程"))

        grid: QtWidgets.QGridLayout = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel(_("优化目标")), 0, 0)
        grid.addWidget(self.target_combo, 0, 1, 1, 3)
        grid.addWidget(QtWidgets.QLabel(_("进程上限")), 1, 0)
        grid.addWidget(self.worker_spin, 1, 1, 1, 3)
        grid.addWidget(QtWidgets.QLabel(_("参数")), 2, 0)
        grid.addWidget(QtWidgets.QLabel(_("开始")), 2, 1)
        grid.addWidget(QtWidgets.QLabel(_("步进")), 2, 2)
        grid.addWidget(QtWidgets.QLabel(_("结束")), 2, 3)

        # Add vt_symbol and name edit if add new strategy
        self.setWindowTitle(_("优化参数配置：{}").format(self.class_name))

        validator: QtGui.QDoubleValidator = QtGui.QDoubleValidator()
        row: int = 3

        for name, value in self.parameters.items():
            type_ = type(value)
            if type_ not in [int, float]:
                continue

            start_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(value))
            step_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(1))
            end_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(value))

            for edit in [start_edit, step_edit, end_edit]:
                edit.setValidator(validator)

            grid.addWidget(QtWidgets.QLabel(name), row, 0)
            grid.addWidget(start_edit, row, 1)
            grid.addWidget(step_edit, row, 2)
            grid.addWidget(end_edit, row, 3)

            self.edits[name] = {
                "type": type_,
                "start": start_edit,
                "step": step_edit,
                "end": end_edit
            }

            row += 1

        parallel_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("多进程优化"))
        parallel_button.clicked.connect(self.generate_parallel_setting)
        grid.addWidget(parallel_button, row, 0, 1, 4)

        row += 1
        ga_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("遗传算法优化"))
        ga_button.clicked.connect(self.generate_ga_setting)
        grid.addWidget(ga_button, row, 0, 1, 4)

        widget: QtWidgets.QWidget = QtWidgets.QWidget()
        widget.setLayout(grid)

        scroll: QtWidgets.QScrollArea = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(scroll)
        self.setLayout(vbox)

    def generate_ga_setting(self) -> None:
        """"""
        self.use_ga = True
        self.generate_setting()

    def generate_parallel_setting(self) -> None:
        """"""
        self.use_ga = False
        self.generate_setting()

    def generate_setting(self) -> None:
        """"""
        self.optimization_setting = OptimizationSetting()

        self.target_display: str = self.target_combo.currentText()
        target_name: str = self.DISPLAY_NAME_MAP[self.target_display]
        self.optimization_setting.set_target(target_name)

        for name, d in self.edits.items():
            type_ = d["type"]
            start_value = type_(d["start"].text())
            step_value = type_(d["step"].text())
            end_value = type_(d["end"].text())

            if start_value == end_value:
                self.optimization_setting.add_parameter(name, start_value)
            else:
                self.optimization_setting.add_parameter(
                    name,
                    start_value,
                    end_value,
                    step_value
                )

        self.accept()

    def get_setting(self) -> tuple[OptimizationSetting, bool, int]:
        """"""
        return self.optimization_setting, self.use_ga, self.worker_spin.value()


class OptimizationResultMonitor(QtWidgets.QDialog):
    """
    For viewing optimization result.
    """

    def __init__(
        self, result_values: list, target_display: str
    ) -> None:
        """"""
        super().__init__()

        self.result_values: list = result_values
        self.target_display: str = target_display

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.setWindowTitle(_("参数优化结果"))
        self.resize(1100, 500)

        # Creat table to show result
        table: QtWidgets.QTableWidget = QtWidgets.QTableWidget()

        table.setColumnCount(2)
        table.setRowCount(len(self.result_values))
        table.setHorizontalHeaderLabels([_("参数"), self.target_display])
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)

        table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch
        )

        for n, tp in enumerate(self.result_values):
            setting, target_value, __ = tp
            setting_cell: QtWidgets.QTableWidgetItem = QtWidgets.QTableWidgetItem(str(setting))
            target_cell: QtWidgets.QTableWidgetItem = QtWidgets.QTableWidgetItem(f"{target_value:.2f}")

            setting_cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            target_cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

            table.setItem(n, 0, setting_cell)
            table.setItem(n, 1, target_cell)

        # Create layout
        button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("保存"))
        button.clicked.connect(self.save_csv)

        hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox.addStretch()
        hbox.addWidget(button)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(table)
        vbox.addLayout(hbox)

        self.setLayout(vbox)

    def save_csv(self) -> None:
        """
        Save table data into a csv file
        """
        path, __ = QtWidgets.QFileDialog.getSaveFileName(
            self, _("保存数据"), "", "CSV(*.csv)")

        if not path:
            return

        with open(path, "w") as f:
            writer = csv.writer(f, lineterminator="\n")

            writer.writerow([_("参数"), self.target_display])

            for tp in self.result_values:
                setting, target_value, __ = tp
                row_data: list = [str(setting), str(target_value)]
                writer.writerow(row_data)


class BacktestingTradeMonitor(BaseMonitor):
    """
    Monitor for backtesting trade data.
    """

    headers: dict = {
        "tradeid": {"display": _("成交号 "), "cell": BaseCell, "update": False},
        "orderid": {"display": _("委托号"), "cell": BaseCell, "update": False},
        "symbol": {"display": _("代码"), "cell": BaseCell, "update": False},
        "exchange": {"display": _("交易所"), "cell": EnumCell, "update": False},
        "direction": {"display": _("方向"), "cell": DirectionCell, "update": False},
        "offset": {"display": _("开平"), "cell": EnumCell, "update": False},
        "price": {"display": _("价格"), "cell": BaseCell, "update": False},
        "volume": {"display": _("数量"), "cell": BaseCell, "update": False},
        "datetime": {"display": _("时间"), "cell": BaseCell, "update": False},
        "gateway_name": {"display": _("接口"), "cell": BaseCell, "update": False},
    }


class BacktestingOrderMonitor(BaseMonitor):
    """
    Monitor for backtesting order data.
    """

    headers: dict = {
        "orderid": {"display": _("委托号"), "cell": BaseCell, "update": False},
        "symbol": {"display": _("代码"), "cell": BaseCell, "update": False},
        "exchange": {"display": _("交易所"), "cell": EnumCell, "update": False},
        "type": {"display": _("类型"), "cell": EnumCell, "update": False},
        "direction": {"display": _("方向"), "cell": DirectionCell, "update": False},
        "offset": {"display": _("开平"), "cell": EnumCell, "update": False},
        "price": {"display": _("价格"), "cell": BaseCell, "update": False},
        "volume": {"display": _("总数量"), "cell": BaseCell, "update": False},
        "traded": {"display": _("已成交"), "cell": BaseCell, "update": False},
        "status": {"display": _("状态"), "cell": EnumCell, "update": False},
        "datetime": {"display": _("时间"), "cell": BaseCell, "update": False},
        "gateway_name": {"display": _("接口"), "cell": BaseCell, "update": False},
    }


class FloatCell(BaseCell):
    """
    Cell used for showing pnl data.
    """

    def __init__(self, content: Any, data: Any) -> None:
        """"""
        content = f"{content:.2f}"
        super().__init__(content, data)


class DailyResultMonitor(BaseMonitor):
    """
    Monitor for backtesting daily result.
    """

    headers: dict = {
        "date": {"display": _("日期"), "cell": BaseCell, "update": False},
        "trade_count": {"display": _("成交笔数"), "cell": BaseCell, "update": False},
        "start_pos": {"display": _("开盘持仓"), "cell": BaseCell, "update": False},
        "end_pos": {"display": _("收盘持仓"), "cell": BaseCell, "update": False},
        "turnover": {"display": _("成交额"), "cell": FloatCell, "update": False},
        "commission": {"display": _("手续费"), "cell": FloatCell, "update": False},
        "slippage": {"display": _("滑点"), "cell": FloatCell, "update": False},
        "trading_pnl": {"display": _("交易盈亏"), "cell": FloatCell, "update": False},
        "holding_pnl": {"display": _("持仓盈亏"), "cell": FloatCell, "update": False},
        "total_pnl": {"display": _("总盈亏"), "cell": FloatCell, "update": False},
        "net_pnl": {"display": _("净盈亏"), "cell": FloatCell, "update": False},
    }


class BacktestingResultDialog(QtWidgets.QDialog):
    """"""

    def __init__(
        self,
        main_engine: MainEngine,
        event_engine: EventEngine,
        title: str,
        table_class: type[BaseMonitor]
    ) -> None:
        """"""
        super().__init__()

        self.main_engine: MainEngine = main_engine
        self.event_engine: EventEngine = event_engine
        self.title: str = title
        self.table_class: type[BaseMonitor] = table_class

        self.updated: bool = False

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.setWindowTitle(self.title)
        self.resize(1100, 600)

        self.table: BaseMonitor = self.table_class(self.main_engine, self.event_engine)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.table)

        self.setLayout(vbox)

    def clear_data(self) -> None:
        """"""
        self.updated = False
        self.table.setRowCount(0)

    def update_data(self, data: list) -> None:
        """"""
        self.updated = True

        data.reverse()
        for obj in data:
            self.table.insert_new_row(obj)

    def is_updated(self) -> bool:
        """"""
        return self.updated


class CandleChartDialog(QtWidgets.QDialog):
    """
    回测K线图表对话框
    
    本类已经集成了EnhancedChartWidget，提供以下功能：
    1. 增强版K线图表显示（支持多种技术指标）
    2. 多周期切换功能
    3. 交易信号标记
    4. 自动回退到标准ChartWidget（如果EnhancedChartWidget不可用）
    
    注意：
    - 这是唯一的K线图表对话框类
    - EnhancedChartWidget来自core/charts/enhanced_chart_widget.py
    - 如果需要修改图表功能，请修改EnhancedChartWidget，而非此类
    """

    def __init__(self) -> None:
        """"""
        super().__init__()

        self.updated: bool = False

        self.dt_ix_map: dict = {}
        self.ix_bar_map: dict = {}

        self.high_price = 0
        self.low_price = 0
        self.price_range = 0

        self.items: list = []

        # 保存原始交易数据用于多周期切换
        self.trade_data: list = []

        # 双图模式相关
        self.is_dual_mode: bool = False
        self.dual_chart = None

        self.init_ui()

    def init_ui(self) -> None:
        """初始化UI界面"""
        self.setWindowTitle(_("回测K线图表(增强版)"))
        self.resize(1600, 900)

        # 创建增强版图表组件（优先使用EnhancedChartWidget）
        try:
            from core.charts import EnhancedChartWidget
            self.chart = EnhancedChartWidget()
        except ImportError as e:
            # 如果增强图表不可用，回退到标准图表
            print(f"[K线图表] 导入EnhancedChartWidget失败(ImportError): {e}")
            print("[K线图表] 回退到标准ChartWidget")
            self.chart = ChartWidget()
            self.chart.add_plot("candle", hide_x_axis=True)
            self.chart.add_plot("volume", maximum_height=200)
            self.chart.add_item(CandleItem, "candle", "candle")
            self.chart.add_item(VolumeItem, "volume", "volume")
            self.chart.add_cursor()
        except Exception as e:
            # 捕获其他异常
            print(f"[K线图表] 加载EnhancedChartWidget失败(Exception): {e}")
            print("[K线图表] 回退到标准ChartWidget")
            self.chart = ChartWidget()
            self.chart.add_plot("candle", hide_x_axis=True)
            self.chart.add_plot("volume", maximum_height=200)
            self.chart.add_item(CandleItem, "candle", "candle")
            self.chart.add_item(VolumeItem, "volume", "volume")
            self.chart.add_cursor()

        # 创建双图组件（但默认不显示）
        try:
            from core.charts import DualChartWidget
            self.dual_chart = DualChartWidget(left_period="15m", right_period="1h")
            self.dual_chart.hide()  # 默认隐藏
        except ImportError as e:
            print(f"[K线图表] 导入DualChartWidget失败: {e}")
            self.dual_chart = None
        except Exception as e:
            print(f"[K线图表] 创建DualChartWidget失败: {e}")
            self.dual_chart = None

        # 创建四图组件（但默认不显示）
        try:
            from core.charts import QuadChartWidget
            self.quad_chart = QuadChartWidget(
                top_left_period="5m",
                top_right_period="15m",
                bottom_left_period="1h",
                bottom_right_period="d"
            )
            self.quad_chart.hide()  # 默认隐藏
        except ImportError as e:
            print(f"[K线图表] 导入QuadChartWidget失败: {e}")
            self.quad_chart = None
        except Exception as e:
            print(f"[K线图表] 创建QuadChartWidget失败: {e}")
            self.quad_chart = None

        # 创建顶部工具栏
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(5)
        toolbar.setContentsMargins(10, 5, 10, 5)

        # 模式切换按钮组（文字风格 - 分段控制器）
        if self.dual_chart or self.quad_chart:
            # 创建按钮组
            self.mode_button_group = QtWidgets.QButtonGroup(self)

            # 单图按钮
            self.single_mode_btn = QtWidgets.QPushButton("单图")
            self.single_mode_btn.setCheckable(True)
            self.single_mode_btn.setChecked(True)  # 默认单图模式
            self.single_mode_btn.setFixedSize(50, 28)

            # 双图按钮
            self.dual_mode_btn = QtWidgets.QPushButton("双图")
            self.dual_mode_btn.setCheckable(True)
            self.dual_mode_btn.setFixedSize(50, 28)

            # 四图按钮
            self.quad_mode_btn = QtWidgets.QPushButton("四图")
            self.quad_mode_btn.setCheckable(True)
            self.quad_mode_btn.setFixedSize(50, 28)

            # 设置按钮样式（分段控制器风格）
            button_style = """
                QPushButton {
                    background-color: #555;
                    color: #aaa;
                    border: 1px solid #444;
                    font-size: 11px;
                    font-weight: normal;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #666;
                    color: #fff;
                }
                QPushButton:checked {
                    background-color: #0078d4;
                    color: white;
                    font-weight: bold;
                    border: 1px solid #0078d4;
                }
            """

            # 单图按钮左圆角
            self.single_mode_btn.setStyleSheet(button_style + """
                QPushButton {
                    border-top-left-radius: 4px;
                    border-bottom-left-radius: 4px;
                    border-right: none;
                }
            """)

            # 双图按钮中间（无圆角）
            self.dual_mode_btn.setStyleSheet(button_style + """
                QPushButton {
                    border-right: none;
                }
            """)

            # 四图按钮右圆角
            self.quad_mode_btn.setStyleSheet(button_style + """
                QPushButton {
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
            """)

            # 添加到按钮组
            self.mode_button_group.addButton(self.single_mode_btn, 0)
            self.mode_button_group.addButton(self.dual_mode_btn, 1)
            self.mode_button_group.addButton(self.quad_mode_btn, 2)

            # 连接信号
            self.mode_button_group.idClicked.connect(self._on_mode_changed)

            # 添加到工具栏
            toolbar.addWidget(QtWidgets.QLabel("视图:"))
            toolbar.addWidget(self.single_mode_btn)
            toolbar.addWidget(self.dual_mode_btn)
            toolbar.addWidget(self.quad_mode_btn)

        toolbar.addStretch()

        # 主布局
        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.setSpacing(0)
        vbox.setContentsMargins(0, 0, 0, 0)

        # 添加工具栏（只有在有按钮时才添加）
        if self.dual_chart or self.quad_chart:
            vbox.addLayout(toolbar)

        # 添加图表（单图默认显示）
        vbox.addWidget(self.chart)

        # 添加双图组件（默认隐藏）
        if self.dual_chart:
            vbox.addWidget(self.dual_chart)

        # 添加四图组件（默认隐藏）
        if self.quad_chart:
            vbox.addWidget(self.quad_chart)

        self.setLayout(vbox)

        # 如果使用的是EnhancedChartWidget，注册周期切换回调
        if hasattr(self.chart, 'on_interval_changed_callback'):
            self.chart.on_interval_changed_callback = self._on_interval_changed

    def update_history(self, history: list) -> None:
        """"""
        self.updated = True

        # 如果使用的是EnhancedChartWidget，设置交易时段和多周期功能
        if hasattr(self.chart, 'set_trading_session_by_symbol') and history:
            first_bar = history[0]
            symbol = first_bar.symbol
            exchange = first_bar.exchange.value if hasattr(first_bar.exchange, 'value') else str(first_bar.exchange)

            # 设置交易时段（用于多周期聚合）
            self.chart.set_trading_session_by_symbol(symbol, exchange)

            # 保存基础数据（用于多周期切换）
            if hasattr(self.chart, 'base_minute_bars'):
                self.chart.base_minute_bars = history.copy()
                self.chart.current_symbol = symbol
                self.chart.current_exchange = exchange

        self.chart.update_history(history)

        # 如果双图组件存在且当前处于双图模式，也更新双图
        if self.dual_chart and self.is_dual_mode:
            self.dual_chart.update_history(history)

            # 设置交易时段
            if history:
                first_bar = history[0]
                symbol = first_bar.symbol
                exchange = first_bar.exchange.value if hasattr(first_bar.exchange, 'value') else str(first_bar.exchange)
                self.dual_chart.set_trading_session_by_symbol(symbol, exchange)

        for ix, bar in enumerate(history):
            self.ix_bar_map[ix] = bar
            self.dt_ix_map[bar.datetime] = ix

            if not self.high_price:
                self.high_price = bar.high_price
                self.low_price = bar.low_price
            else:
                self.high_price = max(self.high_price, bar.high_price)
                self.low_price = min(self.low_price, bar.low_price)

        self.price_range = self.high_price - self.low_price

        # 如果有交易数据，自动重绘交易连线（支持多周期切换）
        if self.trade_data:
            self.redraw_trades()

    def _calculate_bar_duration(self, interval: Interval) -> int:
        """
        计算K线周期对应的分钟数

        Args:
            interval: K线周期

        Returns:
            周期对应的分钟数
        """
        interval_minutes = {
            Interval.MINUTE: 1,
            Interval.HOUR: 60,
            Interval.DAILY: 1440,  # 24小时
        }

        # 如果是字符串类型(如"5m", "15m")
        if isinstance(interval, str):
            if interval == "1m":
                return 1
            elif interval == "5m":
                return 5
            elif interval == "15m":
                return 15
            elif interval == "1h":
                return 60
            elif interval == "d":
                return 1440
            else:
                # 尝试解析分钟数（如"30m" -> 30）
                if interval.endswith("m"):
                    try:
                        return int(interval[:-1])
                    except:
                        pass
                return 1  # 默认1分钟

        # 如果是Interval枚举
        return interval_minutes.get(interval, 1)

    def get_bar_time_range(self, bar: BarData) -> tuple:
        """
        计算K线的时间范围

        Args:
            bar: K线数据

        Returns:
            (start_time, end_time) 元组
        """
        start_time = bar.datetime
        duration_minutes = self._calculate_bar_duration(bar.interval)
        end_time = start_time + timedelta(minutes=duration_minutes)

        return (start_time, end_time)

    def find_nearest_bar_index(self, trade_dt: datetime) -> int:
        """
        智能查找交易时间对应的K线索引（支持多周期）

        匹配策略：
        1. 精确匹配：交易时间刚好等于某根K线时间
        2. 范围匹配：交易时间落在某根K线的时间范围内（用于聚合周期）
        3. 最近匹配：找最接近的K线（兜底策略）

        Args:
            trade_dt: 交易时间

        Returns:
            K线索引，如果找不到返回None
        """
        # 策略1：精确匹配
        if trade_dt in self.dt_ix_map:
            return self.dt_ix_map[trade_dt]

        # 策略2：范围匹配（用于多周期）
        for ix, bar in self.ix_bar_map.items():
            start_time, end_time = self.get_bar_time_range(bar)
            # 交易时间落在K线时间范围内
            if start_time <= trade_dt < end_time:
                return ix

        # 策略3：最近匹配（兜底）
        if not self.dt_ix_map:
            return None

        min_diff = float('inf')
        closest_ix = None

        for dt, ix in self.dt_ix_map.items():
            diff = abs((dt - trade_dt).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest_ix = ix

        return closest_ix

    def update_trades(self, trades: list) -> None:
        """
        更新交易数据并绘制买卖点连线（支持多周期）

        Args:
            trades: 交易列表
        """
        # 保存原始交易数据，用于周期切换时重绘
        self.trade_data = trades

        # 配对交易
        trade_pairs: list = generate_trade_pairs(trades)

        candle_plot: pg.PlotItem = self.chart.get_plot("candle")

        scatter_data: list = []

        y_adjustment: float = self.price_range * 0.001

        for d in trade_pairs:
            # 使用智能时间匹配获取K线索引
            open_ix = self.find_nearest_bar_index(d["open_dt"])
            close_ix = self.find_nearest_bar_index(d["close_dt"])

            # 如果找不到对应的K线索引，跳过这笔交易
            if open_ix is None or close_ix is None:
                continue

            open_price = d["open_price"]
            close_price = d["close_price"]

            # Trade Line
            x: list = [open_ix, close_ix]
            y: list = [open_price, close_price]

            if d["direction"] == Direction.LONG and close_price >= open_price:
                color: str = "r"
            elif d["direction"] == Direction.SHORT and close_price <= open_price:
                color = "r"
            else:
                color = "g"

            # 加粗连线，使用更醒目的宽度和样式
            pen: QtGui.QPen = pg.mkPen(color, width=3, style=QtCore.Qt.PenStyle.DashLine)
            item: pg.PlotCurveItem = pg.PlotCurveItem(x, y, pen=pen)

            self.items.append(item)
            candle_plot.addItem(item)

            # Trade Scatter
            open_bar: BarData = self.ix_bar_map[open_ix]
            close_bar: BarData = self.ix_bar_map[close_ix]

            if d["direction"] == Direction.LONG:
                scatter_color: str = "yellow"
                open_symbol: str = "t1"
                close_symbol: str = "t"
                open_side: int = 1
                close_side: int = -1
                open_y: float = open_bar.low_price
                close_y: float = close_bar.high_price
            else:
                scatter_color = "magenta"
                open_symbol = "t"
                close_symbol = "t1"
                open_side = -1
                close_side = 1
                open_y = open_bar.high_price
                close_y = close_bar.low_price

            pen = pg.mkPen(QtGui.QColor(scatter_color))
            brush: QtGui.QBrush = pg.mkBrush(QtGui.QColor(scatter_color))
            size: int = 10

            open_scatter: dict = {
                "pos": (open_ix, open_y - open_side * y_adjustment),
                "size": size,
                "pen": pen,
                "brush": brush,
                "symbol": open_symbol
            }

            close_scatter: dict = {
                "pos": (close_ix, close_y - close_side * y_adjustment),
                "size": size,
                "pen": pen,
                "brush": brush,
                "symbol": close_symbol
            }

            scatter_data.append(open_scatter)
            scatter_data.append(close_scatter)

            # Trade text
            volume = d["volume"]
            text_color: QtGui.QColor = QtGui.QColor(scatter_color)
            open_text: pg.TextItem = pg.TextItem(f"[{volume}]", color=text_color, anchor=(0.5, 0.5))
            close_text: pg.TextItem = pg.TextItem(f"[{volume}]", color=text_color, anchor=(0.5, 0.5))

            open_text.setPos(open_ix, open_y - open_side * y_adjustment * 3)
            close_text.setPos(close_ix, close_y - close_side * y_adjustment * 3)

            self.items.append(open_text)
            self.items.append(close_text)

            candle_plot.addItem(open_text)
            candle_plot.addItem(close_text)

        if scatter_data:
            trade_scatter: pg.ScatterPlotItem = pg.ScatterPlotItem(scatter_data)
            self.items.append(trade_scatter)
            candle_plot.addItem(trade_scatter)

    def redraw_trades(self) -> None:
        """
        重绘交易连线（用于周期切换后）

        清除现有的交易连线和标记，然后重新绘制
        """
        if not self.trade_data:
            return

        # 清除现有的交易图形项
        candle_plot: pg.PlotItem = self.chart.get_plot("candle")
        for item in self.items:
            candle_plot.removeItem(item)
        self.items.clear()

        # 使用保存的交易数据重新绘制
        self.update_trades(self.trade_data)

    def _on_mode_changed(self, mode_id: int):
        """
        模式切换处理

        Args:
            mode_id: 0=单图模式, 1=双图模式, 2=四图模式
        """
        if mode_id == 1 and not self.dual_chart:
            return
        if mode_id == 2 and not self.quad_chart:
            return

        # 隐藏所有图表
        self.chart.hide()
        if self.dual_chart:
            self.dual_chart.hide()
        if self.quad_chart:
            self.quad_chart.hide()

        # 根据模式显示对应图表
        if mode_id == 0:
            # 单图模式
            self.chart.show()
            self.is_dual_mode = False

        elif mode_id == 1:
            # 双图模式
            self.dual_chart.show()
            self.is_dual_mode = True

            # 如果有历史数据，更新双图
            if hasattr(self.chart, 'base_minute_bars') and self.chart.base_minute_bars:
                self.dual_chart.update_history(self.chart.base_minute_bars)

                # 设置交易时段
                if hasattr(self.chart, 'current_symbol'):
                    self.dual_chart.set_trading_session_by_symbol(
                        self.chart.current_symbol,
                        self.chart.current_exchange or ""
                    )

                # 激活对应的周期按钮
                self._activate_dual_chart_period_buttons()

                # 绘制交易连线
                if self.trade_data:
                    self._draw_dual_chart_trades()


        elif mode_id == 2:
            # 四图模式
            self.quad_chart.show()

            # 如果有历史数据，更新四图
            if hasattr(self.chart, 'base_minute_bars') and self.chart.base_minute_bars:
                self.quad_chart.update_history(self.chart.base_minute_bars)

                # 设置交易时段
                if hasattr(self.chart, 'current_symbol'):
                    self.quad_chart.set_trading_session_by_symbol(
                        self.chart.current_symbol,
                        self.chart.current_exchange or ""
                    )

                # 激活对应的周期按钮
                self._activate_quad_chart_period_buttons()

                # 绘制交易连线
                if self.trade_data:
                    self._draw_quad_chart_trades()


    def _activate_dual_chart_period_buttons(self):
        """激活双图对应的周期按钮"""
        try:
            # 获取左右图表的周期
            left_period = self.dual_chart.left_period
            right_period = self.dual_chart.right_period

            # 获取周期到按钮的映射
            period_button_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1h",
                "d": "d"
            }

            # 激活左侧图表的周期按钮
            if left_period in period_button_map and hasattr(self.dual_chart.left_chart, 'interval_buttons'):
                button_key = period_button_map[left_period]
                if button_key in self.dual_chart.left_chart.interval_buttons:
                    # 先取消所有按钮
                    for btn in self.dual_chart.left_chart.interval_buttons.values():
                        btn.setChecked(False)
                    # 激活对应按钮
                    self.dual_chart.left_chart.interval_buttons[button_key].setChecked(True)

            # 激活右侧图表的周期按钮
            if right_period in period_button_map and hasattr(self.dual_chart.right_chart, 'interval_buttons'):
                button_key = period_button_map[right_period]
                if button_key in self.dual_chart.right_chart.interval_buttons:
                    # 先取消所有按钮
                    for btn in self.dual_chart.right_chart.interval_buttons.values():
                        btn.setChecked(False)
                    # 激活对应按钮
                    self.dual_chart.right_chart.interval_buttons[button_key].setChecked(True)

        except Exception:
            pass  # 静默失败

    def _activate_quad_chart_period_buttons(self):
        """激活四图对应的周期按钮"""
        try:
            # 获取四个图表的周期
            periods = self.quad_chart.periods

            # 获取周期到按钮的映射
            period_button_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1h",
                "d": "d"
            }

            # 遍历四个图表，激活对应的周期按钮
            for chart_name, period in periods.items():
                chart = self.quad_chart.charts[chart_name]

                if period in period_button_map and hasattr(chart, 'interval_buttons'):
                    button_key = period_button_map[period]
                    if button_key in chart.interval_buttons:
                        # 先取消所有按钮
                        for btn in chart.interval_buttons.values():
                            btn.setChecked(False)
                        # 激活对应按钮
                        chart.interval_buttons[button_key].setChecked(True)

        except Exception as e:
            pass  # 静默失败

    def _draw_quad_chart_trades(self):
        """在四图上绘制交易连线"""
        try:
            # 遍历四个图表
            for chart_name, chart in self.quad_chart.charts.items():
                bars = chart._manager.get_all_bars()
                if not bars:
                    continue

                # 为每个图表绘制交易连线
                self._draw_trades_on_chart(chart, bars, chart_name)


        except Exception as e:
            import traceback
            traceback.print_exc()

    def _draw_dual_chart_trades(self):
        """在双图上绘制交易连线"""
        try:
            # 获取左右图表
            left_chart = self.dual_chart.left_chart
            right_chart = self.dual_chart.right_chart

            # 获取左右图表的K线数据
            left_bars = left_chart._manager.get_all_bars()
            right_bars = right_chart._manager.get_all_bars()

            if not left_bars or not right_bars:
                return

            # 为左侧图表绘制交易连线
            self._draw_trades_on_chart(left_chart, left_bars, "左侧")

            # 为右侧图表绘制交易连线
            self._draw_trades_on_chart(right_chart, right_bars, "右侧")


        except Exception as e:
            import traceback
            traceback.print_exc()

    def _draw_trades_on_chart(self, chart, bars, chart_name):
        """
        在指定图表上绘制交易连线

        Args:
            chart: EnhancedChartWidget实例
            bars: K线数据
            chart_name: 图表名称（用于日志）
        """
        if not self.trade_data:
            return

        # 配对交易
        trade_pairs: list = generate_trade_pairs(self.trade_data)

        candle_plot: pg.PlotItem = chart.get_plot("candle")
        if not candle_plot:
            return

        # 构建时间索引映射
        dt_ix_map = {}
        ix_bar_map = {}
        high_price = 0
        low_price = 0

        for ix, bar in enumerate(bars):
            dt_ix_map[bar.datetime] = ix
            ix_bar_map[ix] = bar

            if not high_price:
                high_price = bar.high_price
                low_price = bar.low_price
            else:
                high_price = max(high_price, bar.high_price)
                low_price = min(low_price, bar.low_price)

        price_range = high_price - low_price
        y_adjustment: float = price_range * 0.001

        # 绘制交易对
        for d in trade_pairs:
            # 智能匹配K线索引
            open_ix = self._find_bar_index_for_trade(d["open_dt"], bars, dt_ix_map, ix_bar_map)
            close_ix = self._find_bar_index_for_trade(d["close_dt"], bars, dt_ix_map, ix_bar_map)

            if open_ix is None or close_ix is None:
                continue

            open_price = d["open_price"]
            close_price = d["close_price"]

            # Trade Line
            x: list = [open_ix, close_ix]
            y: list = [open_price, close_price]

            if d["direction"] == Direction.LONG and close_price >= open_price:
                color: str = "r"
            elif d["direction"] == Direction.SHORT and close_price <= open_price:
                color = "r"
            else:
                color = "g"

            # 加粗连线
            pen: QtGui.QPen = pg.mkPen(color, width=3, style=QtCore.Qt.PenStyle.DashLine)
            item: pg.PlotCurveItem = pg.PlotCurveItem(x, y, pen=pen)
            candle_plot.addItem(item)

            # Trade Scatter
            open_bar: BarData = ix_bar_map[open_ix]
            close_bar: BarData = ix_bar_map[close_ix]

            if d["direction"] == Direction.LONG:
                scatter_color: str = "yellow"
                open_symbol: str = "t1"
                close_symbol: str = "t"
                open_side: int = 1
                close_side: int = -1
                open_y: float = open_bar.low_price
                close_y: float = close_bar.high_price
            else:
                scatter_color = "magenta"
                open_symbol = "t"
                close_symbol = "t1"
                open_side = -1
                close_side = 1
                open_y = open_bar.high_price
                close_y = close_bar.low_price

            pen = pg.mkPen(QtGui.QColor(scatter_color))
            brush: QtGui.QBrush = pg.mkBrush(QtGui.QColor(scatter_color))
            size: int = 10

            open_scatter: dict = {
                "pos": (open_ix, open_y - open_side * y_adjustment),
                "size": size,
                "pen": pen,
                "brush": brush,
                "symbol": open_symbol
            }

            close_scatter: dict = {
                "pos": (close_ix, close_y - close_side * y_adjustment),
                "size": size,
                "pen": pen,
                "brush": brush,
                "symbol": close_symbol
            }

            scatter_item: pg.ScatterPlotItem = pg.ScatterPlotItem([open_scatter, close_scatter])
            candle_plot.addItem(scatter_item)


    def _find_bar_index_for_trade(self, trade_dt, bars, dt_ix_map, ix_bar_map):
        """
        为交易时间找到对应的K线索引（支持多周期）

        Args:
            trade_dt: 交易时间
            bars: K线数据列表
            dt_ix_map: 时间到索引的映射
            ix_bar_map: 索引到K线的映射

        Returns:
            K线索引，找不到返回None
        """
        # 策略1：精确匹配
        if trade_dt in dt_ix_map:
            return dt_ix_map[trade_dt]

        # 策略2：范围匹配（用于多周期）
        for ix, bar in ix_bar_map.items():
            start_time, end_time = self.get_bar_time_range(bar)
            if start_time <= trade_dt < end_time:
                return ix

        # 策略3：最近匹配
        min_diff = float('inf')
        closest_ix = None

        for dt, ix in dt_ix_map.items():
            diff = abs((dt - trade_dt).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest_ix = ix

        return closest_ix

    def _on_interval_changed(self, bars: list, interval: str) -> None:
        """
        周期切换回调处理方法

        当EnhancedChartWidget切换周期时，此方法会被调用
        用于更新买卖点连线的显示

        Args:
            bars: 新周期的K线数据列表
            interval: 新的周期字符串（如"1m", "5m", "15m", "1h", "d"）
        """

        # 第一步：清除现有的交易图形项
        candle_plot: pg.PlotItem = self.chart.get_plot("candle")
        for item in self.items:
            candle_plot.removeItem(item)
        self.items.clear()

        # 第二步：清空并重建时间索引映射
        self.dt_ix_map.clear()
        self.ix_bar_map.clear()

        # 重置价格范围
        self.high_price = 0
        self.low_price = 0
        self.price_range = 0

        # 重新构建索引映射和价格范围
        for ix, bar in enumerate(bars):
            self.ix_bar_map[ix] = bar
            self.dt_ix_map[bar.datetime] = ix

            if not self.high_price:
                self.high_price = bar.high_price
                self.low_price = bar.low_price
            else:
                self.high_price = max(self.high_price, bar.high_price)
                self.low_price = min(self.low_price, bar.low_price)

        self.price_range = self.high_price - self.low_price


        # 第三步：重绘交易连线
        if self.trade_data:
            self.update_trades(self.trade_data)
        else:
            print("  无交易数据需要重绘")


    def clear_data(self) -> None:
        """"""
        self.updated = False

        candle_plot: pg.PlotItem = self.chart.get_plot("candle")
        for item in self.items:
            candle_plot.removeItem(item)
        self.items.clear()

        self.chart.clear_all()

        self.dt_ix_map.clear()
        self.ix_bar_map.clear()

        # 清除保存的交易数据
        self.trade_data.clear()

    def closeEvent(self, event) -> None:
        """对话框关闭时清理资源，防止bus error"""
        # 清除交易连线
        candle_plot: pg.PlotItem = self.chart.get_plot("candle")
        for item in self.items:
            candle_plot.removeItem(item)
        self.items.clear()

        # 清除图表数据（包括所有indicators）
        self.chart.clear_all()

        # 清除映射
        self.dt_ix_map.clear()
        self.ix_bar_map.clear()
        self.trade_data.clear()

        # 标记为未更新，这样下次打开时会重新加载数据
        self.updated = False

        # 注意：双图/四图会被Qt自动清理，不需要手动deleteLater()
        # 它们是dialog的子widget，父对象销毁时会自动清理子对象

        super().closeEvent(event)

    def is_updated(self) -> bool:
        """"""
        return self.updated


def generate_trade_pairs(trades: list) -> list:
    """"""
    long_trades: list = []
    short_trades: list = []
    trade_pairs: list = []

    for trade in trades:
        trade = copy(trade)

        if trade.direction == Direction.LONG:
            same_direction: list = long_trades
            opposite_direction: list = short_trades
        else:
            same_direction = short_trades
            opposite_direction = long_trades

        while trade.volume and opposite_direction:
            open_trade: TradeData = opposite_direction[0]

            close_volume = min(open_trade.volume, trade.volume)
            d: dict = {
                "open_dt": open_trade.datetime,
                "open_price": open_trade.price,
                "close_dt": trade.datetime,
                "close_price": trade.price,
                "direction": open_trade.direction,
                "volume": close_volume,
            }
            trade_pairs.append(d)

            open_trade.volume -= close_volume
            if not open_trade.volume:
                opposite_direction.pop(0)

            trade.volume -= close_volume

        if trade.volume:
            same_direction.append(trade)

    return trade_pairs

# ===================================
# 回测管理器 - 选择使用的UI版本
# ===================================

# [SOLVED] 问题已解决！通过渐进式测试发现 emoji 字符导致 macOS bus error
# 已从 RedesignedBacktesterManager 移除所有 emoji，现在使用现代化界面

class BacktesterManager(RedesignedBacktesterManager):
    """
    使用重新设计的现代化回测管理器界面

    已修复的问题：
    - [OK] 延迟初始化引擎，避免 Qt + multiprocessing 冲突
    - [OK] 移除 emoji 字符，避免 macOS 渲染崩溃
    """
    pass

# 渐进式测试指南（已完成诊断，保留供参考）
#
# 通过测试 TestVersion1-6，确认了问题根源：
# - TestVersion1-5：正常 [OK]
# - TestVersion6（添加emoji）：闪退 [FAIL]
#
# 结论：emoji 字符在 macOS 上触发 bus error
# 解决方案：移除所有 emoji，使用纯文本
#
# 如需重新测试，取消注释以下任一版本：
# class BacktesterManager(TestVersion1):  # 最小化框架
# class BacktesterManager(TestVersion2):  # + 表单控件
# class BacktesterManager(TestVersion3):  # + 选项卡
# class BacktesterManager(TestVersion4):  # + 图表布局
# class BacktesterManager(TestVersion5):  # + 深色样式
# class BacktesterManager(TestVersion6):  # + emoji（会闪退）
#
# 或使用原始UI：
# class BacktesterManager(OriginalBacktesterManager):
#     pass