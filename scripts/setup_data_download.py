#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货数据下载环境设置脚本
帮助用户快速配置数据下载环境
"""

import os
import sys
import subprocess
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_python_version():
    """检查Python版本"""
    print("检查Python版本...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"✗ Python版本过低: {version.major}.{version.minor}")
        print("  需要Python 3.8或更高版本")
        return False
    else:
        print(f"✓ Python版本: {version.major}.{version.minor}.{version.micro}")
        return True


def install_dependencies():
    """安装依赖包"""
    print("\n安装依赖包...")
    
    dependencies = [
        "tqsdk",
        "vnpy_sqlite",
        "schedule"  # 用于定时任务
    ]
    
    success_count = 0
    
    for dep in dependencies:
        print(f"安装 {dep}...")
        try:
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", dep
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                print(f"✓ {dep} 安装成功")
                success_count += 1
            else:
                print(f"✗ {dep} 安装失败: {result.stderr}")
        except subprocess.TimeoutExpired:
            print(f"✗ {dep} 安装超时")
        except Exception as e:
            print(f"✗ {dep} 安装异常: {e}")
    
    print(f"\n依赖安装完成: {success_count}/{len(dependencies)} 成功")
    return success_count == len(dependencies)


def setup_config_files():
    """设置配置文件"""
    print("\n设置配置文件...")
    
    # 检查.env文件
    env_file = project_root / ".env"
    env_example = project_root / ".env.example"
    
    if not env_file.exists() and env_example.exists():
        try:
            import shutil
            shutil.copy(env_example, env_file)
            print("✓ 创建.env配置文件")
        except Exception as e:
            print(f"✗ 创建.env文件失败: {e}")
            return False
    elif env_file.exists():
        print("✓ .env配置文件已存在")
    else:
        print("✗ 缺少.env.example模板文件")
        return False
    
    # 检查下载配置文件
    download_config = project_root / "config" / "download_config.json"
    if download_config.exists():
        print("✓ 下载配置文件已存在")
    else:
        print("⚠️  下载配置文件不存在，将使用默认配置")
    
    return True


def test_basic_functionality():
    """测试基本功能"""
    print("\n测试基本功能...")
    
    try:
        # 测试配置加载
        from config.settings import apply_settings
        apply_settings()
        print("✓ 配置系统正常")
        
        # 测试期货配置
        from config.futures_config import get_all_symbols, get_futures_info
        symbols = get_all_symbols()
        if symbols:
            print(f"✓ 期货配置正常，支持 {len(symbols)} 个品种")
        else:
            print("✗ 期货配置异常")
            return False
        
        # 测试数据库连接
        from vnpy.trader.database import get_database
        database = get_database()
        print("✓ 数据库连接正常")
        
        return True
        
    except ImportError as e:
        print(f"✗ 模块导入失败: {e}")
        return False
    except Exception as e:
        print(f"✗ 功能测试失败: {e}")
        return False


def show_next_steps():
    """显示后续步骤"""
    print("\n" + "="*60)
    print("环境设置完成！后续步骤：")
    print("="*60)
    
    print("\n1. 配置数据源账户")
    print("   编辑 .env 文件，填入天勤账户信息：")
    print("   DATAFEED_USERNAME=your_phone_number")
    print("   DATAFEED_PASSWORD=your_password")
    
    print("\n2. 测试数据下载")
    print("   python scripts/test_download.py")
    
    print("\n3. 查看支持的品种")
    print("   python scripts/download_futures_data.py --list-symbols")
    
    print("\n4. 开始下载数据")
    print("   python scripts/download_futures_data.py --symbols rb")
    
    print("\n5. 验证数据质量")
    print("   python scripts/verify_data.py --symbols rb")
    
    print("\n6. 设置定时任务")
    print("   参考文档设置cron或Windows任务计划")
    
    print("\n详细使用说明请查看：")
    print("   docs/futures_data_download.md")
    print("   articles/以AI量化为生：5.期货数据定时下载与合约管理.md")


def main():
    """主函数"""
    print("期货数据下载环境设置")
    print("="*60)
    
    # 检查Python版本
    if not check_python_version():
        return False
    
    # 安装依赖
    if not install_dependencies():
        print("\n⚠️  部分依赖安装失败，可能影响功能使用")
    
    # 设置配置文件
    if not setup_config_files():
        print("\n✗ 配置文件设置失败")
        return False
    
    # 测试基本功能
    if not test_basic_functionality():
        print("\n✗ 基本功能测试失败")
        return False
    
    # 显示后续步骤
    show_next_steps()
    
    print("\n🎉 环境设置成功！")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)