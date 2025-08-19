#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vnpy插件配置管理
"""

# CTA策略引擎配置
CTA_STRATEGY_SETTINGS = {
    "template_path": "strategies/templates/",
    "strategy_path": "strategies/",
    "log_level": "INFO",
    "risk_check": True,
    "max_position": 10,
    "max_order_size": 100
}

# 数据管理配置
DATA_MANAGER_SETTINGS = {
    "data_path": "data/",
    "auto_update": True,
    "update_interval": 3600,  # 秒
    "data_sources": ["simnow", "tushare"],
    "symbols": ["rb2501", "hc2501", "i2501"]
}

# 回测引擎配置
BACKTEST_SETTINGS = {
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "initial_capital": 1000000,
    "commission_rate": 0.0001,
    "slippage": 1,
    "size_multiplier": 10
}

# MySQL数据库配置
MYSQL_SETTINGS = {
    "host": "localhost",
    "port": 3306,
    "database": "vnpy_data",
    "user": "vnpy_user", 
    "password": "vnpy_password",
    "charset": "utf8mb4",
    "pool_size": 10,
    "pool_recycle": 3600
}

# CTP连接配置
CTP_SETTINGS = {
    # SimNow 7x24环境配置
    "simnow_24h": {
        "用户名": "your_simnow_account",
        "密码": "your_simnow_password", 
        "经纪商代码": "9999",
        "交易服务器": "180.168.146.187:10130",
        "行情服务器": "180.168.146.187:10131",
        "产品名称": "simnow_client_test",
        "授权编码": "0000000000000000",
        "产品信息": ""
    },
    
    # SimNow交易时段环境配置  
    "simnow_trading": {
        "用户名": "your_simnow_account",
        "密码": "your_simnow_password",
        "经纪商代码": "9999", 
        "交易服务器": "180.168.146.187:10201",
        "行情服务器": "180.168.146.187:10211",
        "产品名称": "simnow_client_test",
        "授权编码": "0000000000000000",
        "产品信息": ""
    }
}

# 当前使用的CTP配置
CURRENT_CTP_SETTINGS = CTP_SETTINGS["simnow_24h"]