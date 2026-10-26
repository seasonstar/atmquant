#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V2 策略参数优化"""

import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vnpy_ctastrategy.backtesting import BacktestingEngine
from core.strategies.triple_ma_dd_control_v2 import TripleMaDdControlV2


def run_single(setting, label):
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol="rb2510.SHFE",
        interval="1m",
        start=datetime(2024, 10, 15),
        end=datetime(2025, 10, 15),
        rate=0.0003, slippage=1, size=10, pricetick=1, capital=200_000,
    )
    engine.add_strategy(TripleMaDdControlV2, setting)
    engine.load_data()
    engine.run_backtesting()
    df = engine.calculate_result()
    stats = engine.calculate_statistics()
    return {
        "label": label,
        "total_net_pnl": stats.get("total_net_pnl", 0),
        "total_return": stats.get("total_return", 0),
        "max_ddpercent": stats.get("max_ddpercent", 0),
        "sharpe_ratio": stats.get("sharpe_ratio", 0),
        "win_rate": stats.get("win_rate", 0),
        "profit_factor": stats.get("profit_factor", 0),
        "total_trade_count": stats.get("total_trade_count", 0),
        "total_commission": stats.get("total_commission", 0),
    }


param_sets = [
    # 1. 最优V1参数 + 5分钟周期 + 量能 + ATR
    {
        "label": "v2_5_20_40_sl4_tp12_5min",
        "setting": {
            "short_window": 5, "mid_window": 20, "long_window": 40,
            "stop_loss_pct": 4.0, "take_profit_pct": 12.0, "trailing_stop_pct": 2.5,
            "bar_interval": 5,
        }
    },
    # 2. 中等均线 + 5分钟
    {
        "label": "v2_10_30_60_sl3_tp9_5min",
        "setting": {
            "short_window": 10, "mid_window": 30, "long_window": 60,
            "stop_loss_pct": 3.0, "take_profit_pct": 9.0, "trailing_stop_pct": 2.0,
            "bar_interval": 5,
        }
    },
    # 3. 中等均线 + 15分钟周期
    {
        "label": "v2_10_30_60_sl3_tp9_15min",
        "setting": {
            "short_window": 10, "mid_window": 30, "long_window": 60,
            "stop_loss_pct": 3.0, "take_profit_pct": 9.0, "trailing_stop_pct": 2.0,
            "bar_interval": 15,
        }
    },
    # 4. 短均线 + 15分钟
    {
        "label": "v2_5_20_40_sl4_tp12_15min",
        "setting": {
            "short_window": 5, "mid_window": 20, "long_window": 40,
            "stop_loss_pct": 4.0, "take_profit_pct": 12.0, "trailing_stop_pct": 2.5,
            "bar_interval": 15,
        }
    },
    # 5. 长均线 + 15分钟
    {
        "label": "v2_20_60_120_sl3_tp9_15min",
        "setting": {
            "short_window": 20, "mid_window": 60, "long_window": 120,
            "stop_loss_pct": 3.0, "take_profit_pct": 9.0, "trailing_stop_pct": 2.0,
            "bar_interval": 15,
        }
    },
    # 6. 短均线宽止损 + 5分钟
    {
        "label": "v2_5_15_30_sl5_tp15_5min",
        "setting": {
            "short_window": 5, "mid_window": 15, "long_window": 30,
            "stop_loss_pct": 5.0, "take_profit_pct": 15.0, "trailing_stop_pct": 3.0,
            "bar_interval": 5,
        }
    },
]

print("=" * 90)
print("V2 策略参数优化对比")
print("=" * 90)

results = []
for ps in param_sets:
    print(f"\n>>> 运行: {ps['label']}")
    r = run_single(ps["setting"], ps["label"])
    results.append(r)
    print(f"    净盈亏: {r['total_net_pnl']:.0f}  回撤: {r['max_ddpercent']:.2f}%  夏普: {r['sharpe_ratio']:.2f}  胜率: {r['win_rate']:.1%}  交易: {r['total_trade_count']}")

print("\n" + "=" * 90)
print("V2 汇总对比")
print("=" * 90)
print(f"{'Label':<40} {'净盈亏':>10} {'收益%':>8} {'回撤%':>8} {'夏普':>7} {'胜率':>6} {'因子':>6} {'笔数':>5}")
print("-" * 90)
for r in results:
    print(f"{r['label']:<40} {r['total_net_pnl']:>10.0f} {r['total_return']:>8.2f} {r['max_ddpercent']:>8.2f} {r['sharpe_ratio']:>7.2f} {r['win_rate']:>6.1%} {r['profit_factor']:>6.2f} {r['total_trade_count']:>5.0f}")
print("=" * 90)
