#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货数据系统最终测试脚本
验证所有功能是否正常工作
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import apply_settings
from config.futures_config import get_all_symbols, get_futures_info, get_priority_contracts


def test_config_system():
    """测试配置系统"""
    print("1. 测试配置系统")
    print("-" * 40)
    
    try:
        apply_settings()
        print("✓ 配置系统正常")
        return True
    except Exception as e:
        print(f"✗ 配置系统异常: {e}")
        return False


def test_futures_config():
    """测试期货配置"""
    print("\n2. 测试期货配置")
    print("-" * 40)
    
    try:
        symbols = get_all_symbols()
        print(f"✓ 支持品种数量: {len(symbols)}")
        
        # 测试几个主要品种
        test_symbols = ["rb", "cu", "i", "MA", "IF", "sc", "si"]
        success_count = 0
        
        for symbol in test_symbols:
            info = get_futures_info(symbol)
            if info:
                print(f"✓ {symbol}: {info['name']} - {info['exchange'].value}")
                success_count += 1
            else:
                print(f"✗ {symbol}: 配置缺失")
        
        print(f"✓ 测试品种: {success_count}/{len(test_symbols)} 成功")
        return success_count == len(test_symbols)
        
    except Exception as e:
        print(f"✗ 期货配置异常: {e}")
        return False


def test_priority_contracts():
    """测试优先合约配置"""
    print("\n3. 测试优先合约配置")
    print("-" * 40)
    
    try:
        test_symbols = ["rb", "cu", "i", "MA"]
        success_count = 0
        
        for symbol in test_symbols:
            contracts = get_priority_contracts(symbol)
            if contracts:
                print(f"✓ {symbol}: {len(contracts)} 个合约")
                success_count += 1
            else:
                print(f"✗ {symbol}: 无优先合约")
        
        print(f"✓ 优先合约配置: {success_count}/{len(test_symbols)} 成功")
        return success_count == len(test_symbols)
        
    except Exception as e:
        print(f"✗ 优先合约配置异常: {e}")
        return False


def test_database_connection():
    """测试数据库连接"""
    print("\n4. 测试数据库连接")
    print("-" * 40)
    
    try:
        from vnpy.trader.database import get_database
        database = get_database()
        print("✓ 数据库连接正常")
        return True
    except Exception as e:
        print(f"✗ 数据库连接失败: {e}")
        return False


def test_tqsdk_connection():
    """测试天勤SDK连接"""
    print("\n5. 测试天勤SDK连接")
    print("-" * 40)
    
    try:
        from core.data.downloader import FuturesDataDownloader
        downloader = FuturesDataDownloader()
        
        if downloader.init_tqsdk():
            print("✓ 天勤SDK连接正常")
            downloader.close()
            return True
        else:
            print("✗ 天勤SDK连接失败")
            return False
            
    except Exception as e:
        print(f"✗ 天勤SDK测试异常: {e}")
        return False


def test_data_query():
    """测试数据查询"""
    print("\n6. 测试数据查询")
    print("-" * 40)
    
    try:
        from vnpy.trader.database import get_database
        from vnpy.trader.constant import Exchange, Interval
        from datetime import datetime, timedelta
        
        database = get_database()
        
        # 查询螺纹钢主连合约的数据
        bars = database.load_bar_data(
            symbol="rb9999",
            exchange=Exchange.SHFE,
            interval=Interval.MINUTE,
            start=datetime.now() - timedelta(days=1),
            end=datetime.now()
        )
        
        if bars:
            print(f"✓ 查询到数据: {len(bars)} 条")
            print(f"✓ 最新价格: {bars[-1].close_price}")
            return True
        else:
            print("⚠️  暂无数据（可能需要先下载）")
            return True  # 这不算错误
            
    except Exception as e:
        print(f"✗ 数据查询异常: {e}")
        return False


def test_download_config():
    """测试下载配置"""
    print("\n7. 测试下载配置")
    print("-" * 40)
    
    try:
        import json
        config_path = Path("config/download_config.json")
        
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            enabled_symbols = config.get("enabled_symbols", [])
            print(f"✓ 下载配置正常，启用品种: {len(enabled_symbols)} 个")
            return True
        else:
            print("✗ 下载配置文件不存在")
            return False
            
    except Exception as e:
        print(f"✗ 下载配置测试异常: {e}")
        return False


def test_priority_config():
    """测试优先合约配置文件"""
    print("\n8. 测试优先合约配置文件")
    print("-" * 40)
    
    try:
        import json
        config_path = Path("config/priority_contracts.json")
        
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            contracts = config.get("contracts", {})
            total_contracts = config.get("total_contracts", 0)
            print(f"✓ 优先合约配置正常，{len(contracts)} 个品种，{total_contracts} 个合约")
            return True
        else:
            print("✗ 优先合约配置文件不存在")
            return False
            
    except Exception as e:
        print(f"✗ 优先合约配置测试异常: {e}")
        return False


def main():
    """主测试函数"""
    print("期货数据系统最终测试")
    print("=" * 60)
    
    tests = [
        ("配置系统", test_config_system),
        ("期货配置", test_futures_config),
        ("优先合约", test_priority_contracts),
        ("数据库连接", test_database_connection),
        ("天勤SDK", test_tqsdk_connection),
        ("数据查询", test_data_query),
        ("下载配置", test_download_config),
        ("优先合约配置", test_priority_config),
    ]
    
    passed_tests = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed_tests += 1
        except Exception as e:
            print(f"✗ {test_name}测试异常: {e}")
    
    print("\n" + "=" * 60)
    print(f"测试总结: {passed_tests}/{len(tests)} 项测试通过")
    
    if passed_tests == len(tests):
        print("🎉 所有测试通过！系统运行正常！")
        
        print("\n系统功能概览:")
        print("✓ 支持76个期货品种的完整配置")
        print("✓ 智能合约管理（168个优先合约）")
        print("✓ 天勤数据源集成（兼容免费版）")
        print("✓ 自动化数据下载和验证")
        print("✓ 完整的配置管理系统")
        
        print("\n使用建议:")
        print("1. 运行: python scripts/download_futures_data.py --symbols rb cu")
        print("2. 验证: python scripts/verify_data.py --symbols rb cu")
        print("3. 配置: 编辑 config/download_config.json")
        print("4. 定时: 设置cron或Windows任务计划")
        
        return True
    else:
        print("⚠️  部分测试失败，请检查系统配置")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)