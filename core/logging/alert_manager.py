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
import threading
from collections import defaultdict, deque
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict
from .logger_manager import get_logger

# 创建线程池执行器，用于异步发送告警
executor = ThreadPoolExecutor(max_workers=5)
logger = get_logger(symbol="ALERT")

# 时间与休眠的可注入点（测试中替换为假时钟）
_now = time.monotonic
_sleep = time.sleep

# 防护参数默认值；模块尾部的配置加载会覆盖它们
ALERT_RATE_LIMIT_PER_10S = 5
ALERT_CIRCUIT_COOLDOWN_SECONDS = 600
ALERT_RATE_BACKOFF_SECONDS = 15

# 飞书永久性错误码：重试不可能成功
_FEISHU_PERMANENT_CODES = {19001}
# 瞬时网络异常的最大重试次数与退避间隔
_TRANSIENT_RETRIES = 2
_TRANSIENT_BACKOFFS = (1.0, 5.0)
_RATE_WINDOW_SECONDS = 10.0
_RATE_DROP_SUMMARY_SECONDS = 60.0


class _Circuit:
    """单个webhook的熔断状态"""

    def __init__(self, opened_at: float, cooldown: float, reason: str):
        self.opened_at = opened_at
        self.cooldown = cooldown
        self.reason = reason
        self.suppressed = 0

    def is_open(self) -> bool:
        return _now() < self.opened_at + self.cooldown


