"""capissimo ML 逻辑回归CTA执行测试。"""

from types import SimpleNamespace

from core.strategies.capissimo_logistic_strategy import CapissimoLogisticStrategy


class FakeCalculator:
    def __init__(self, state):
        self.state = state

    def update(self, bar):
        return self.state


def make_state(start_long=False, start_short=False, end_long=False, end_short=False, signal=0):
    return SimpleNamespace(
        start_long=start_long,
        start_short=start_short,
        end_long=end_long,
        end_short=end_short,
        signal=signal,
        loss=0.0,
        scaled_loss=100.0,
    )


def make_strategy(state, position: int):
    strategy = CapissimoLogisticStrategy.__new__(CapissimoLogisticStrategy)
    strategy.calculator = FakeCalculator(state)
    strategy.pos = position
    strategy.fixed_size = 1
    strategy.signal = 0
    strategy.loss = 0.0
    strategy.scaled_loss = 0.0
    strategy.target_pos = 0
    strategy.first_signal_datetime = None
    strategy.trading = True
    strategy.orders = []
    strategy.cancel_all = lambda: None
    strategy.buy = lambda price, volume: strategy.orders.append(("buy", price, volume))
    strategy.sell = lambda price, volume: strategy.orders.append(("sell", price, volume))
    return strategy


def make_bar(close: float = 3000.0):
    return SimpleNamespace(
        close_price=close,
        high_price=close * 1.001,
        low_price=close * 0.999,
        volume=1000.0,
        datetime=None,
    )


def test_start_long_buys_one_lot() -> None:
    strategy = make_strategy(make_state(start_long=True, signal=1), 0)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 1
    assert strategy.orders == [("buy", 3000.0 * 1.1, 1)]


def test_start_short_sells_one_lot() -> None:
    strategy = make_strategy(make_state(start_short=True, signal=-1), 0)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == -1
    assert strategy.orders == [("sell", 3000.0 * 0.9, 1)]


def test_flip_long_to_short_single_delta_order() -> None:
    """多翻空同一根K线只下一笔差额单。"""
    strategy = make_strategy(make_state(start_short=True, end_long=True, signal=-1), 1)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == -1
    assert strategy.orders == [("sell", 3000.0 * 0.9, 2)]


def test_holding_period_exit_flattens() -> None:
    strategy = make_strategy(make_state(end_long=True, signal=1), 1)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 0
    assert strategy.orders == [("sell", 3000.0 * 0.9, 1)]


def test_no_state_change_keeps_position() -> None:
    strategy = make_strategy(make_state(signal=1), 1)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 1
    assert strategy.orders == []


def test_warmup_replay_no_orders() -> None:
    strategy = make_strategy(make_state(start_long=True, signal=1), 0)
    strategy.trading = False
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 1
    assert strategy.orders == []
