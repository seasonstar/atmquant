#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新合约列表脚本
根据当前主力合约和未来合约数据更新配置
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 当前主力合约
current_main_contracts = [
    'nr2510.INE', 'sc2510.INE', 'jd2510.DCE', 'ss2510.SHFE', 'sp2511.SHFE', 
    'c2511.DCE', 'a2511.DCE', 'l2601.DCE', 'TA601.CZCE', 'i2601.DCE', 
    'm2601.DCE', 'pp2601.DCE', 'CF601.CZCE', 'RM601.CZCE', 'PK511.CZCE', 
    'ao2601.SHFE', 'FG601.CZCE', 'PX511.CZCE', 'UR601.CZCE', 'p2601.DCE', 
    'MA601.CZCE', 'OI601.CZCE', 'SF511.CZCE', 'j2601.DCE', 'ps2511.GFEX', 
    'PF510.CZCE', 'si2511.GFEX', 'lc2511.GFEX', 'bu2510.SHFE', 'lh2511.DCE', 
    'ru2601.SHFE', 'SA601.CZCE', 'al2509.SHFE', 'zn2509.SHFE', 'eb2509.DCE', 
    'pb2509.SHFE', 'pg2509.DCE', 'br2509.SHFE', 'cu2509.SHFE', 'lu2510.INE', 
    'sn2509.SHFE', 'bc2509.INE', 'ni2509.SHFE', 'ec2510.INE', 'ag2510.SHFE', 
    'jm2601.DCE', 'CJ601.CZCE', 'cs2509.DCE', 'fu2509.SHFE', 'au2510.SHFE', 
    'lg2509.DCE', 'IC2509.CFFEX', 'IF2509.CFFEX', 'IH2509.CFFEX', 'IM2509.CFFEX', 
    'AP510.CZCE', 'SR601.CZCE', 'hc2510.SHFE', 'rb2510.SHFE', 'y2601.DCE', 
    'v2509.DCE', 'SM509.CZCE', 'b2509.DCE', 'eg2509.DCE', 'SH509.CZCE', 
    'bz2603.DCE', 'T2509.CFFEX', 'TF2509.CFFEX', 'TL2509.CFFEX', 'TS2509.CFFEX'
]

# 未来主力合约
future_main_contracts = [
    # 有色金属
    "ni2601.SHFE", "ni2602.SHFE", "sn2601.SHFE", "sn2602.SHFE",
    "cu2601.SHFE", "cu2602.SHFE", "zn2601.SHFE", "zn2602.SHFE",
    "al2601.SHFE", "al2602.SHFE", "pb2601.SHFE", "pb2602.SHFE",
    "ao2601.SHFE", "ao2605.SHFE", "ss2601.SHFE", "ss2602.SHFE",
    "ag2512.SHFE", "ag2602.SHFE", "nr2511.INE", "nr2601.INE", "nr2602.INE",
    
    # 化工
    "SA605.CZCE", "FG605.CZCE", "UR605.CZCE", "TA605.CZCE", "MA605.CZCE",
    "SH601.CZCE", "SH605.CZCE", "PX605.CZCE", "ru2605.SHFE", "ru2606.SHFE",
    "l2605.DCE", "v2601.DCE", "v2605.DCE", "eg2601.DCE", "eg2605.DCE",
    "pp2601.DCE", "pp2605.DCE", "sp2601.SHFE", "sp2605.SHFE",
    "pg2511.DCE", "pg2601.DCE", "pg2605.DCE", "eb2511.DCE", "eb2601.DCE", "eb2605.DCE",
    "bz2604.DCE", "bz2605.DCE",
    
    # 黑色系
    "rb2601.SHFE", "rb2605.SHFE", "hc2601.SHFE", "hc2605.SHFE",
    "i2601.DCE", "i2605.DCE", "bu2511.SHFE", "bu2601.SHFE", "bu2605.SHFE",
    "lc2601.GFEX", "lc2603.GFEX", "lc2605.GFEX", "si2601.GFEX", "si2603.GFEX", "si2605.GFEX",
    "ps2601.GFEX", "ps2603.GFEX", "ps2605.GFEX", "SM601.CZCE", "SM605.CZCE",
    "SF511.CZCE", "SF601.CZCE", "SF605.CZCE",
    
    # 能源
    "j2601.DCE", "j2605.DCE", "jm2605.DCE", "fu2511.SHFE", "fu2601.SHFE", "fu2605.SHFE",
    
    # 油脂油料
    "m2601.DCE", "m2605.DCE", "RM601.CZCE", "RM605.CZCE", "OI601.CZCE", "OI605.CZCE",
    "y2605.DCE", "p2601.DCE", "p2605.DCE", "a2511.DCE", "a2601.DCE", "a2605.DCE",
    "b2601.DCE", "b2605.DCE", "c2511.DCE", "c2601.DCE", "c2605.DCE",
    
    # 农副软商
    "CF601.CZCE", "CF605.CZCE", "CJ601.CZCE", "CJ605.CZCE", "SR601.CZCE", "SR605.CZCE",
    "AP601.CZCE", "AP605.CZCE", "jd2601.DCE", "jd2605.DCE",
    
    # 股指期货
    "IC2512.CFFEX", "IF2512.CFFEX", "IH2512.CFFEX", "IM2512.CFFEX",
    "T2512.CFFEX", "TF2512.CFFEX", "TL2512.CFFEX", "TS2512.CFFEX",
]


