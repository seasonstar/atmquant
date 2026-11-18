"""随机森林方向CTA执行测试（日线）。"""

from types import SimpleNamespace

from core.strategies.random_forest_direction_strategy import (
    RandomForestDirectionStrategy,
)


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
    strategy = RandomForestDirectionStrategy.__new__(RandomForestDirectionStrategy)
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
        volume=100000.0,
        datetime=None,
    )


def test_neutral_probability_stays_flat() -> None:
    """概率落在阈值内不开仓。"""
    strategy = make_strategy(0.54, 0)
    strategy.on_bar(make_bar())
    assert strategy.target_pos == 0
    assert strategy.orders == []


def test_probability_none_does_nothing() -> None:
    """模型未就绪时不产生任何委托。"""
    strategy = make_strategy(None, 0)
    strategy.on_bar(make_bar())
    assert strategy.orders == []
    assert strategy.first_signal_datetime is None


def test_strong_probability_takes_max_size() -> None:
    """偏离超过两倍阈值直接满仓 max_size。"""
    strategy = make_strategy(0.62, 0)
    strategy.on_bar(make_bar())
    assert strategy.target_pos == 2
    assert strategy.orders == [("buy", 3000.0 * 1.1, 2)]


def test_moderate_probability_takes_one_lot() -> None:
    """偏离超过阈值但不足两倍只开 1 手。"""
    strategy = make_strategy(0.58, 0)
    strategy.on_bar(make_bar())
    assert strategy.target_pos == 1
    assert strategy.orders == [("buy", 3000.0 * 1.1, 1)]


def test_short_side_mirrors_long() -> None:
    strategy = make_strategy(0.38, 0)
    strategy.on_bar(make_bar())
    assert strategy.target_pos == -2
    assert strategy.orders == [("sell", 3000.0 * 0.9, 2)]


def test_position_reduced_toward_target() -> None:
    """持多 2 手、概率回到中性时全平。"""
    strategy = make_strategy(0.51, 2)
    strategy.on_bar(make_bar())
    assert strategy.target_pos == 0
    assert strategy.orders == [("sell", 3000.0 * 0.9, 2)]


def test_warmup_not_trading_places_no_orders() -> None:
    """预热回放（trading=False）只训练不下单。"""
    strategy = make_strategy(0.70, 0)
    strategy.trading = False
    strategy.on_bar(make_bar())
    assert strategy.target_pos == 2  # 目标仓位仍被记录
    assert strategy.orders == []


def test_model_kind_parameter_registered() -> None:
    """model_kind 必须在参数清单里（A/B 由参数驱动）。"""
    assert "model_kind" in RandomForestDirectionStrategy.parameters
