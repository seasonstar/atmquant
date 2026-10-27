#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置系统测试
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

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
        # 隔离已存在于开发机环境中的同名变量，验证.env只补缺失值
        with patch.dict(os.environ, {}, clear=False):
            for key in (
                "DATABASE_TYPE",
                "DATABASE_HOST",
                "DATABASE_PORT",
                "DATAFEED_NAME",
                "DATAFEED_USERNAME",
            ):
                os.environ.pop(key, None)

            load_env_file(temp_env_file)

            assert os.getenv("DATABASE_TYPE") == "mysql"
            assert os.getenv("DATABASE_HOST") == "localhost"
            assert os.getenv("DATABASE_PORT") == "3306"
            assert os.getenv("DATAFEED_NAME") == "tqsdk"
            assert os.getenv("DATAFEED_USERNAME") == "test_user"

        print("✓ .env文件加载测试通过")
        
    finally:
        # 清理临时文件
        os.unlink(temp_env_file)


def test_env_file_preserves_existing_environment():
    """显式进程环境变量的优先级必须高于.env文件"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write("DATABASE_TYPE=mysql\n")
        temp_env_file = f.name

    try:
        with patch.dict(os.environ, {"DATABASE_TYPE": "postgresql"}, clear=False):
            load_env_file(temp_env_file)
            assert os.environ["DATABASE_TYPE"] == "postgresql"
    finally:
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
    with tempfile.TemporaryDirectory() as temp_dir:
        original_cwd = os.getcwd()
        try:
            # 在没有.env的目录验证默认值，避免开发机配置影响测试
            os.chdir(temp_dir)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DATABASE_TYPE", None)
                settings = get_atmquant_settings()
                assert settings["database.name"] == "sqlite"

                # 显式环境变量覆盖默认值
                os.environ["DATABASE_TYPE"] = "mysql"
                settings = get_atmquant_settings()
                assert settings["database.name"] == "mysql"
        finally:
            os.chdir(original_cwd)

    print("✓ 配置优先级测试通过")


def main():
    """运行所有测试"""
    print("开始配置系统测试...")
    print("=" * 40)
    
    try:
        test_load_env_file()
        test_env_file_preserves_existing_environment()
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