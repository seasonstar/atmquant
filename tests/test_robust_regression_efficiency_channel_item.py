"""稳健回归效率通道主图测试。"""

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
import pytest

from core.charts.enhanced_chart_widget import EXTENDED_INDICATORS_CONFIG
from core.indicators.robust_regression_efficiency_channel_item import (
    RobustRegressionEfficiencyChannelItem,
)
from vnpy.chart.manager import BarManager
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.trader.ui import QtWidgets


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make_bars(count: int = 50):
    rng = np.random.default_rng(23)
    closes = 100 + np.cumsum(rng.normal(0, 1, count))
    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    return [
        BarData(
            symbol="rb2701",
            exchange=Exchange.SHFE,
            datetime=start + timedelta(minutes=15 * i),
            interval=Interval.MINUTE,
            open_price=float(close - 0.2),
            high_price=float(close + 1),
            low_price=float(close - 1),
            close_price=float(close),
            volume=100,
            gateway_name="TEST",
        )
        for i, close in enumerate(closes)
    ]


def make_item(app, window=20):
    bars = make_bars()
    manager = BarManager()
    manager.update_history(bars)
    item = RobustRegressionEfficiencyChannelItem(manager, window=window)
    item.update_history(bars)
    return item, bars


def test_indicator_has_independent_main_chart_registration() -> None:
    """独立指标使用自己的注册键和主图配置。"""
    config = EXTENDED_INDICATORS_CONFIG["robust_regression_efficiency_channel"]

    assert config["type"] == "main"
    assert config["default_visible"] is False
    assert config["configurable"] is True


def test_shared_states_hud_and_visible_range(app) -> None:
    """主图共享稳健拟合状态，HUD显示斜率、ER和ATR。"""
    item, bars = make_item(app)

    assert len(item.calculator.states) == len(bars)
    assert "Efficiency Ratio" in item.get_hud_html()
    assert "ATR" in item.get_hud_html()
    assert item.get_current_values()["slope"] == item.calculator.states[-1].slope
    low, high = item.get_y_range(20, 50)
    valid = [s for s in item.calculator.states[20:50] if s.is_valid]
    assert low <= min(s.lower_band for s in valid)
    assert high >= max(s.upper_band for s in valid)


def test_configuration_recalculates_and_hud_follows_visibility(app) -> None:
    """修改窗口与ER后全量重算，HUD开关控制真实Plot可见性。"""
    item, bars = make_item(app)
    plot = pg.PlotWidget()
    item.attach_hud(plot.getPlotItem())

    item.apply_config({"window": 30, "deviation_factor": 1.5, "er_threshold": 0.4, "show_hud": False})

    assert item.calculator.window == 30
    assert item.calculator.deviation_factor == 1.5
    assert item.calculator.er_threshold == 0.4
    assert len(item.calculator.states) == len(bars)
    assert not item.hud_item.isVisible()
    plot.deleteLater()


def test_hud_can_move_to_top_left(app) -> None:
    """展示最新突破K线时，HUD可移动到左上避免遮挡右侧价格。"""
    item, _ = make_item(app)
    plot = pg.PlotWidget()
    item.attach_hud(plot.getPlotItem())
    (x_min, x_max), _ = plot.getPlotItem().getViewBox().viewRange()

    item.hud_position = "top_left"
    item._position_hud()

    assert item.hud_item.pos().x() < (x_min + x_max) / 2
    plot.deleteLater()
