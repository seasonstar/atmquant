#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATMTrader基础策略类
基于vnpy CtaTemplate扩展，添加日志和告警功能
"""

from datetime import time
from typing import List, Tuple, Optional
import re

from vnpy_ctastrategy import CtaTemplate
from vnpy.trader.utility import BarGenerator
from vnpy.trader.constant import Interval
from core.logging.logger_manager import get_logger
from core.logging.alert_manager import alert_manager
from config.trading_sessions_config import (
    get_trading_session_by_symbol,
    TradingSession,
    MarketType
)


class BaseCtaStrategy(CtaTemplate):
    """
    ATMTrader基础策略类
    
    特性：
    1. 自动识别品种的交易时段
    2. 支持日志和告警功能
    3. 小时K线按照实际交易时段合成（如果配置了trading_session）
    """
    
    # 交易时段定义（子类可以重写这些属性）
    # 如果不重写，将自动根据品种代码识别市场类型并使用对应的交易时段
    trading_session: Optional[TradingSession] = None
    
    # 每日收盘时间（用于日线聚合，如果未设置则使用trading_session中的值）
    daily_end: Optional[time] = None
    
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """
        初始化策略

        参数优先级：
        1. 界面参数（setting字典）优先级最高
        2. 配置文件中的最优参数次之
        3. 默认参数优先级最低
        """
        # 初始化日志系统（提前初始化，用于记录参数加载）
        self.logger = get_logger(symbol=vt_symbol.split('.')[0])

        # 策略状态
        self.strategy_status = "未启动"

        # 在调用父类 __init__ 之前，先填充最优参数到 setting
        self._fill_optimized_params(setting, vt_symbol)

        # 调用父类初始化（会把 setting 应用到策略属性）
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        # 自动识别并设置交易时段
        if self.trading_session is None:
            # 解析品种代码和交易所
            symbol = self.vt_symbol.split('.')[0]
            exchange = self.vt_symbol.split('.')[1] if '.' in self.vt_symbol else ""

            # 自动获取交易时段
            self.trading_session = get_trading_session_by_symbol(symbol, exchange)
            self.logger.info(f"自动识别交易时段: {self.trading_session.name}")

        # 设置每日收盘时间
        if self.daily_end is None:
            self.daily_end = self.trading_session.daily_end

    def _fill_optimized_params(self, setting: dict, vt_symbol: str):
        """
        将最优参数填充到 setting 字典中

        Args:
            setting: 界面传入的参数字典（会被修改）
            vt_symbol: 品种代码
        """
        # 延迟导入避免循环依赖
        from core.utils.strategy_param_manager import get_param_manager

        param_manager = get_param_manager()

        # 获取策略名称（转换为配置文件格式）
        strategy_name = self._get_strategy_config_name()

        # 获取该品种的最优参数
        optimized_params = param_manager.get_params(
            strategy_name=strategy_name,
            symbol=vt_symbol
        )

        if not optimized_params:
            self.logger.debug(f"未找到优化参数，使用默认参数: {vt_symbol}")
            return

        # 将最优参数填充到 setting 中（不覆盖已存在的界面参数）
        filled_count = 0
        for key, value in optimized_params.items():
            # 如果界面已经有这个参数，跳过（界面参数优先）
            if key in setting:
                continue

            # 添加到 setting
            setting[key] = value
            filled_count += 1

        if filled_count > 0:
            self.logger.info(
                f"✓ 填充优化参数到界面: {vt_symbol} -> "
                f"{filled_count} 个参数"
            )

    def _get_strategy_config_name(self) -> str:
        """
        获取策略配置名称

        将策略类名转换为配置文件格式：
        - KalmanMeanReversionStrategy -> kalman_mean_reversion
        - BollRSIStrategy -> boll_rsi
        """
        class_name = self.__class__.__name__

        # 移除 "Strategy" 后缀
        if class_name.endswith("Strategy"):
            class_name = class_name[:-8]

        # 驼峰转下划线
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
        config_name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

        return config_name
        
    def on_init(self):
        """策略初始化"""
        self.strategy_status = "初始化中"
        self.logger.info(f"策略 {self.strategy_name} 开始初始化")
        super().on_init()
        
    def on_start(self):
        """策略启动"""
        self.strategy_status = "运行中"
        self.logger.success(f"策略 {self.strategy_name} 启动成功")
        super().on_start()
        
    def on_stop(self):
        """策略停止"""
        self.strategy_status = "已停止"
        self.logger.info(f"策略 {self.strategy_name} 已停止")
        super().on_stop()
        
    def on_trade(self, trade):
        """成交回报"""
        self.logger.success(
            f"成交回报: {trade.direction} {trade.volume}@{trade.price} "
            f"成交金额: {trade.price * trade.volume}"
        )
        super().on_trade(trade)
        
    def on_order(self, order):
        """委托回报"""
        if order.status == "全部成交":
            self.logger.info(f"委托全部成交: {order.direction} {order.volume}@{order.price}")
        elif order.status == "部分成交":
            self.logger.info(f"委托部分成交: {order.direction} {order.volume}@{order.price}")
        elif order.status == "已撤销":
            self.logger.warning(f"委托已撤销: {order.direction} {order.volume}@{order.price}")
        super().on_order(order)
        
    def _is_backtest(self) -> bool:
        """判断策略是否运行在回测引擎中"""
        from vnpy_ctastrategy.base import EngineType

        engine_type = getattr(self.cta_engine, "engine_type", None)
        return engine_type is not None and engine_type == EngineType.BACKTESTING

    def send_alert(self, message: str):
        """发送告警消息（回测模式下仅记录日志）"""
        try:
            from config.alert_config import ALERT_BACKTEST_ENABLED

            if self._is_backtest() and not ALERT_BACKTEST_ENABLED:
                self.logger.debug(f"[回测告警·仅记录] {message}")
                return

            alert_manager.send_alert(
                content=f"📊 策略告警\n策略：{self.strategy_name}\n品种：{self.vt_symbol}\n消息：{message}",
                symbol=self.vt_symbol,

            )
        except Exception as e:
            self.logger.error(f"发送告警失败: {e}")
