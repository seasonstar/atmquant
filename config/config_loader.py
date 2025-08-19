#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载器
"""

import json
import os
from typing import Dict, Any

class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self._configs = {}
    
    def load_config(self, config_name: str) -> Dict[str, Any]:
        """加载配置文件"""
        if config_name in self._configs:
            return self._configs[config_name]
        
        config_file = os.path.join(self.config_dir, f"{config_name}.json")
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self._configs[config_name] = config
                return config
        else:
            # 如果配置文件不存在，返回默认配置
            return self._get_default_config(config_name)
    
    def save_config(self, config_name: str, config: Dict[str, Any]):
        """保存配置文件"""
        config_file = os.path.join(self.config_dir, f"{config_name}.json")
        
        os.makedirs(self.config_dir, exist_ok=True)
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        self._configs[config_name] = config
    
    def _get_default_config(self, config_name: str) -> Dict[str, Any]:
        """获取默认配置"""
        from .plugin_settings import (
            CTA_STRATEGY_SETTINGS,
            DATA_MANAGER_SETTINGS, 
            BACKTEST_SETTINGS,
            MYSQL_SETTINGS,
            CURRENT_CTP_SETTINGS
        )
        
        defaults = {
            "cta_strategy": CTA_STRATEGY_SETTINGS,
            "data_manager": DATA_MANAGER_SETTINGS,
            "backtest": BACKTEST_SETTINGS,
            "mysql": MYSQL_SETTINGS,
            "ctp": CURRENT_CTP_SETTINGS
        }
        
        return defaults.get(config_name, {})

# 全局配置加载器实例
config_loader = ConfigLoader()