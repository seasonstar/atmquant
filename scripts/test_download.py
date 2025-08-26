#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货数据下载测试脚本
用于测试和演示数据下载功能
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import apply_settings
from config.futures_config import get_active_contracts, get_priority_contracts, get_futures_info
from core.data.downloader import FuturesDataDownloader


def test_futures_config():
    """测试期货配置"""
    print("=" * 60)
    print("测试期货品种配置")
    print("=" * 60)
    
    # 测试螺纹钢配置
    symbol = "rb"
    info = get_futures_info(symbol)
    
    print(f"品种代码: {symbol}")
    print(f"品种名称: {info.get('name', '未知')}")
    print(f"交易所: {info.get('exchange', '未知')}")
    print(f"合约乘数: {info.get('size', 0)} 吨/手")
    print(f"最小变动价位: {info.get('pricetick', 0)} 元")
    print(f"保证金比例: {info.get('deposit_rate', 0) * 100}%")
    print(f"交易月份: {info.get('months', [])}")
    
    # 测试合约生成
    print(f"\n生成合约列表:")
    contracts = get_active_contracts(symbol)
    print(f"月份合约: {contracts['month_contracts'][:5]}...")  # 只显示前5个
    print(f"主连合约: {contracts['continuous_contract']}")
    print(f"加权合约: {contracts['weighted_contract']}")
    
    # 测试优先合约
    priority = get_priority_contracts(symbol)
    print(f"\n优先下载合约:")
    for contract in priority:
        print(f"  {contract}")


def test_single_download():
    """测试单个合约下载"""
    print("\n" + "=" * 60)
    print("测试单个合约数据下载")
    print("=" * 60)
    
    # 应用配置
    apply_settings()
    
    # 创建下载器
    downloader = FuturesDataDownloader()
    
    # 初始化
    if not downloader.init_database():
        print("✗ 数据库初始化失败")
        return False
    
    if not downloader.init_tqsdk():
        print("✗ 天勤SDK初始化失败")
        return False
    
    try:
        # 测试下载螺纹钢主连合约
        symbol = "rb9999.SHFE"
        print(f"测试下载: {symbol}")
        
        # 设置下载最近7天的数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        success = downloader.download_contract_data(
            symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        if success:
            print(f"✓ {symbol} 下载成功")
        else:
            print(f"✗ {symbol} 下载失败")
        
        return success
        
    finally:
        downloader.close()


def test_symbol_download():
    """测试品种批量下载"""
    print("\n" + "=" * 60)
    print("测试品种批量下载")
    print("=" * 60)
    
    # 应用配置
    apply_settings()
    
    # 创建下载器
    downloader = FuturesDataDownloader()
    
    # 初始化
    if not downloader.init_database():
        print("✗ 数据库初始化失败")
        return False
    
    if not downloader.init_tqsdk():
        print("✗ 天勤SDK初始化失败")
        return False
    
    try:
        # 测试下载螺纹钢所有优先合约
        symbol = "rb"
        print(f"测试下载品种: {symbol}")
        
        # 设置下载最近3天的数据（测试用）
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)
        
        results = downloader.download_symbol_data(
            symbol,
            priority_only=True,
            start_date=start_date,
            end_date=end_date
        )
        
        # 统计结果
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        
        print(f"\n下载结果: {success_count}/{total_count} 成功")
        for contract, success in results.items():
            status = "✓" if success else "✗"
            print(f"  {status} {contract}")
        
        return success_count > 0
        
    finally:
        downloader.close()


def test_data_query():
    """测试数据查询"""
    print("\n" + "=" * 60)
    print("测试数据查询")
    print("=" * 60)
    
    try:
        from vnpy.trader.database import get_database
        from vnpy.trader.constant import Exchange, Interval
        from datetime import datetime, timedelta
        
        database = get_database()
        
        # 查询螺纹钢主连合约的数据
        symbol = "rb9999"
        exchange = Exchange.SHFE
        interval = Interval.MINUTE
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        
        bars = database.load_bar_data(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start=start_date,
            end=end_date
        )
        
        if bars:
            print(f"✓ 查询到 {len(bars)} 条数据")
            print(f"最新数据时间: {bars[-1].datetime}")
            print(f"最新价格: {bars[-1].close_price}")
            return True
        else:
            print("⚠️  未查询到数据")
            return False
            
    except Exception as e:
        print(f"✗ 数据查询失败: {e}")
        return False


def main():
    """主测试函数"""
    print("期货数据下载系统测试")
    print("=" * 60)
    
    # 测试1: 配置测试
    test_futures_config()
    
    # 测试2: 单个合约下载
    success1 = test_single_download()
    
    if success1:
        # 测试3: 品种批量下载
        success2 = test_symbol_download()
        
        if success2:
            # 测试4: 数据查询
            test_data_query()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()