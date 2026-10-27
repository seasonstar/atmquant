#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书告警管理器
支持异步告警发送
"""

import traceback
import requests
import json
import hashlib
import base64
import hmac
import time
import re
import atexit
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict
from .logger_manager import get_logger

# 创建线程池执行器，用于异步发送告警
executor = ThreadPoolExecutor(max_workers=5)
logger = get_logger(symbol="ALERT")


def cleanup_executor():
    """清理线程池，防止信号量泄漏"""
    try:
        # 退出阶段不再新增日志，避免写入已关闭的控制台捕获流
        executor.shutdown(wait=False)
    except Exception:
        pass


# 注册退出时的清理函数
atexit.register(cleanup_executor)


class AlertManager:
    """飞书告警管理器"""

    def __init__(self):
        self.symbol_hook_map: Dict[str, str] = {}  # 品种到webhook映射
        self.hook_secret_map: Dict[str, str] = {}  # webhook到密钥映射
        self.default_webhook = ""
        self.default_secret = ""

    def configure(
        self,
        webhook: str,
        secret: str,
        symbol_mapping: Optional[Dict[str, str]] = None,
        secret_mapping: Optional[Dict[str, str]] = None
    ):
        """
        配置飞书告警

        Args:
            webhook: 飞书webhook地址
            secret: 飞书密钥
            symbol_mapping: 品种到webhook的映射（可选）
            secret_mapping: webhook到密钥的映射（可选）
        """
        self.default_webhook = webhook
        self.default_secret = secret

        if symbol_mapping:
            self.symbol_hook_map.update(symbol_mapping)
        if secret_mapping:
            self.hook_secret_map.update(secret_mapping)

        logger.info("飞书告警配置完成")

    def _generate_signature(self, timestamp: int, secret: str) -> str:
        """生成飞书签名"""
        string_to_sign = f'{timestamp}\n{secret}'
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode('utf-8')

    def _extract_commodity_code(self, contract_string: str) -> Optional[str]:
        """从合约代码中提取品种代码"""
        if not contract_string:
            return None

        pattern = r'([a-zA-Z]{1,2})[0-9]+\.[A-Z]+'
        match = re.match(pattern, contract_string)
        return match.group(1) if match else None

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

    def send_alert(
        self,
        content: str,
        symbol: Optional[str] = None,
        force_send: bool = False
    ):
        """
        发送飞书告警消息

        Args:
            content: 消息内容
            symbol: 品种代码或合约代码（可选）
            force_send: 是否强制发送，忽略时间限制
        """
        # 检查全局告警开关
        from config.alert_config import ALERT_ENABLED
        if not ALERT_ENABLED:
            logger.debug(f"告警已禁用，跳过发送: {content[:50]}...")
            return

        now = datetime.now()
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
                    self.default_webhook
                )
                secret = self.hook_secret_map.get(
                    commodity_code,
                    self.default_secret
                )

                if not webhook_url or not secret:
                    logger.error("飞书webhook或密钥未配置")
                    return

                # 生成签名
                timestamp = int(time.time())
                signature = self._generate_signature(timestamp, secret)

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


# 全局告警管理器实例
alert_manager = AlertManager()

# 自动从配置文件加载告警配置
try:
    from config.alert_config import FEISHU_CONFIG

    if FEISHU_CONFIG["default_webhook"] and FEISHU_CONFIG["default_secret"]:
        alert_manager.configure(
            webhook=FEISHU_CONFIG["default_webhook"],
            secret=FEISHU_CONFIG["default_secret"],
            symbol_mapping=FEISHU_CONFIG.get("symbol_webhook_map", {}),
            secret_mapping=FEISHU_CONFIG.get("webhook_secret_map", {})
        )
except Exception as e:
    logger.warning(f"加载告警配置失败: {e}")
