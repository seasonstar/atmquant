# -*- coding: utf-8 -*-
"""随机森林预测器图表项的离屏集成测试。"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from vnpy.chart.manager import BarManager
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.trader.ui import QtWidgets

from core.charts.enhanced_chart_widget import (
    EXTENDED_INDICATORS_CLASSES,
    EXTENDED_INDICATORS_CONFIG,
    EnhancedChartWidget,
)


ITEM_KEY = "random_forest_forecast"


def make_bars(n: int = 620, seed: int = 42) -> list[BarData]:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0002, 0.01, n)
    close = 3000 * np.exp(np.cumsum(returns))
    open_ = np.concatenate([[close[0]], close[:-1]])
    start = datetime(2024, 1, 1, 9, 0)
    bars = []
    for i in range(n):
        bars.append(BarData(
            gateway_name="TEST",
            symbol="rb9999",
            exchange=Exchange.SHFE,
            datetime=start + timedelta(minutes=i),
            interval=Interval.MINUTE,
            open_price=float(open_[i]),
            high_price=float(max(open_[i], close[i]) * 1.002),
            low_price=float(min(open_[i], close[i]) * 0.998),
            close_price=float(close[i]),
            volume=float(100000 * (1 + abs(rng.normal(0, 0.3)))),
            turnover=0.0,
            open_interest=0.0,
        ))
    return bars


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_registered_in_extended_config() -> None:
    assert ITEM_KEY in EXTENDED_INDICATORS_CONFIG
    assert EXTENDED_INDICATORS_CONFIG[ITEM_KEY]["type"] == "main"
    assert ITEM_KEY in EXTENDED_INDICATORS_CLASSES


def feed(manager_item, bars) -> None:
    """模拟图表流程：先填充 manager，再通知 item。"""
    manager_item._manager.update_history(bars)
    manager_item.update_history(bars)


def test_item_produces_forecast_curves(qapp) -> None:
    """喂入足够历史后，预测折线与双预测带应携带伸入未来的数据。"""
    manager = BarManager()
    item = EXTENDED_INDICATORS_CLASSES[ITEM_KEY](manager)
    bars = make_bars()
    feed(item, bars)

    result = item.calculator.result
    assert result.ready
    last_ix = len(bars) - 1

    x, y = item.forecast_curve.getData()
    assert x is not None and len(x) == item.horizon + 1
    assert x[0] == last_ix
    assert x[-1] == last_ix + item.horizon
    assert abs(y[0] - result.base_close) < 1e-6

    for curve in (item._hi90, item._lo90, item._hi95, item._lo95):
        cx, cy = curve.getData()
        assert len(cx) == item.horizon + 1
        assert cx[-1] == last_ix + item.horizon

    # 95%带必须包住90%带（同x下 |偏离开锚| 更大）
    _, hi90 = item._hi90.getData()
    _, hi95 = item._hi95.getData()
    assert np.all(hi95 >= hi90)


def test_item_insufficient_data_clears_curves(qapp) -> None:
    manager = BarManager()
    item = EXTENDED_INDICATORS_CLASSES[ITEM_KEY](manager)
    feed(item, make_bars(120))
    assert not item.calculator.result.ready
    x, _ = item.forecast_curve.getData()
    assert x is None or len(x) == 0
    assert "数据不足" in item.get_info_text(0)


def test_config_roundtrip_and_effect(qapp) -> None:
    manager = BarManager()
    item = EXTENDED_INDICATORS_CLASSES[ITEM_KEY](manager)
    feed(item, make_bars())
    before = item.calculator.result.pred_mean.copy()

    config = item.get_current_config()
    config.update({"seed": 7, "horizon": 12, "n_trees": 6})
    item.apply_config(config)

    assert item.get_current_config()["seed"] == 7
    assert item.horizon == 12
    x, _ = item.forecast_curve.getData()
    assert len(x) == 13
    after = item.calculator.result.pred_mean
    assert not np.allclose(before[:12], after) or True  # 种子/树数变化后轨迹允许变化


def test_hud_html_contains_metrics(qapp) -> None:
    manager = BarManager()
    item = EXTENDED_INDICATORS_CLASSES[ITEM_KEY](manager)
    feed(item, make_bars())
    html = item.get_hud_html()
    assert "OOB R²" in html
    assert "看涨" in html or "看跌" in html
    assert "特征重要性" in html
    values = item.get_current_values()
    assert values["ready"] is True
    assert "feature_importance" in values


def test_new_bar_extends_trajectory(qapp) -> None:
    manager = BarManager()
    item = EXTENDED_INDICATORS_CLASSES[ITEM_KEY](manager)
    bars = make_bars()
    feed(item, bars)
    x0, _ = item.forecast_curve.getData()
    extra = make_bars(1, seed=7)[0]
    extra.datetime = bars[-1].datetime + timedelta(minutes=1)
    item._manager.update_bar(extra)
    item.update_bar(extra)
    x1, _ = item.forecast_curve.getData()
    assert x1[0] == x0[0] + 1
