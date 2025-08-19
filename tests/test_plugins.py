#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vnpy插件综合验证脚本
验证所有核心插件是否正确安装
"""

import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_all_plugins():
    """测试所有vnpy插件"""
    print("=" * 60)
    print("vnpy插件综合验证")
    print(f"测试时间: {datetime.now()}")
    print("=" * 60)
    
    plugins = [
        ("vnpy_ctp", "CTP交易接口"),
        ("vnpy_ctastrategy", "CTA策略引擎"),
        ("vnpy_datamanager", "历史数据管理"),
        ("vnpy_ctabacktester", "回测引擎"),
        ("vnpy_mysql", "MySQL数据库支持")
    ]
    
    success_count = 0
    
    for plugin_name, description in plugins:
        print(f"\n测试 {plugin_name} - {description}")
        print("-" * 40)
        
        try:
            # 动态导入插件
            plugin_module = __import__(plugin_name)
            print(f"✓ {plugin_name} 导入成功")
            
            # 检查插件版本
            if hasattr(plugin_module, '__version__'):
                print(f"✓ 版本: {plugin_module.__version__}")
            
            # 特定插件的额外检查
            if plugin_name == "vnpy_ctp":
                from vnpy_ctp import CtpGateway
                print("✓ CTP网关类导入成功")
                
            elif plugin_name == "vnpy_ctastrategy":
                from vnpy_ctastrategy import CtaStrategyApp
                from vnpy_ctastrategy.template import CtaTemplate
                print("✓ 策略模板和应用类导入成功")
                
            elif plugin_name == "vnpy_datamanager":
                from vnpy_datamanager import DataManagerApp
                print("✓ 数据管理应用类导入成功")
                
            elif plugin_name == "vnpy_ctabacktester":
                from vnpy_ctabacktester import CtaBacktesterApp
                print("✓ 回测应用类导入成功")
                
            elif plugin_name == "vnpy_mysql":
                from vnpy_mysql import Database
                print("✓ MySQL数据库类导入成功")
            
            success_count += 1
            print(f"✓ {plugin_name} 验证通过")
            
        except ImportError as e:
            print(f"✗ {plugin_name} 导入失败: {e}")
        except Exception as e:
            print(f"✗ {plugin_name} 验证失败: {e}")
    
    print("\n" + "=" * 60)
    print(f"验证结果: {success_count}/{len(plugins)} 个插件验证通过")
    
    if success_count == len(plugins):
        print("🎉 所有核心插件安装成功！")
        return True
    else:
        print("⚠️ 部分插件安装失败，请检查安装过程")
        return False

def test_vnpy_integration():
    """测试vnpy主框架集成"""
    print("\n" + "=" * 60)
    print("vnpy主框架集成测试")
    print("=" * 60)
    
    try:
        from vnpy.event import EventEngine
        from vnpy.trader.engine import MainEngine
        print("✓ vnpy核心模块导入成功")
        
        # 创建引擎
        event_engine = EventEngine()
        main_engine = MainEngine(event_engine)
        print("✓ 主引擎创建成功")
        
        # 测试插件加载
        from vnpy_ctastrategy import CtaStrategyApp
        main_engine.add_app(CtaStrategyApp)
        print("✓ CTA策略应用加载成功")
        
        from vnpy_datamanager import DataManagerApp
        main_engine.add_app(DataManagerApp)
        print("✓ 数据管理应用加载成功")
        
        from vnpy_ctabacktester import CtaBacktesterApp
        main_engine.add_app(CtaBacktesterApp)
        print("✓ 回测应用加载成功")
        
        # 清理资源
        main_engine.close()
        event_engine.stop()
        print("✓ 资源清理成功")
        
        return True
        
    except Exception as e:
        print(f"✗ vnpy集成测试失败: {e}")
        return False

def main():
    """主测试函数"""
    # 测试插件安装
    plugins_ok = test_all_plugins()
    
    # 测试vnpy集成
    integration_ok = test_vnpy_integration()
    
    print("\n" + "=" * 60)
    print("最终测试结果")
    print("=" * 60)
    
    if plugins_ok and integration_ok:
        print("🎉 所有测试通过！vnpy插件环境配置完成！")
        print("\n下一步可以开始：")
        print("1. 配置CTP连接参数")
        print("2. 设置MySQL数据库")
        print("3. 开发第一个策略")
        return True
    else:
        print("⚠️ 部分测试失败，请检查配置")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)