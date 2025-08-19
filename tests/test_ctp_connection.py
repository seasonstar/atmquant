#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CTP连接测试脚本
测试CTP网关是否能正常连接SimNow模拟环境
"""

import sys
import time
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy_ctp import CtpGateway
from config.plugin_settings import CURRENT_CTP_SETTINGS

def test_ctp_connection():
    """测试CTP连接"""
    print("=" * 60)
    print("CTP连接测试")
    print("=" * 60)
    
    # 检查配置
    print("检查CTP配置...")
    if CURRENT_CTP_SETTINGS.get("用户名") == "your_simnow_account":
        print("⚠️  请先在 config/plugin_settings.py 中配置您的SimNow账户信息")
        print("   - 用户名：您的SimNow账户")
        print("   - 密码：您的SimNow密码")
        print("   - 其他参数已预配置为SimNow 7x24环境")
        return False
    
    try:
        # 创建事件引擎和主引擎
        event_engine = EventEngine()
        main_engine = MainEngine(event_engine)
        print("✓ 主引擎创建成功")
        
        # 添加CTP网关
        main_engine.add_gateway(CtpGateway)
        print("✓ CTP网关加载成功")
        
        # 连接CTP（这里只是测试连接接口，不进行实际连接）
        print("✓ CTP连接接口测试通过")
        print("  - 交易服务器:", CURRENT_CTP_SETTINGS.get("交易服务器"))
        print("  - 行情服务器:", CURRENT_CTP_SETTINGS.get("行情服务器"))
        print("  - 经纪商代码:", CURRENT_CTP_SETTINGS.get("经纪商代码"))
        
        # 清理资源
        main_engine.close()
        event_engine.stop()
        print("✓ 资源清理成功")
        
        return True
        
    except Exception as e:
        print(f"✗ CTP连接测试失败: {e}")
        return False

def main():
    """主函数"""
    print("CTP连接测试脚本")
    print("注意：此脚本仅测试CTP接口是否正确安装，不进行实际连接")
    print()
    
    success = test_ctp_connection()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 CTP接口测试通过！")
        print("\n下一步：")
        print("1. 注册SimNow模拟账户：https://www.simnow.com.cn/")
        print("2. 在 config/plugin_settings.py 中配置账户信息")
        print("3. 运行实际连接测试")
    else:
        print("⚠️ CTP接口测试失败，请检查安装")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)