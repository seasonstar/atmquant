#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
展示新增期货品种信息
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.futures_config import get_futures_info, get_priority_contracts


def show_new_symbols():
    """展示新增品种信息"""
    new_symbols = ['PL', 'ad', 'PR']
    
    print("新增期货品种信息")
    print("=" * 60)
    
    for symbol in new_symbols:
        info = get_futures_info(symbol)
        contracts = get_priority_contracts(symbol)
        
        print(f"\n品种代码: {symbol}")
        print(f"品种名称: {info['name']}")
        print(f"交易所: {info['exchange'].value}")
        print(f"合约乘数: {info['size']} 吨/手")
        print(f"最小变动价位: {info['pricetick']} 元")
        print(f"保证金比例: {info['deposit_rate'] * 100:.1f}%")
        print(f"手续费率: {info['rate'] * 10000:.1f}‰")
        print(f"滑点: {info['slippage']}")
        print(f"交易月份: {info['months']}")
        print(f"优先合约数量: {len(contracts)} 个")
        print(f"优先合约: {', '.join(contracts[:3])}...")
    
    print(f"\n总计新增: {len(new_symbols)} 个品种")
    print("系统现在支持: 85 个期货品种")


if __name__ == "__main__":
    show_new_symbols()