def parse_contract_symbol(contract: str) -> tuple:
    """
    解析合约代码
    
    Args:
        contract: 合约代码，如 'rb2510.SHFE'
    
    Returns:
        (symbol, month, exchange)
    """
    if '.' not in contract:
        return None, None, None
    
    symbol_month, exchange = contract.split('.')
    
    # 找到数字开始的位置
    last_idx = -1
    while last_idx >= -len(symbol_month) and symbol_month[last_idx].isdigit():
        last_idx -= 1
    
    if last_idx == -1:
        return symbol_month, None, exchange
    
    symbol = symbol_month[:last_idx + 1]
    month = symbol_month[last_idx + 1:]
    
    return symbol, month, exchange


def get_symbol_contracts(contracts: List[str]) -> Dict[str, List[str]]:
    """
    按品种分组合约
    
    Args:
        contracts: 合约列表
    
    Returns:
        按品种分组的合约字典
    """
    symbol_contracts = {}
    
    for contract in contracts:
        symbol, month, exchange = parse_contract_symbol(contract)
        if symbol and month and exchange:
            # 统一品种代码格式
            symbol_key = symbol.lower()
            
            if symbol_key not in symbol_contracts:
                symbol_contracts[symbol_key] = []
            
            symbol_contracts[symbol_key].append(contract)
    
    return symbol_contracts


def generate_priority_download_list() -> Dict[str, List[str]]:
    """
    生成优先下载列表
    
    Returns:
        包含当前主力和未来合约的下载列表
    """
    # 解析当前主力合约
    current_contracts = get_symbol_contracts(current_main_contracts)
    
    # 解析未来合约
    future_contracts = get_symbol_contracts(future_main_contracts)
    
    # 合并列表
    all_contracts = {}
    
    # 添加当前主力合约
    for symbol, contracts in current_contracts.items():
        if symbol not in all_contracts:
            all_contracts[symbol] = []
        all_contracts[symbol].extend(contracts)
    
    # 添加未来合约
    for symbol, contracts in future_contracts.items():
        if symbol not in all_contracts:
            all_contracts[symbol] = []
        all_contracts[symbol].extend(contracts)
    
    # 去重并排序
    for symbol in all_contracts:
        all_contracts[symbol] = sorted(list(set(all_contracts[symbol])))
    
    return all_contracts


def save_contract_config(contracts: Dict[str, List[str]], filename: str = "config/priority_contracts.json"):
    """
    保存合约配置到文件
    
    Args:
        contracts: 合约配置字典
        filename: 保存文件名
    """
    config_path = Path(filename)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 添加元数据
    config_data = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": "优先下载合约配置，包含当前主力合约和未来合约",
        "total_symbols": len(contracts),
        "total_contracts": sum(len(contract_list) for contract_list in contracts.values()),
        "contracts": contracts
    }
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        print(f"✓ 合约配置已保存: {config_path}")
        return True
    except Exception as e:
        print(f"✗ 合约配置保存失败: {e}")
        return False


def show_contract_summary(contracts: Dict[str, List[str]]):
    """
    显示合约汇总信息
    
    Args:
        contracts: 合约配置字典
    """
    print("合约配置汇总:")
    print("=" * 60)
    
    total_contracts = 0
    
    # 按交易所分组统计
    exchange_stats = {}
    
    for symbol, contract_list in contracts.items():
        print(f"{symbol:6} ({len(contract_list):2}个): {', '.join(contract_list[:3])}{'...' if len(contract_list) > 3 else ''}")
        total_contracts += len(contract_list)
        
        # 统计交易所
        for contract in contract_list:
            _, _, exchange = parse_contract_symbol(contract)
            if exchange:
                if exchange not in exchange_stats:
                    exchange_stats[exchange] = 0
                exchange_stats[exchange] += 1
    
    print("\n" + "=" * 60)
    print(f"总计: {len(contracts)} 个品种, {total_contracts} 个合约")
    
    print("\n交易所分布:")
    for exchange, count in sorted(exchange_stats.items()):
        print(f"  {exchange}: {count} 个合约")


def main():
    """主函数"""
    print("更新合约列表配置")
    print("=" * 60)
    
    # 生成优先下载列表
    priority_contracts = generate_priority_download_list()
    
    # 显示汇总信息
    show_contract_summary(priority_contracts)
    
    # 保存配置
    if save_contract_config(priority_contracts):
        print("\n✓ 合约配置更新完成")
    else:
        print("\n✗ 合约配置更新失败")
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)