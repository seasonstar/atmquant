# -*- coding: utf-8 -*-
"""Bayesian Q 六模型的一小时 CTA 执行与审计测试。"""

from datetime import datetime, timedelta, timezone
import math

import pytest

from core.indicators.calculators.bayesian_bbsma_calculator import BayesianBbsmaState
from core.indicators.calculators.bayesian_q_calculator import (
    MODEL_NAMES,
    BayesianQState,
)
from core.indicators.calculators.nqqe_calculator import NqqeState
from core.strategies.base_strategy import BaseCtaStrategy
from core.strategies.bayesian_q_strategy import BayesianQStrategy
from vnpy.trader.constant import Direction, Exchange, Interval, Offset
from vnpy.trader.object import BarData


START = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


class RecordingEngine:
    """在真实 CtaTemplate 下单边界记录订单，不替换策略执行方法。"""

    def __init__(self):
        self.orders = []
        self.cancel_all_calls = 0

    def send_order(
        self,
        strategy,
        direction,
        offset,
        price,
        volume,
        stop,
        lock,
        net,
    ):
        order = {
            "direction": direction,
            "offset": offset,
            "price": price,
            "volume": volume,
            "stop": stop,
            "lock": lock,
            "net": net,
        }
        self.orders.append(order)
        return [str(len(self.orders))]

    def cancel_all(self, strategy):
        self.cancel_all_calls += 1


class StubCalculator:
    """按小时 update 顺序返回完整手造状态。"""

    def __init__(self, *states):
        self.states = list(states)
        self.calls = []

    def update(self, bar):
        self.calls.append(bar)
        if len(self.calls) > len(self.states):
            raise AssertionError("calculator received more updates than expected")
        return self.states[len(self.calls) - 1]


def make_bar(dt, close=100.0, interval=Interval.HOUR):
    return BarData(
        symbol="rb2510",
        exchange=Exchange.SHFE,
        datetime=dt,
        interval=interval,
        gateway_name="TEST",
        open_price=close - 0.5,
        high_price=close + 1.0,
        low_price=close - 1.0,
        close_price=close,
        volume=10.0,
        turnover=1000.0,
        open_interest=20.0,
    )


def make_state(
    model,
    event,
    *,
    bayes_ready=True,
    nqqe_ready=True,
    sma=100.0,
):
    signals = {name: 0 for name in MODEL_NAMES}
    signals[model] = event
    bayes = BayesianBbsmaState(
        sma=sma,
        basis=sma,
        upper=sma + 5.0,
        sigma_up_legacy=0.8,
        sigma_down_legacy=0.2,
        prime_legacy=0.7,
        sigma_up_fixed=0.75,
        sigma_down_fixed=0.25,
        prime_fixed=0.65,
        ready=bayes_ready,
    )
    nqqe = NqqeState(
        rsi=65.0,
        qqef=64.0,
        qqes=60.0,
        crossover=event == 1,
        crossunder=event == -1,
        trend="up" if event == 1 else "down" if event == -1 else "neutral",
        ready=nqqe_ready,
    )
    return BayesianQState(bayes=bayes, nqqe=nqqe, signals=signals)


def make_strategy(monkeypatch, model="bayes_q_fixed", trading=True):
    # 参数文件是外部副作用；执行测试显式传入冻结参数，其余构造与下单路径保持真实。
    monkeypatch.setattr(
        BaseCtaStrategy,
        "_fill_optimized_params",
        lambda self, setting, vt_symbol: None,
    )
    engine = RecordingEngine()
    strategy = BayesianQStrategy(
        engine,
        "bayesian_q_test",
        "rb2510.SHFE",
        {"model": model, "fixed_size": 1},
    )
    strategy.trading = trading
    return strategy, engine


@pytest.mark.parametrize("model", MODEL_NAMES)
def test_each_model_opens_one_lot_long_from_flat(monkeypatch, model):
    strategy, engine = make_strategy(monkeypatch, model)
    calculator = StubCalculator(make_state(model, 1))
    strategy.calculator = calculator
    bar = make_bar(START, close=101.0)

    strategy.on_60min_bar(bar)

    assert engine.cancel_all_calls == 1
    assert engine.orders == [
        {
            "direction": Direction.LONG,
            "offset": Offset.OPEN,
            "price": 101.0,
            "volume": 1,
            "stop": False,
            "lock": False,
            "net": False,
        }
    ]
    assert calculator.calls == [bar]
    assert strategy.signal == 1
    assert strategy.target_pos == 1
    assert strategy.first_signal_datetime == START


@pytest.mark.parametrize("model", MODEL_NAMES)
def test_each_model_opens_one_lot_short_from_flat_with_sell(monkeypatch, model):
    strategy, engine = make_strategy(monkeypatch, model)
    strategy.calculator = StubCalculator(make_state(model, -1))
    bar = make_bar(START, close=99.0)

    strategy.on_60min_bar(bar)

    assert len(engine.orders) == 1
    order = engine.orders[0]
    assert order["direction"] == Direction.SHORT
    assert order["offset"] == Offset.CLOSE
    assert order["price"] == 99.0
    assert order["volume"] == 1
    assert order["stop"] is False
    assert strategy.signal == -1
    assert strategy.target_pos == -1


@pytest.mark.parametrize("model", MODEL_NAMES)
def test_each_model_reverses_long_to_short_with_one_delta_sell(monkeypatch, model):
    strategy, engine = make_strategy(monkeypatch, model)
    strategy.pos = 1
    strategy.calculator = StubCalculator(make_state(model, -1))

    strategy.on_60min_bar(make_bar(START, close=98.0))

    assert len(engine.orders) == 1
    order = engine.orders[0]
    assert order["direction"] == Direction.SHORT
    assert order["offset"] == Offset.CLOSE
    assert order["volume"] == 2
    assert order["price"] == 98.0
    assert strategy.target_pos == -1