def _mask_webhook(webhook: str) -> str:
    """日志中脱敏展示webhook，只保留末尾片段"""
    tail = webhook[-8:] if len(webhook) > 8 else webhook
    return f"...{tail}"


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

        # 限流与熔断状态（按webhook隔离，线程安全）
        self._lock = threading.Lock()
        self._send_times: Dict[str, deque] = defaultdict(deque)
        self._circuits: Dict[str, _Circuit] = {}
        self._rate_dropped: Dict[str, int] = defaultdict(int)
        self._last_rate_log: Dict[str, float] = {}

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

    def _acquire_send_slot(self, webhook: str) -> bool:
        """令牌桶限流：每10秒窗口内每个webhook最多ALERT_RATE_LIMIT_PER_10S条

        超限的发送被丢弃并计数，每60秒聚合输出一条摘要日志。
        """
        with self._lock:
            now = _now()
            times = self._send_times[webhook]
            while times and times[0] <= now - _RATE_WINDOW_SECONDS:
                times.popleft()

            if len(times) >= ALERT_RATE_LIMIT_PER_10S:
                self._rate_dropped[webhook] += 1
                dropped = self._rate_dropped[webhook]
                last_log = self._last_rate_log.get(webhook, 0.0)
                if now - last_log >= _RATE_DROP_SUMMARY_SECONDS:
                    logger.warning(
                        f"飞书告警限流：过去{_RATE_DROP_SUMMARY_SECONDS:.0f}秒丢弃 "
                        f"{dropped} 条发送到 {_mask_webhook(webhook)}，"
                        f"配额为每{_RATE_WINDOW_SECONDS:.0f}秒{ALERT_RATE_LIMIT_PER_10S}条"
                    )
                    self._rate_dropped[webhook] = 0
                    self._last_rate_log[webhook] = now
                return False

            times.append(now)
            return True

    def _circuit_blocks(self, webhook: str) -> bool:
        """熔断器：冷却期内静默跳过；冷却结束放行一条作为探测"""
        with self._lock:
            circuit = self._circuits.get(webhook)
            if circuit is None:
                return False
            if circuit.is_open():
                circuit.suppressed += 1
                return True
            return False

    def _open_circuit(self, webhook: str, reason: str, cooldown: float) -> None:
        """打开熔断：仅在从关闭到打开的瞬间输出一条错误日志"""
        with self._lock:
            existing = self._circuits.get(webhook)
            if existing is not None and existing.is_open():
                existing.suppressed += 1
                return
            self._circuits[webhook] = _Circuit(_now(), cooldown, reason)

        if cooldown >= ALERT_CIRCUIT_COOLDOWN_SECONDS:
            logger.error(
                f"飞书告警熔断{cooldown:.0f}秒：{reason}（webhook: "
                f"{_mask_webhook(webhook)}）。请检查 FEISHU_DEFAULT_WEBHOOK 等"
                f"配置是否有效，冷却结束后将自动探测恢复"
            )
        else:
            logger.warning(f"飞书告警暂停{cooldown:.0f}秒：{reason}")

    def _clear_circuit(self, webhook: str) -> None:
        """发送成功后清除熔断状态"""
        with self._lock:
            self._circuits.pop(webhook, None)

    def _send_now(self, webhook: str, secret: str, content: str) -> None:
        """同步执行单条告警的防护检查与发送（由线程池调用）"""
        if not self._acquire_send_slot(webhook):
            return

        if self._circuit_blocks(webhook):
            logger.debug(f"告警熔断中，跳过发送: {content[:50]}...")
            return

        timestamp = int(time.time())
        signature = self._generate_signature(timestamp, secret)
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {
            "timestamp": timestamp,
            "sign": signature,
            "msg_type": "text",
            "content": {"text": content},
        }

        attempt = 0
        while True:
            try:
                response = requests.post(
                    url=webhook,
                    data=json.dumps(payload),
                    headers=headers,
                    timeout=10
                )
                try:
                    result = response.json()
                except ValueError:
                    body_preview = (response.text or "")[:100]
                    reason = f"响应非JSON HTTP {response.status_code}: {body_preview}"
                    if response.status_code >= 500:
                        # 网关瞬时异常：退避重试，持续失败则熔断
                        if attempt < _TRANSIENT_RETRIES:
                            attempt += 1
                            _sleep(_TRANSIENT_BACKOFFS[attempt - 1])
                            continue
                        self._open_circuit(webhook, reason, ALERT_CIRCUIT_COOLDOWN_SECONDS)
                    else:
                        self._open_circuit(webhook, reason, ALERT_CIRCUIT_COOLDOWN_SECONDS)
                    return

                code = result.get("code", 0)
                msg = str(result.get("msg", ""))

                if result.get("msg") == "success" or code == 0:
                    logger.debug(f"飞书告警响应: {result}")
                    logger.success(f"飞书告警发送成功: {content[:50]}...")
                    self._clear_circuit(webhook)
                    return

                if code == 9499 or "too many request" in msg.lower():
                    # 飞书限频：当前消息不重试，短退避后自然恢复
                    self._open_circuit(webhook, f"飞书限频(9499)", ALERT_RATE_BACKOFF_SECONDS)
                    return

                if code in _FEISHU_PERMANENT_CODES or "invalid" in msg.lower():
                    self._open_circuit(
                        webhook,
                        f"飞书拒绝 code={code} msg={msg}，webhook令牌可能失效",
                        ALERT_CIRCUIT_COOLDOWN_SECONDS,
                    )
                    return

                # 未知错误：记录一次，不重试不熔断，避免放大请求
                logger.warning(f"飞书告警未成功(不重试): {result}")
                return

            except requests.RequestException as e:
                # 网络瞬时异常：退避重试，重试耗尽后单条日志放弃
                if attempt < _TRANSIENT_RETRIES:
                    attempt += 1
                    _sleep(_TRANSIENT_BACKOFFS[attempt - 1])
                    continue
                logger.error(f"飞书告警网络异常，已重试{attempt}次后放弃: {e}")
                return

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

                self._send_now(webhook_url, secret, content)

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

# 用配置文件中的防护参数覆盖模块默认值
try:
    from config.alert_config import (  # noqa: E402
        ALERT_RATE_LIMIT_PER_10S as _CFG_RATE_LIMIT,
        ALERT_CIRCUIT_COOLDOWN_SECONDS as _CFG_CIRCUIT,
        ALERT_RATE_BACKOFF_SECONDS as _CFG_BACKOFF,
    )
    ALERT_RATE_LIMIT_PER_10S = _CFG_RATE_LIMIT
    ALERT_CIRCUIT_COOLDOWN_SECONDS = _CFG_CIRCUIT
    ALERT_RATE_BACKOFF_SECONDS = _CFG_BACKOFF
except Exception as e:
    logger.warning(f"加载告警防护配置失败，使用默认值: {e}")
