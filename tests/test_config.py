#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置系统测试
"""

import os
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import load_env_file, get_atmquant_settings


def test_load_env_file():
    """测试.env文件加载"""
    # 创建临时.env文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write("""# 测试配置
DATABASE_TYPE=mysql
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATAFEED_NAME=tqsdk
DATAFEED_USERNAME=test_user
""")
        temp_env_file = f.name
    
    try:
        # 加载配置
        load_env_file(temp_env_file)
        
        # 验证环境变量
        assert os.getenv("DATABASE_TYPE") == "mysql"
        assert os.getenv("DATABASE_HOST") == "localhost"
        assert os.getenv("DATABASE_PORT") == "3306"
        assert os.getenv("DATAFEED_NAME") == "tqsdk"
        assert os.getenv("DATAFEED_USERNAME") == "test_user"
        
        print("✓ .env文件加载测试通过")
        
    finally:
        # 清理临时文件
        os.unlink(temp_env_file)


def test_get_atmquant_settings():
    """测试配置获取"""
    # 设置测试环境变量
    os.environ["DATABASE_TYPE"] = "postgresql"
    os.environ["DATABASE_HOST"] = "test.example.com"
    os.environ["DATABASE_PORT"] = "5432"
    os.environ["DATAFEED_NAME"] = "joinquant"
    
    # 获取配置
    settings = get_atmquant_settings()
    
    # 验证配置
    assert settings["database.name"] == "postgresql"
    assert settings["database.host"] == "test.example.com"
    assert settings["database.port"] == 5432
    assert settings["datafeed.name"] == "joinquant"
    
    # 验证默认配置
    assert settings["font.family"] == "微软雅黑"
    assert settings["font.size"] == 12
    assert settings["log.active"] is True
    
    print("✓ 配置获取测试通过")


def test_config_priority():
    """测试配置优先级"""
    # 清除环境变量
    if "DATABASE_TYPE" in os.environ:
        del os.environ["DATABASE_TYPE"]
    
    # 测试默认配置
    settings = get_atmquant_settings()
    assert settings["database.name"] == "sqlite"
    
    # 设置环境变量
    os.environ["DATABASE_TYPE"] = "mysql"
    
    # 测试环境变量覆盖
    settings = get_atmquant_settings()
    assert settings["database.name"] == "mysql"
    
    print("✓ 配置优先级测试通过")


def main():
    """运行所有测试"""
    print("开始配置系统测试...")
    print("=" * 40)
    
    try:
        test_load_env_file()
        test_get_atmquant_settings()
        test_config_priority()
        
        print("=" * 40)
        print("✅ 所有测试通过！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)