@pytest.mark.parametrize("model", MODEL_NAMES)
def test_zero_event_keeps_current_position_without_order(monkeypatch, model):
    strategy, engine = make_strategy(monkeypatch, model)
    strategy.pos = 1
    strategy.calculator = StubCalculator(make_state(model, 0))

    strategy.on_60min_bar(make_bar(START))

    assert engine.orders == []
    assert strategy.signal == 0
    assert strategy.target_pos == 1
    assert strategy.first_signal_datetime is None


@pytest.mark.parametrize("model", MODEL_NAMES)
def test_unready_selected_model_does_not_trade(monkeypatch, model):
    strategy, engine = make_strategy(monkeypatch, model)
    state = make_state(
        model,
        1,
        bayes_ready=False,
        nqqe_ready=False,
        sma=math.nan,
    )
    strategy.calculator = StubCalculator(state)

    strategy.on_60min_bar(make_bar(START, close=101.0))

    assert engine.orders == []
    assert strategy.signal == 0
    assert strategy.target_pos == 0
    assert strategy.first_signal_datetime is None


def test_sma_momentum_needs_only_valid_sma_not_other_model_readiness(monkeypatch):
    strategy, engine = make_strategy(monkeypatch, "sma_momentum")
    state = make_state(
        "sma_momentum",
        1,
        bayes_ready=False,
        nqqe_ready=False,
        sma=100.0,
    )
    strategy.calculator = StubCalculator(state)

    strategy.on_60min_bar(make_bar(START, close=101.0))

    assert len(engine.orders) == 1
    assert engine.orders[0]["direction"] == Direction.LONG
    assert strategy.target_pos == 1


def test_warmup_replay_never_sends_or_cancels_orders(monkeypatch):
    strategy, engine = make_strategy(monkeypatch, trading=False)
    strategy.calculator = StubCalculator(make_state("bayes_q_fixed", 1))

    strategy.on_60min_bar(make_bar(START, close=101.0))
    strategy.on_stop()

    assert engine.orders == []
    assert engine.cancel_all_calls == 0


def test_one_minute_bars_emit_signal_only_when_hour_is_complete(monkeypatch):
    strategy, engine = make_strategy(monkeypatch, "bayes_q_fixed")
    calculator = StubCalculator(make_state("bayes_q_fixed", 1))
    strategy.calculator = calculator
    bars = [
        make_bar(
            START + timedelta(minutes=index),
            close=100.0 + index / 10.0,
            interval=Interval.MINUTE,
        )
        for index in range(60)
    ]

    for bar in bars[:59]:
        strategy.on_bar(bar)
    assert engine.orders == []
    assert calculator.calls == []

    strategy.on_bar(bars[-1])

    assert len(calculator.calls) == 1
    assert calculator.calls[0].datetime == START
    assert calculator.calls[0].close_price == pytest.approx(105.9)
    assert len(engine.orders) == 1
    assert strategy.last_bar_datetime == bars[-1].datetime
    assert strategy.first_signal_datetime == START
    assert strategy.audit_records[0]["datetime"] == START


def test_audit_record_contains_all_events_and_formula_values(monkeypatch):
    strategy, engine = make_strategy(monkeypatch, "nqqe")
    events = {
        "bayes_legacy": 1,
        "bayes_fixed": -1,
        "nqqe": 1,
        "bayes_q_legacy": 0,
        "bayes_q_fixed": 1,
        "sma_momentum": -1,
    }
    bayes = BayesianBbsmaState(
        sma=101.0,
        basis=102.0,
        upper=110.0,
        sigma_up_legacy=0.81,
        sigma_down_legacy=0.19,
        prime_legacy=0.71,
        sigma_up_fixed=0.82,
        sigma_down_fixed=0.18,
        prime_fixed=0.72,
        ready=True,
    )
    nqqe = NqqeState(
        rsi=66.0,
        qqef=65.0,
        qqes=61.0,
        crossover=True,
        trend="up",
        ready=True,
    )
    first_state = BayesianQState(bayes=bayes, nqqe=nqqe, signals=events)
    second_state = make_state("nqqe", 0)
    strategy.calculator = StubCalculator(first_state, second_state)

    strategy.on_60min_bar(make_bar(START, close=103.0))
    strategy.on_60min_bar(make_bar(START + timedelta(hours=1), close=104.0))

    record = strategy.audit_records[0]
    assert record["datetime"] == START
    assert record["model"] == "nqqe"
    assert {name: record[name] for name in MODEL_NAMES} == events
    assert record["sma"] == 101.0
    assert record["basis"] == 102.0
    assert record["upper"] == 110.0
    assert record["sigma_up_legacy"] == 0.81
    assert record["sigma_down_legacy"] == 0.19
    assert record["prime_legacy"] == 0.71
    assert record["sigma_up_fixed"] == 0.82
    assert record["sigma_down_fixed"] == 0.18
    assert record["prime_fixed"] == 0.72
    assert record["rsi"] == 66.0
    assert record["qqef"] == 65.0
    assert record["qqes"] == 61.0
    assert record["bayes_ready"] is True
    assert record["nqqe_ready"] is True
    assert record["signal"] == 1
    assert record["target_pos"] == 1
    assert record["pos"] == 0
    assert record["close_price"] == 103.0
    assert strategy.first_signal_datetime == START


def test_unknown_model_is_rejected(monkeypatch):
    with pytest.raises(ValueError):
        make_strategy(monkeypatch, "not_a_model")
