#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATMQuant主程序入口
基于vnpy框架的AI量化交易系统
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """主函数"""
    print("=" * 60)
    print("ATMQuant - AI量化交易系统")
    import vnpy
    print(f"基于vnpy {vnpy.__version__}框架")
    print("=" * 60)
    
    # 加载ATMQuant配置
    try:
        from config.settings import apply_settings
        apply_settings()
    except Exception as e:
        print(f"⚠️  配置加载失败: {e}")
    
    try:
        # 导入vnpy核心模块
        from vnpy.event import EventEngine
        from vnpy.trader.engine import MainEngine
        from vnpy.trader.ui import MainWindow, create_qapp
        
        print("✓ vnpy核心模块导入成功")
        
        # 创建Qt应用
        qapp = create_qapp()
        
        # 创建事件引擎
        event_engine = EventEngine()
        print("✓ 事件引擎创建成功")
        
        # 创建主引擎
        main_engine = MainEngine(event_engine)
        print("✓ 主引擎创建成功")
        
        # 导入CTP网关
        from vnpy_ctp import CtpGateway
        main_engine.add_gateway(CtpGateway)
        print("✓ CTP交易网关加载成功")
        
        # 导入并添加插件应用
        from vnpy_ctastrategy import CtaStrategyApp
        from vnpy_datamanager import DataManagerApp
        from vnpy_ctabacktester import CtaBacktesterApp
        from vnpy_charttrader import ChartTraderApp

        main_engine.add_app(CtaStrategyApp)
        print("✓ CTA策略引擎加载成功")

        #main_engine.add_app(DataManagerApp)
        #print("✓ 数据管理模块加载成功")

        main_engine.add_app(CtaBacktesterApp)
        print("✓ 回测引擎加载成功")

        main_engine.add_app(ChartTraderApp)
        print("✓ 图表交易模块加载成功")
        
        # 创建主窗口
        main_window = MainWindow(main_engine, event_engine)
        main_window.showMaximized()
        
        print("✓ 图形界面启动成功")
        print("\n🎉 ATMQuant启动完成！")
        

        # 自动连接CTP网关
        try:
            import os
            from dotenv import load_dotenv
            from vnpy.trader.utility import load_json

            load_dotenv()

            auto_connect = os.getenv("CTP_AUTO_CONNECT", "false").lower() == "true"
            if auto_connect:
                # 读取connect_ctp.json配置文件
                filename = "connect_ctp.json"
                ctp_setting = load_json(filename)

                if ctp_setting:
                    main_engine.connect(ctp_setting, "CTP")
                    print("✓ CTP网关自动连接中...")
                else:
                    print("⚠️  未找到connect_ctp.json配置文件，跳过自动连接")
        except Exception as e:
            print(f"⚠️  CTP自动连接失败: {e}")

        print("\n🎉 ATMTrader启动完成！")

        # 运行应用
        qapp.exec()
        
    except ImportError as e:
        print(f"✗ 模块导入失败: {e}")
        print("请确保已正确安装vnpy环境")
        return False
    except Exception as e:
        print(f"✗ 程序启动失败: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
