#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3MA策略测试脚本
验证策略加载和基本功能
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

def test_strategy_loading():
    """测试策略加载"""
    print("🔍 测试策略加载...")
    
    try:
        # 测试导入基础策略类
        from core.strategies.base_strategy import BaseCtaStrategy
        print("✅ 基础策略类导入成功")
        
        # 测试导入3MA策略
        from core.strategies.triple_ma_strategy import TripleMaStrategy
        print("✅ 3MA策略类导入成功")
        
        # 检查策略参数
        print(f"📊 3MA策略参数: {TripleMaStrategy.parameters}")
        print(f"📊 3MA策略变量: {TripleMaStrategy.variables}")
        
        return True
        
    except Exception as e:
        print(f"❌ 策略加载失败: {e}")
        return False

def test_vnpy_integration():
    """测试vnpy集成"""
    print("\n🔗 测试vnpy集成...")
    
    try:
        # 测试vnpy_ctastrategy引擎
        from vnpy_ctastrategy import CtaEngine
        print("✅ vnpy_ctastrategy引擎导入成功")
        
        # 测试vnpy_ctabacktester引擎
        from vnpy_ctabacktester import BacktesterEngine
        print("✅ vnpy_ctabacktester引擎导入成功")
        
        return True
        
    except Exception as e:
        print(f"❌ vnpy集成测试失败: {e}")
        return False

def test_strategy_parameters():
    """测试策略参数"""
    print("\n⚙️ 测试策略参数...")
    
    try:
        from core.strategies.triple_ma_strategy import TripleMaStrategy
        
        # 创建策略实例（模拟）
        class MockEngine:
            pass
        
        strategy = TripleMaStrategy(MockEngine(), "test_strategy", "rb2501.SHFE", {})
        
        # 检查默认参数
        assert strategy.short_window == 7
        assert strategy.mid_window == 55
        assert strategy.long_window == 100
        assert strategy.ma_type == "SMA"
        assert strategy.signal_timeframe == 5
        assert strategy.trade_timeframe == 5
        assert strategy.stop_loss_pct == 2.0
        assert strategy.take_profit_pct == 4.0
        assert strategy.trailing_stop_pct == 0.5
        
        print("✅ 策略参数验证通过")
        return True
        
    except Exception as e:
        print(f"❌ 策略参数测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("🚀 开始3MA策略测试")
    print("=" * 50)
    
    # 运行所有测试
    tests = [
        test_strategy_loading,
        test_vnpy_integration,
        test_strategy_parameters,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 50)
    print(f"📊 测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！3MA策略可以正常使用")
    else:
        print("⚠️ 部分测试失败，请检查配置")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
