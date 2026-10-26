#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3MA策略回测脚本
"""

import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from vnpy_ctastrategy.backtesting import BacktestingEngine
from core.strategies.triple_ma_strategy import TripleMaStrategy


def run_backtest():
    """运行3MA策略回测"""
    # 创建回测引擎
    engine = BacktestingEngine()
    
    # 设置回测参数
    engine.set_parameters(
        vt_symbol="rb2501.SHFE",  # 螺纹钢主力合约
        interval="1m",             # 1分钟K线
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        rate=0.0003,              # 手续费率
        slippage=0.2,             # 滑点
        size=10,                  # 合约乘数
        pricetick=1,              # 最小价格变动
        capital=1_000_000,        # 初始资金
    )
    
    # 添加策略
    engine.add_strategy(TripleMaStrategy, {
        "short_window": 5,
        "mid_window": 20,
        "long_window": 60,
        "ma_type": "SMA",
        "signal_timeframe": 15,
        "trade_timeframe": 5,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "trailing_stop_pct": 1.0,
    })
    
    # 加载数据
    engine.load_data()
    
    # 运行回测
    engine.run_backtesting()
    
    # 计算结果
    df = engine.calculate_result()
    engine.calculate_statistics()
    
    # 显示结果
    engine.show_chart()
    
    return df


if __name__ == "__main__":
    print("🚀 开始3MA策略回测...")
    df = run_backtest()
    print("✅ 回测完成！")
