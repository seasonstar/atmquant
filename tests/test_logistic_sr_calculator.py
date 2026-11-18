"""逻辑回归支撑阻力计算器 Pine 语义对照测试。"""

from types import SimpleNamespace

import numpy as np
import pytest

from core.indicators.calculators.logistic_sr_calculator import (
    LEARNING_RATE,
    LogisticSrCalculator,
    SrLine,
    _loss,
    _sigmoid,
)


def make_bar(open_p, high, low, close):
    return SimpleNamespace(
        open_price=float(open_p),
        high_price=float(high),
        low_price=float(low),
        close_price=float(close),
    )


def make_trend_bars(n: int, start: float = 3000.0, drift: float = 1.0, seed: int = 5):
    """带枢轴的震荡序列：正弦 + 趋势，保证产生 pivot。"""
    rng = np.random.default_rng(seed)
    bars = []
    for i in range(n):
        close = start + drift * i + 8 * np.sin(i / 3.0) + rng.normal(0, 0.5)
        open_p = close - rng.normal(0, 0.8)
        high = max(open_p, close) + abs(rng.normal(0, 1.2))
        low = min(open_p, close) - abs(rng.normal(0, 1.2))
        bars.append(make_bar(open_p, high, low, close))
    return bars


def test_loss_matches_original_formula() -> None:
    """±1 标签的自定义损失：y=1 为 -log(p)，y=-1 为 log(p)-2log(1-p)。"""
    p = 0.6
    assert _loss(1.0, p) == pytest.approx(-np.log(p))
    assert _loss(-1.0, p) == pytest.approx(np.log(p) - 2 * np.log(1 - p))


def test_predict_single_pass_matches_hand_calculation() -> None:
    """单趟在线更新：手工推两个样本后的最终输出。"""
    calc = LogisticSrCalculator(pivot_length=2, target_respects=2)
    # 手工注入两个同侧历史枢轴
    calc.all_pivots.append(SrLine(
        is_support=True, level=100.0, start_index=0, confirm_index=1,
        detected_rsi=1, detected_body=1, times_respected=2,  # 已达标 -> y=+1
    ))
    calc.all_pivots.append(SrLine(
        is_support=True, level=101.0, start_index=2, confirm_index=3,
        detected_rsi=-1, detected_body=1, times_respected=0,  # 未达标 -> y=-1
    ))

    base, rsi_b, body_b = 1.0, 1.0, 1.0
    # 样本1: y=+1, x=(+1,+1)
    p1 = _sigmoid(base + rsi_b * 1 + body_b * 1)
    loss1 = _loss(1.0, p1)
    rsi_b -= LEARNING_RATE * (p1 + loss1) * 1
    body_b -= LEARNING_RATE * (p1 + loss1) * 1
    expected = _sigmoid(base + rsi_b * 1 + body_b * 1)
    # 样本2: y=-1, x=(-1,+1)
    p2 = _sigmoid(base + rsi_b * (-1) + body_b * 1)
    loss2 = _loss(-1.0, p2)
    rsi_b -= LEARNING_RATE * (p2 + loss2) * (-1)
    body_b -= LEARNING_RATE * (p2 + loss2) * 1
    expected = _sigmoid(base + rsi_b * 1 + body_b * 1)

    assert calc._predict(True, 1, 1) == pytest.approx(expected)


def test_predict_without_history_returns_zero() -> None:
    calc = LogisticSrCalculator()
    assert calc._predict(True, 1, 1) == 0.0


def test_pivot_confirmation_waits_right_side() -> None:
    """右侧K线未齐时不确认枢轴。"""
    calc = LogisticSrCalculator(pivot_length=3)
    # 构造一个明显的枢轴高点：中间最高
    seq = [10, 11, 12, 13, 12, 11, 10, 9, 8]
    for i, c in enumerate(seq):
        calc.update(make_bar(c, c + 0.5, c - 0.5, c))
        if i < 3 + 3:
            assert len(calc.all_pivots) == 0
    assert len(calc.all_pivots) == 1
    pivot = calc.all_pivots[0]
    assert pivot.is_support is False
    assert pivot.level == pytest.approx(13.5)


