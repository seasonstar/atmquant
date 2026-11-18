"""逻辑回归方向CTA执行测试。"""

from types import SimpleNamespace

from core.strategies.logistic_direction_strategy import LogisticDirectionStrategy


class FakeCalculator:
    def __init__(self, prob_up):
        self.state = SimpleNamespace(
            prob_up=prob_up,
            model_ready=prob_up is not None,
            train_count=1 if prob_up is not None else 0,
        )

    def update(self, bar):
        return self.state


def make_strategy(prob_up, position: int, threshold: float = 0.05, max_size: int = 2):
    strategy = LogisticDirectionStrategy.__new__(LogisticDirectionStrategy)
    strategy.calculator = FakeCalculator(prob_up)
    strategy.pos = position
    strategy.prob_threshold = threshold
    strategy.max_size = max_size
    strategy.prob_up = 0.0
    strategy.target_pos = 0
    strategy.model_ready = False
    strategy.train_count = 0
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


def test_neutral_probability_stays_flat() -> None:
    """概率落在阈值内不开仓。"""
    strategy = make_strategy(0.54, 0)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 0
    assert strategy.orders == []


def test_probability_none_does_nothing() -> None:
    """模型未就绪时不产生任何委托。"""
    strategy = make_strategy(None, 0)
    strategy.on_15min_bar(make_bar())
    assert strategy.orders == []
    assert strategy.first_signal_datetime is None


def test_strong_probability_takes_max_size() -> None:
    """偏离超过两倍阈值直接满仓 max_size。"""
    strategy = make_strategy(0.62, 0)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 2
    assert strategy.orders == [("buy", 3000.0 * 1.1, 2)]


def test_moderate_probability_takes_one_lot() -> None:
    """偏离超过阈值但不足两倍只开 1 手。"""
    strategy = make_strategy(0.58, 0)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 1
    assert strategy.orders == [("buy", 3000.0 * 1.1, 1)]


def test_short_side_symmetry() -> None:
    """空头方向与多头对称。"""
    strategy = make_strategy(0.38, 0)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == -2
    assert strategy.orders == [("sell", 3000.0 * 0.9, 2)]


def test_reversal_trades_full_delta() -> None:
    """从多 1 手翻空 2 手只下一笔 3 手卖单。"""
    strategy = make_strategy(0.36, 1)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == -2
    assert strategy.orders == [("sell", 3000.0 * 0.9, 3)]


def test_same_target_no_order() -> None:
    """目标仓位与持仓一致时不重复下单。"""
    strategy = make_strategy(0.58, 1)
    strategy.on_15min_bar(make_bar())
    assert strategy.orders == []


def test_probability_fallback_to_flat() -> None:
    """概率回落到中性区间时平仓。"""
    strategy = make_strategy(0.52, 2)
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 0
    assert strategy.orders == [("sell", 3000.0 * 0.9, 2)]


def test_warmup_replay_only_trains_no_orders() -> None:
    """trading 未开启时（预热回放/实盘启动）只更新模型不下单。"""
    strategy = make_strategy(0.62, 0)
    strategy.trading = False
    strategy.on_15min_bar(make_bar())
    assert strategy.target_pos == 2
    assert strategy.orders == []
