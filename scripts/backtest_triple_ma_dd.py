#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三均线回撤控制策略 — 本地回测脚本
品种: rb2510.SHFE (螺纹钢)
"""

import sys
import json
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vnpy_ctastrategy.backtesting import BacktestingEngine
from core.strategies.triple_ma_dd_control import TripleMaDdControl


def run_backtest():
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

    engine.add_strategy(TripleMaDdControl, {})

    engine.load_data()
    engine.run_backtesting()

    df = engine.calculate_result()
    stats = engine.calculate_statistics()

    # 输出关键指标
    print("\n" + "=" * 60)
    print("回测结果摘要")
    print("=" * 60)

    if isinstance(stats, dict):
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}")
            else:
                print(f"  {k}: {v}")
    else:
        print(stats)

    print("=" * 60)

    # 输出成交记录
    trades = engine.get_all_trades()
    print(f"\n总成交笔数: {len(trades)}")

    if trades:
        print("\n前20笔成交:")
        for t in trades[:20]:
            print(f"  {t.datetime} {t.direction} {t.offset} {t.volume}@{t.price}")

    # 输出每日资金曲线
    if df is not None and len(df) > 0:
        print(f"\n每日资金曲线记录数: {len(df)}")
        print(f"  起始日期: {df.index[0]}")
        print(f"  结束日期: {df.index[-1]}")
        print(f"  期末资金: {df['end_capital'].iloc[-1]:.2f}" if 'end_capital' in df.columns else "")

        # 计算最大回撤
        if 'end_capital' in df.columns:
            capital_series = df['end_capital']
            peak = capital_series.expanding().max()
            drawdown = (capital_series - peak) / peak * 100
            max_dd = drawdown.min()
            print(f"  最大回撤: {max_dd:.2f}%")

    return engine, df, stats


if __name__ == "__main__":
    print("开始三均线回撤控制策略回测...")
    engine, df, stats = run_backtest()
    print("回测完成!")