def test_respect_counts_every_touching_bar_and_ends_on_close_beyond() -> None:
    """支撑线：low 刺破但收回即尊重+1（每根都计），收破即终点。"""
    calc = LogisticSrCalculator(pivot_length=2, target_respects=2, probability_threshold=0.0001)
    # 先喂 6 根平稳K线，让后续索引避开 latest_retest_index=0 的初始冷却
    for _ in range(6):
        calc.update(make_bar(100, 100.5, 99.5, 100.0))
    level = SrLine(
        is_support=True, level=98.0, start_index=2, confirm_index=5,
        detected_rsi=1, detected_body=1, by_regression=True,
    )
    calc.all_pivots.append(level)

    # 第1根：low 97.5 刺破、close 101 收回 -> 尊重 1 + 回测事件
    state = calc.update(make_bar(100, 101.5, 97.5, 101.0))
    assert level.times_respected == 1
    assert level.end_index is None
    assert any(e.kind == "retest" for e in state.events)
    # 第2根：再刺破收回 -> 尊重 2 -> respected 达标
    calc.update(make_bar(101, 102.0, 97.6, 101.5))
    assert level.times_respected == 2
    assert level.respected is True
    # 第3根：收破 97 -> 终点 + break 事件
    state = calc.update(make_bar(101, 101.2, 96.5, 97.0))
    assert level.end_index is not None
    assert any(e.kind == "break" for e in state.events)
    # 第4根：已终点不再跟踪
    calc.update(make_bar(97, 97.5, 95.0, 96.0))
    assert level.times_respected == 2


def test_retest_label_respects_cooldown() -> None:
    """回测事件受 3 根K线冷却期约束，但尊重计数不受限。"""
    calc = LogisticSrCalculator(pivot_length=2, retest_cooldown=3, probability_threshold=0.0001)
    for _ in range(6):
        calc.update(make_bar(100, 100.5, 99.5, 100.0))
    level = SrLine(
        is_support=True, level=98.0, start_index=2, confirm_index=5,
        detected_rsi=1, detected_body=1, by_regression=True,
    )
    calc.all_pivots.append(level)

    retest_events = 0
    for o, h, l, c in [
        (100, 101, 97.5, 100.5),
        (100.5, 101, 97.6, 100.6),
        (100.6, 101, 97.7, 100.7),
    ]:
        state = calc.update(make_bar(o, h, l, c))
        retest_events += sum(1 for e in state.events if e.kind == "retest")

    assert level.times_respected == 3       # 计数不受冷却影响
    assert retest_events == 1               # 标签只在第一次触发（后续处于冷却期）


def test_no_lookahead_prefix_matches_full() -> None:
    bars = make_trend_bars(300)
    cut = 200
    calc_a = LogisticSrCalculator()
    for b in bars[:cut]:
        calc_a.update(b)
    calc_b = LogisticSrCalculator()
    for b in bars:
        calc_b.update(b)

    assert len(calc_a.all_pivots) == len(calc_b.all_pivots[:len(calc_a.all_pivots)])
    for a, b in zip(calc_a.all_pivots, calc_b.all_pivots):
        assert a.level == pytest.approx(b.level)
        assert a.prediction == pytest.approx(b.prediction)
        assert a.times_respected == b.times_respected


def test_full_run_produces_levels_and_events() -> None:
    """完整跑一段震荡序列，应产生画线水平与事件。"""
    calc = LogisticSrCalculator(pivot_length=3, probability_threshold=0.5)
    for b in make_trend_bars(400):
        calc.update(b)

    regression = calc.regression_lines()
    assert len(calc.all_pivots) > 5
    assert len(regression) >= 1
    assert all(0.0 <= sr.prediction <= 1.0 for sr in calc.all_pivots)
    assert calc.states[-1].support_pivots + calc.states[-1].resistance_pivots == len(calc.all_pivots)
