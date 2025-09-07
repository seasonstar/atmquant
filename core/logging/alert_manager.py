#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警管理器
支持钉钉、飞书等多种通知方式的异步告警系统
"""

import traceback
import requests
import json
import hashlib
import base64
import hmac
import time
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
from .logger_manager import get_logger

# 创建线程池执行器，用于异步发送告警
executor = ThreadPoolExecutor(max_workers=5)
logger = get_logger(symbol="ALERT")


class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self.symbol_hook_map = {}  # 品种到webhook映射
        self.hook_secret_map = {}  # webhook到密钥映射
        self.default_feishu_url = ""
        self.default_feishu_secret = ""
        self.default_dingtalk_url = ""
        self.default_dingtalk_secret = ""
    
    def configure_feishu(
        self, 
        default_url: str, 
        default_secret: str,
        symbol_mapping: Optional[Dict[str, str]] = None,
        secret_mapping: Optional[Dict[str, str]] = None
    ):
        """
        配置飞书告警
        
        Args:
            default_url: 默认飞书webhook地址
            default_secret: 默认飞书密钥
            symbol_mapping: 品种到webhook的映射
            secret_mapping: webhook到密钥的映射
        """
        self.default_feishu_url = default_url
        self.default_feishu_secret = default_secret
        
        if symbol_mapping:
            self.symbol_hook_map.update(symbol_mapping)
        if secret_mapping:
            self.hook_secret_map.update(secret_mapping)
        
        logger.info("飞书告警配置完成")
    
    def configure_dingtalk(
        self,
        default_url: str,
        default_secret: str,
        symbol_mapping: Optional[Dict[str, str]] = None,
        secret_mapping: Optional[Dict[str, str]] = None
    ):
        """
        配置钉钉告警
        
        Args:
            default_url: 默认钉钉webhook地址
            default_secret: 默认钉钉密钥
            symbol_mapping: 品种到webhook的映射
            secret_mapping: webhook到密钥的映射
        """
        self.default_dingtalk_url = default_url
        self.default_dingtalk_secret = default_secret
        
        if symbol_mapping:
            self.symbol_hook_map.update(symbol_mapping)
        if secret_mapping:
            self.hook_secret_map.update(secret_mapping)
        
        logger.info("钉钉告警配置完成")
    
    def _generate_feishu_signature(self, timestamp: int, secret: str) -> str:
        """生成飞书签名"""
        string_to_sign = f'{timestamp}\n{secret}'
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), 
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign
    
    def _generate_dingtalk_signature(self, timestamp: int, secret: str) -> str:
        """生成钉钉签名"""
        string_to_sign = f'{timestamp}\n{secret}'
        hmac_code = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign
    
    def _extract_commodity_code(self, contract_string: str) -> Optional[str]:
        """从合约代码中提取品种代码"""
        if not contract_string:
            return None
            
        pattern = r'([a-zA-Z]{1,2})[0-9]+\.[A-Z]+'
        match = re.match(pattern, contract_string)
        if match:
            return match.group(1)
        else:
            return None
    
    def _should_send_alert(self, now: datetime, force_send: bool = False) -> bool:
        """判断是否应该发送告警"""
        if force_send:
            return True
        
        # 非当天不发送消息
        today = datetime.now().strftime('%Y-%m-%d')
        if today != now.strftime('%Y-%m-%d'):
            return False
        
        # 判断从周六凌晨3点到周日24点前不发送消息
        if now.weekday() == 5 and now.hour >= 3:  # 周六凌晨3点后
            return False
        if now.weekday() == 6:  # 整个周日
            return False
        
        return True
    
    def send_feishu_alert(
        self, 
        content: str, 
        symbol: Optional[str] = None,
        now: Optional[datetime] = None,
        force_send: bool = False
    ):
        """
        发送飞书告警消息
        
        Args:
            content: 消息内容
            symbol: 品种代码或合约代码
            now: 当前时间，默认为当前时间
            force_send: 是否强制发送，忽略时间限制
        """
        if now is None:
            now = datetime.now()
        
        # 提取品种代码
        commodity_code = self._extract_commodity_code(symbol) if symbol else None
        
        def send_message():
            """异步发送消息的内部函数"""
            try:
                # 检查是否应该发送
                if not self._should_send_alert(now, force_send):
                    logger.debug(f"跳过发送告警消息：{content[:50]}...")
                    return
                
                # 选择webhook和密钥
                webhook_url = self.symbol_hook_map.get(
                    commodity_code, 
                    self.default_feishu_url
                )
                secret = self.hook_secret_map.get(
                    commodity_code,
                    self.default_feishu_secret
                )
                
                if not webhook_url or not secret:
                    logger.error("飞书webhook或密钥未配置")
                    return
                
                # 生成签名
                timestamp = int(time.time())
                signature = self._generate_feishu_signature(timestamp, secret)
                
                # 构造消息
                headers = {
                    "Content-Type": "application/json; charset=utf-8"
                }
                
                payload = {
                    "timestamp": timestamp,
                    "sign": signature,
                    "msg_type": "text",
                    "content": {
                        "text": content
                    }
                }
                
                # 发送请求，最多重试3次
                for attempt in range(3):
                    try:
                        response = requests.post(
                            url=webhook_url,
                            data=json.dumps(payload),
                            headers=headers,
                            timeout=10
                        )
                        
                        result = response.json()
                        logger.debug(f"飞书告警响应: {result}")
                        
                        if result.get('msg') == 'success':
                            logger.success(f"飞书告警发送成功: {content[:50]}...")
                            break
                        else:
                            logger.warning(f"飞书告警发送失败: {result}")
                            
                    except Exception as e:
                        logger.error(f"飞书告警发送异常 (尝试 {attempt + 1}/3): {e}")
                        if attempt < 2:  # 不是最后一次尝试
                            time.sleep(5)
                        continue
                
                # 每处理完一个任务后等待1秒钟
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"飞书告警处理异常: {e}")
                logger.error(traceback.format_exc())
        
        # 提交到线程池异步执行
        executor.submit(send_message)
    
    def send_dingtalk_alert(
        self,
        content: str,
        symbol: Optional[str] = None,
        now: Optional[datetime] = None,
        force_send: bool = False
    ):
        """
        发送钉钉告警消息
        
        Args:
            content: 消息内容
            symbol: 品种代码或合约代码
            now: 当前时间，默认为当前时间
            force_send: 是否强制发送，忽略时间限制
        """
        if now is None:
            now = datetime.now()
        
        # 提取品种代码
        commodity_code = self._extract_commodity_code(symbol) if symbol else None
        
        def send_message():
            """异步发送消息的内部函数"""
            try:
                # 检查是否应该发送
                if not self._should_send_alert(now, force_send):
                    logger.debug(f"跳过发送钉钉告警消息：{content[:50]}...")
                    return
                
                # 选择webhook和密钥
                webhook_url = self.symbol_hook_map.get(
                    commodity_code,
                    self.default_dingtalk_url
                )
                secret = self.hook_secret_map.get(
                    commodity_code,
                    self.default_dingtalk_secret
                )
                
                if not webhook_url or not secret:
                    logger.error("钉钉webhook或密钥未配置")
                    return
                
                # 生成签名
                timestamp = int(time.time() * 1000)  # 钉钉使用毫秒时间戳
                signature = self._generate_dingtalk_signature(timestamp, secret)
                
                # 构造URL
                sign_url = f"{webhook_url}&timestamp={timestamp}&sign={signature}"
                
                # 构造消息
                headers = {
                    "Content-Type": "application/json; charset=utf-8"
                }
                
                payload = {
                    "msgtype": "text",
                    "text": {
                        "content": content
                    }
                }
                
                # 发送请求，最多重试3次
                for attempt in range(3):
                    try:
                        response = requests.post(
                            url=sign_url,
                            data=json.dumps(payload),
                            headers=headers,
                            timeout=10
                        )
                        
                        result = response.json()
                        logger.debug(f"钉钉告警响应: {result}")
                        
                        if result.get('errcode') == 0:
                            logger.success(f"钉钉告警发送成功: {content[:50]}...")
                            break
                        else:
                            logger.warning(f"钉钉告警发送失败: {result}")
                            
                    except Exception as e:
                        logger.error(f"钉钉告警发送异常 (尝试 {attempt + 1}/3): {e}")
                        if attempt < 2:  # 不是最后一次尝试
                            time.sleep(5)
                        continue
                
                # 每处理完一个任务后等待1秒钟
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"钉钉告警处理异常: {e}")
                logger.error(traceback.format_exc())
        
        # 提交到线程池异步执行
        executor.submit(send_message)
    
    def send_alert(
        self,
        content: str,
        symbol: Optional[str] = None,
        alert_type: str = "feishu",
        force_send: bool = False
    ):
        """
        发送告警消息（统一接口）
        
        Args:
            content: 消息内容
            symbol: 品种代码或合约代码
            alert_type: 告警类型，支持 'feishu', 'dingtalk', 'all'
            force_send: 是否强制发送
        """
        now = datetime.now()
        
        if alert_type == "feishu":
            self.send_feishu_alert(content, symbol, now, force_send)
        elif alert_type == "dingtalk":
            self.send_dingtalk_alert(content, symbol, now, force_send)
        elif alert_type == "all":
            self.send_feishu_alert(content, symbol, now, force_send)
            self.send_dingtalk_alert(content, symbol, now, force_send)
        else:
            logger.error(f"不支持的告警类型: {alert_type}")


# 全局告警管理器实例
alert_manager = AlertManager()