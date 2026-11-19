#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图表管理器模块
"""

from .trading_manager import TradingManager
from .position_manager import PositionManager
from .risk_monitor import RiskMonitor

__all__ = ["TradingManager", "PositionManager", "RiskMonitor"]

# AI 分析协调器为会员专项模块，缺失时静默降级
try:
    from .ai_analysis_coordinator import AIAnalysisCoordinator
    __all__.append("AIAnalysisCoordinator")
except ImportError:
    pass
