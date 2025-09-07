#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警配置管理
支持飞书、钉钉等多种告警方式的配置
"""

import os
from typing import Dict, Optional
from pathlib import Path

# 加载环境变量
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

# 加载环境变量
load_env_file()

# 飞书配置
FEISHU_CONFIG = {
    # 默认飞书webhook配置
    "default_webhook": os.getenv("FEISHU_DEFAULT_WEBHOOK", ""),
    "default_secret": os.getenv("FEISHU_DEFAULT_SECRET", ""),
    
    # 品种特定的webhook映射（可选）
    "symbol_webhook_map": {
        # 示例：不同品种可以发送到不同的群
        # "rb": "https://open.feishu.cn/open-apis/bot/v2/hook/your-rb-webhook",
        # "cu": "https://open.feishu.cn/open-apis/bot/v2/hook/your-cu-webhook",
    },
    
    # webhook对应的密钥映射
    "webhook_secret_map": {
        # 示例：每个webhook对应的密钥
        # "https://open.feishu.cn/open-apis/bot/v2/hook/your-rb-webhook": "your-rb-secret",
        # "https://open.feishu.cn/open-apis/bot/v2/hook/your-cu-webhook": "your-cu-secret",
    }
}

# 钉钉配置
DINGTALK_CONFIG = {
    # 默认钉钉webhook配置
    "default_webhook": os.getenv("DINGTALK_DEFAULT_WEBHOOK", ""),
    "default_secret": os.getenv("DINGTALK_DEFAULT_SECRET", ""),
    
    # 品种特定的webhook映射（可选）
    "symbol_webhook_map": {
        # 示例：不同品种可以发送到不同的群
        # "rb": "https://oapi.dingtalk.com/robot/send?access_token=your-rb-token",
        # "cu": "https://oapi.dingtalk.com/robot/send?access_token=your-cu-token",
    },
    
    # webhook对应的密钥映射
    "webhook_secret_map": {
        # 示例：每个webhook对应的密钥
        # "https://oapi.dingtalk.com/robot/send?access_token=your-rb-token": "your-rb-secret",
        # "https://oapi.dingtalk.com/robot/send?access_token=your-cu-token": "your-cu-secret",
    }
}

# 告警配置
ALERT_CONFIG = {
    # 启用的告警类型
    "enabled_types": ["feishu"],  # 可选: "feishu", "dingtalk", "email"
    
    # 默认告警类型
    "default_type": "feishu",
    
    # 告警级别配置
    "alert_levels": {
        "ERROR": True,      # 错误级别告警
        "CRITICAL": True,   # 严重错误告警
        "WARNING": False,   # 警告级别告警（默认不发送）
        "SUCCESS": False,   # 成功消息（默认不发送）
    },
    
    # 时间限制配置
    "time_restrictions": {
        "enabled": True,           # 是否启用时间限制
        "weekend_silence": True,   # 周末是否静音
        "silence_start_hour": 3,   # 周六静音开始时间（小时）
    },
    
    # 消息格式配置
    "message_format": {
        "include_timestamp": True,  # 是否包含时间戳
        "include_symbol": True,     # 是否包含品种信息
        "max_length": 1000,        # 消息最大长度
    }
}

def get_alert_config() -> Dict:
    """获取告警配置"""
    return {
        "feishu": FEISHU_CONFIG,
        "dingtalk": DINGTALK_CONFIG,
        "alert": ALERT_CONFIG
    }

def is_alert_enabled(alert_type: str) -> bool:
    """检查指定类型的告警是否启用"""
    return alert_type in ALERT_CONFIG["enabled_types"]

def should_alert_for_level(level: str) -> bool:
    """检查指定级别是否应该发送告警"""
    return ALERT_CONFIG["alert_levels"].get(level, False)