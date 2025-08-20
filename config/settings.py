#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATMQuant配置管理
轻量级配置覆盖机制，直接从.env文件加载配置并应用到vnpy
"""

import os
from pathlib import Path
from typing import Dict, Any
from logging import INFO
from tzlocal import get_localzone_name


def load_env_file(env_file: str = ".env") -> None:
    """加载.env文件到环境变量"""
    env_path = Path(env_file)
    if not env_path.exists():
        return
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    except Exception as e:
        print(f"⚠️  加载.env文件失败: {e}")


def get_atmquant_settings() -> Dict[str, Any]:
    """获取ATMQuant配置"""
    # 加载.env文件
    load_env_file()
    
    # 基础配置
    settings = {
        # 字体设置
        "font.family": "微软雅黑",
        "font.size": 12,
        
        # 日志设置
        "log.active": True,
        "log.level": INFO,
        "log.console": True,
        "log.file": True,
        
        # 邮件设置
        "email.server": os.getenv("EMAIL_SERVER", ""),
        "email.port": int(os.getenv("EMAIL_PORT", "0")),
        "email.username": os.getenv("EMAIL_USERNAME", ""),
        "email.password": os.getenv("EMAIL_PASSWORD", ""),
        "email.sender": os.getenv("EMAIL_SENDER", ""),
        "email.receiver": os.getenv("EMAIL_RECEIVER", ""),
        
        # 数据源设置
        "datafeed.name": os.getenv("DATAFEED_NAME", ""),
        "datafeed.username": os.getenv("DATAFEED_USERNAME", ""),
        "datafeed.password": os.getenv("DATAFEED_PASSWORD", ""),
        
        # 数据库设置
        "database.timezone": get_localzone_name(),
        "database.name": os.getenv("DATABASE_TYPE", "sqlite"),
        "database.database": os.getenv("DATABASE_NAME", "atmquant.db"),
        "database.host": os.getenv("DATABASE_HOST", ""),
        "database.port": int(os.getenv("DATABASE_PORT", "0")),
        "database.user": os.getenv("DATABASE_USER", ""),
        "database.password": os.getenv("DATABASE_PASSWORD", ""),
    }
    
    return settings


def apply_settings():
    """应用配置到vnpy.trader.setting.SETTINGS"""
    try:
        from vnpy.trader.setting import SETTINGS
        
        # 获取ATMQuant配置
        atmquant_settings = get_atmquant_settings()
        
        # 更新vnpy的SETTINGS
        SETTINGS.update(atmquant_settings)
        
        print("✓ ATMQuant配置已加载")
        return True
        
    except ImportError:
        print("⚠️  VeighNa未安装")
        return False


def print_config():
    """打印当前配置"""
    settings = get_atmquant_settings()
    
    print("\n" + "="*50)
    print("ATMQuant配置")
    print("="*50)
    print(f"数据库: {settings['database.name']}")
    if settings['database.name'] == 'sqlite':
        print(f"数据库文件: {settings['database.database']}")
    else:
        print(f"数据库地址: {settings['database.host']}:{settings['database.port']}")
        print(f"数据库名: {settings['database.database']}")
    
    print(f"数据源: {settings['datafeed.name'] or '未配置'}")
    print(f"时区: {settings['database.timezone']}")
    print("="*50)