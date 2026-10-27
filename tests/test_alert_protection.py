"""告警自动防护机制的回归测试。

覆盖四个防线：回测降级、客户端限流、熔断器、重试语义。
"""

import sys
from unittest import mock

import pytest

import core.logging.alert_manager  # noqa: F401  确保模块已加载

# core.logging.__init__ 会把子模块名遮蔽为全局实例，这里取真模块
am = sys.modules["core.logging.alert_manager"]
from core.logging.alert_manager import AlertManager
from vnpy_ctastrategy.base import EngineType


WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/test-token-abcdef"
SECRET = "test-secret"


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=False, text=""):
        self._payload = payload
        self.status_code = status_code
        self._json_error = json_error
        self.text = text or (str(payload) if payload is not None else "")

    def json(self):
        if self._json_error:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class FakeClock:
    """可手动推进的单调时钟"""

    def __init__(self):
        self.current = 1000.0

    def __call__(self):
        return self.current

    def advance(self, seconds: float):
        self.current += seconds


@pytest.fixture
def manager():
    m = AlertManager()
    m.configure(webhook=WEBHOOK, secret=SECRET)
    return m


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(am, "_now", fake)
    return fake


@pytest.fixture
def no_sleep(monkeypatch):
    return monkeypatch.setattr(am, "_sleep", lambda seconds: None)


@pytest.fixture
def post(monkeypatch):
    fake = mock.Mock(return_value=FakeResponse({"msg": "success"}))
    monkeypatch.setattr(am.requests, "post", fake)
    return fake


# ---------- 第1层：回测自动降级 ----------


class MockEngine:
    def __init__(self, engine_type):
        self.engine_type = engine_type


def _make_strategy(engine_type):
    from core.strategies.triple_ma_strategy import TripleMaStrategy

    return TripleMaStrategy(MockEngine(engine_type), "test_strategy", "rb2501.SHFE", {})


def test_backtest_strategy_does_not_dispatch_alert(monkeypatch):
    """回测引擎中的策略告警只写日志，不进入告警管理器"""
    sent = mock.Mock()
    monkeypatch.setattr("core.strategies.base_strategy.alert_manager", sent)

    strategy = _make_strategy(EngineType.BACKTESTING)
    strategy.send_alert("止损触发")

    sent.send_alert.assert_not_called()


def test_live_strategy_dispatches_alert(monkeypatch):
    """实盘引擎中的策略告警正常进入告警管理器"""
    sent = mock.Mock()
    monkeypatch.setattr("core.strategies.base_strategy.alert_manager", sent)

    strategy = _make_strategy(EngineType.LIVE)
    strategy.send_alert("止损触发")

    sent.send_alert.assert_called_once()


# ---------- 第2层：客户端限流 ----------


def test_rate_limiter_drops_beyond_quota_and_recovers(manager, clock, post):
    """10秒窗口内超过配额的发送被丢弃，窗口滚动后恢复"""
    for _ in range(am.ALERT_RATE_LIMIT_PER_10S):
        manager._send_now(WEBHOOK, SECRET, "告警")

    assert post.call_count == am.ALERT_RATE_LIMIT_PER_10S

    manager._send_now(WEBHOOK, SECRET, "超限告警")
    assert post.call_count == am.ALERT_RATE_LIMIT_PER_10S  # 被丢弃

    clock.advance(11)
    manager._send_now(WEBHOOK, SECRET, "窗口后告警")
    assert post.call_count == am.ALERT_RATE_LIMIT_PER_10S + 1


# ---------- 第3层：熔断器 ----------


def test_permanent_error_opens_circuit_and_skips_until_cooldown(
    manager, clock, post, no_sleep
):
    """19001令牌失效：单条错误日志熔断，冷却期内静默跳过，冷却后放行探测"""
    post.return_value = FakeResponse({"code": 19001, "msg": "param invalid: token"})

    manager._send_now(WEBHOOK, SECRET, "第一条")
    assert post.call_count == 1

    manager._send_now(WEBHOOK, SECRET, "熔断期内")
    manager._send_now(WEBHOOK, SECRET, "熔断期内2")
    assert post.call_count == 1  # 熔断期内不再发请求

    clock.advance(am.ALERT_CIRCUIT_COOLDOWN_SECONDS + 1)
    post.return_value = FakeResponse({"msg": "success"})
    manager._send_now(WEBHOOK, SECRET, "探测恢复")
    assert post.call_count == 2


def test_feishu_rate_limit_pauses_without_retry(manager, clock, post, no_sleep):
    """9499限频：不重试当前消息，短退避内继续跳过"""
    post.return_value = FakeResponse({"code": 9499, "msg": "too many request"})

    manager._send_now(WEBHOOK, SECRET, "被限频的消息")
    assert post.call_count == 1  # 不做立即重试

    manager._send_now(WEBHOOK, SECRET, "退避期内")
    assert post.call_count == 1

    clock.advance(am.ALERT_RATE_BACKOFF_SECONDS + 1)
    post.return_value = FakeResponse({"msg": "success"})
    manager._send_now(WEBHOOK, SECRET, "退避后")
    assert post.call_count == 2


# ---------- 第4层：重试语义 ----------


def test_non_json_response_is_classified_not_crashed(manager, clock, post, no_sleep):
    """非JSON响应按永久故障处理并熔断，不进入裸重试循环"""
    post.return_value = FakeResponse(json_error=True, status_code=200, text="<html>bad</html>")

    manager._send_now(WEBHOOK, SECRET, "解析失败的消息")

    assert post.call_count == 1  # 分类处理，不无脑重试
    circuit = manager._circuits[WEBHOOK]
    assert circuit.reason
    assert "200" in circuit.reason


def test_network_error_retries_with_backoff_then_succeeds(manager, clock, post, no_sleep):
    """网络瞬时异常按退避重试，最终成功并清除熔断状态"""
    import requests as requests_lib

    post.side_effect = [
        requests_lib.ConnectionError("boom"),
        requests_lib.ConnectionError("boom"),
        FakeResponse({"msg": "success"}),
    ]

    manager._send_now(WEBHOOK, SECRET, "瞬时网络异常")
    assert post.call_count == 3
    assert WEBHOOK not in manager._circuits
