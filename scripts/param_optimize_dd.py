#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三均线回撤控制策略 — 参数优化回测
"""

import sys
import json
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vnpy_ctastrategy.backtesting import BacktestingEngine
from core.strategies.triple_ma_dd_control import TripleMaDdControl


def run_single_backtest(setting, label):
    """运行单组参数回测"""
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="rb2510.SHFE",
        interval="1m",
        start=datetime(2024, 10, 15),
        end=datetime(2025, 10, 15),
        rate=0.0003,
        slippage=1,
        size=10,
        pricetick=1,
        capital=200_000,
    )
    engine.add_strategy(TripleMaDdControl, setting)
    engine.load_data()
    engine.run_backtesting()
    df = engine.calculate_result()
    stats = engine.calculate_statistics()
    
    # 提取关键指标
    result = {
        "label": label,
        "setting": setting,
        "total_net_pnl": stats.get("total_net_pnl", 0),
        "total_return": stats.get("total_return", 0),
        "max_ddpercent": stats.get("max_ddpercent", 0),
        "sharpe_ratio": stats.get("sharpe_ratio", 0),
        "win_rate": stats.get("win_rate", 0),
        "profit_factor": stats.get("profit_factor", 0),
        "total_trade_count": stats.get("total_trade_count", 0),
        "total_commission": stats.get("total_commission", 0),
        "end_balance": stats.get("end_balance", 0),
    }
    return result


# 参数组合
param_sets = [
    # 1. 基线 (原参数)
    {
        "label": "baseline_10_30_60_sl2_tp6",
        "setting": {
            "short_window": 10, "mid_window": 30, "long_window": 60,
            "stop_loss_pct": 2.0, "take_profit_pct": 6.0, "trailing_stop_pct": 1.5,
        }
    },
    # 2. 更长均线，减少噪音
    {
        "label": "longer_20_60_120_sl3_tp9",
        "setting": {
            "short_window": 20, "mid_window": 60, "long_window": 120,
            "stop_loss_pct": 3.0, "take_profit_pct": 9.0, "trailing_stop_pct": 2.0,
        }
    },
    # 3. 中等均线，宽止损
    {
        "label": "mid_15_40_80_sl3_tp9",
        "setting": {
            "short_window": 15, "mid_window": 40, "long_window": 80,
            "stop_loss_pct": 3.0, "take_profit_pct": 9.0, "trailing_stop_pct": 2.0,
        }
    },
    # 4. 短均线 + 宽止损大止盈
    {
        "label": "short_5_20_40_sl4_tp12",
        "setting": {
            "short_window": 5, "mid_window": 20, "long_window": 40,
            "stop_loss_pct": 4.0, "take_profit_pct": 12.0, "trailing_stop_pct": 2.5,
        }
    },
    # 5. 长均线 + 紧止损（趋势跟踪经典）
    {
        "label": "trend_20_50_100_sl2_tp8",
        "setting": {
            "short_window": 20, "mid_window": 50, "long_window": 100,
            "stop_loss_pct": 2.0, "take_profit_pct": 8.0, "trailing_stop_pct": 1.5,
        }
    },
    # 6. 超长均线（过滤噪音）
    {
        "label": "vlong_30_80_150_sl3_tp10",
        "setting": {
            "short_window": 30, "mid_window": 80, "long_window": 150,
            "stop_loss_pct": 3.0, "take_profit_pct": 10.0, "trailing_stop_pct": 2.0,
        }
    },
]

print("=" * 80)
print("参数优化对比测试")
print("=" * 80)

results = []
for ps in param_sets:
    print(f"\n>>> 运行: {ps['label']}")
    r = run_single_backtest(ps["setting"], ps["label"])
    results.append(r)
    print(f"    净亏: {r['total_net_pnl']:.0f}  回撤: {r['max_ddpercent']:.2f}%  夏普: {r['sharpe_ratio']:.2f}  胜率: {r['win_rate']:.1%}  交易: {r['total_trade_count']}")

print("\n" + "=" * 80)
print("汇总对比")
print("=" * 80)
print(f"{'Label':<35} {'净盈亏':>10} {'收益%':>8} {'回撤%':>8} {'夏普':>7} {'胜率':>6} {'因子':>6} {'笔数':>5}")
print("-" * 80)
for r in results:
    print(f"{r['label']:<35} {r['total_net_pnl']:>10.0f} {r['total_return']:>8.2f} {r['max_ddpercent']:>8.2f} {r['sharpe_ratio']:>7.2f} {r['win_rate']:>6.1%} {r['profit_factor']:>6.2f} {r['total_trade_count']:>5.0f}")

print("=" * 80)
