#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书告警配置
"""

import os
from pathlib import Path


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
                    os.environ.setdefault(key.strip(), value.strip())
    except Exception as e:
        print(f"⚠️  加载.env文件失败: {e}")


# 加载环境变量
load_env_file()

# 全局告警开关（可通过环境变量 ALERT_ENABLED 控制）
# 设置为 false 可在回测等场景下禁用所有告警
ALERT_ENABLED = os.getenv("ALERT_ENABLED", "true").lower() == "true"

# ---- 告警自动防护配置 ----
# 回测模式下策略告警默认只写日志、不发网络请求；置 true 可恢复发送
ALERT_BACKTEST_ENABLED = os.getenv("ALERT_BACKTEST_ENABLED", "false").lower() == "true"
# 客户端限流：每个webhook每10秒最多发送条数（对齐飞书频率限制）
ALERT_RATE_LIMIT_PER_10S = int(os.getenv("ALERT_RATE_LIMIT_PER_10S", "5"))
# 永久故障（令牌失效等）熔断时长（秒）
ALERT_CIRCUIT_COOLDOWN_SECONDS = int(os.getenv("ALERT_CIRCUIT_COOLDOWN_SECONDS", "600"))
# 飞书限频(9499)后的短退避时长（秒）
ALERT_RATE_BACKOFF_SECONDS = int(os.getenv("ALERT_RATE_BACKOFF_SECONDS", "15"))

# 飞书配置
FEISHU_CONFIG = {
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

# 告警配置
ALERT_CONFIG = {
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


def should_alert_for_level(level: str) -> bool:
    """检查指定级别是否应该发送告警"""
    return ALERT_CONFIG["alert_levels"].get(level, False)