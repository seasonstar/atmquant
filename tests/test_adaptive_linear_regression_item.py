"""自适应线性回归主图指标测试。"""

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
import pytest

from core.charts.enhanced_chart_widget import EXTENDED_INDICATORS_CONFIG
from core.indicators.adaptive_linear_regression_item import AdaptiveLinearRegressionItem
from core.indicators.calculators.adaptive_linear_regression_calculator import (
    RegressionSignal,
    fit_ols,
)
from vnpy.chart.manager import BarManager
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.trader.ui import QtWidgets


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


def make_bars(count: int = 40):
    rng = np.random.default_rng(11)
    closes = 100 + np.cumsum(rng.normal(0, 1, count))
    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    bars = []
    for i, close in enumerate(closes):
        bars.append(BarData(
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
        ))
    return bars


def test_indicator_is_registered_as_configurable_main_chart() -> None:
    """扩展注册表应提供默认关闭的主图自适应回归指标。"""
    config = EXTENDED_INDICATORS_CONFIG["adaptive_linear_regression"]

    assert config["type"] == "main"
    assert config["default_visible"] is False
    assert config["configurable"] is True


def test_indicator_uses_shared_states_and_exposes_hud(app) -> None:
    """图表直接呈现共享模型状态，并提供R²、方向和Duration。"""
    bars = make_bars()
    manager = BarManager()
    manager.update_history(bars)
    item = AdaptiveLinearRegressionItem(manager, quality_threshold=0.0)
    item.update_history(bars)

    assert len(item.calculator.states) == len(bars)
    assert item.get_current_config()["scan_horizon"] == 20
    assert "Model Quality" in item.get_hud_html()
    assert item.get_current_values()["duration"] == item.calculator.states[-1].model.duration
    low, high = item.get_y_range()
    assert low <= high
    assert item.boundingRect().width() >= len(bars)


def test_configuration_recalculates_without_changing_state_count(app) -> None:
    """修改参数后使用相同K线重算，不能丢失状态或沿用旧缓存。"""
    bars = make_bars()
    manager = BarManager()
    manager.update_history(bars)
    item = AdaptiveLinearRegressionItem(manager)
    item.update_history(bars)

    item.apply_config({
        "scan_horizon": 10,
        "deviation_factor": 1.5,
        "structural_sensitivity": 3,
        "quality_threshold": 0.25,
        "show_hud": False,
    })

    assert item.calculator.scan_horizon == 10
    assert item.calculator.deviation_factor == 1.5
    assert item.calculator.structural_sensitivity == 3
    assert item.calculator.quality_threshold == 0.25
    assert len(item.calculator.states) == len(bars)
    assert not item.show_hud


def test_hud_attaches_to_real_plot_and_follows_visibility(app) -> None:
    """HUD必须能附着到真实Plot，并随指标和配置控制可见性。"""
    bars = make_bars()
    manager = BarManager()
    manager.update_history(bars)
    item = AdaptiveLinearRegressionItem(manager, quality_threshold=0.0)
    item.update_history(bars)
    plot = pg.PlotWidget()

    item.attach_hud(plot.getPlotItem())

    assert item.hud_item.isVisible()
    assert "Model Quality" in item.hud_item.toPlainText()
    item.apply_config({"show_hud": False})
    assert not item.hud_item.isVisible()
    plot.close()


def test_visible_y_range_excludes_offscreen_channel_origin(app) -> None:
    """屏幕外的通道起点不能把当前可视区Y轴拉向旧价格。"""
    bars = make_bars()
    manager = BarManager()
    manager.update_history(bars)
    item = AdaptiveLinearRegressionItem(manager)
    item.update_history(bars)
    state = item.calculator.states[-1]
    model = replace(
        fit_ols([10, 11, 13, 12, 15]),
        alpha_offset=50,
        beta_slope=1,
        std_deviation=1,
        origin_idx=0,
        duration=39,
        is_valid=True,
    )
    item.calculator.states[-1] = replace(state, model=model)

    low, high = item.get_y_range(30, 39)

    assert low == pytest.approx(78)
    assert high == pytest.approx(max(bar.high_price for bar in bars[30:40]))


def test_rebuilding_labels_removes_old_scene_items(app) -> None:
    """重复重算标签时Scene中只能保留一套文本，不能叠字。"""
    bars = make_bars()
    manager = BarManager()
    manager.update_history(bars)
    item = AdaptiveLinearRegressionItem(manager)
    plot = pg.PlotWidget()
    plot.addItem(item)
    item.calculator.compute(bars)
    state = item.calculator.states[-1]
    item.calculator.states[-1] = replace(
        state,
        signal=RegressionSignal(1, state.close, state.close + 2, state.close - 2),
    )

    item._rebuild_labels()
    first_count = len(plot.getPlotItem().items)
    item._rebuild_labels()
    second_count = len(plot.getPlotItem().items)

    assert len(item._signal_items) == 1
    assert second_count == first_count
    plot.deleteLater()


def test_adjacent_signal_labels_are_stacked_vertically(app) -> None:
    """相邻且价格相同的信号必须错开标签，避免标题和EP/TP/SL互相覆盖。"""
    bars = make_bars()
    for bar in bars[:2]:
        bar.low_price = 100
        bar.high_price = 102
    manager = BarManager()
    manager.update_history(bars)
    item = AdaptiveLinearRegressionItem(manager)
    item.calculator.compute(bars)
    latest = item.calculator.states[-1]
    item.calculator.states[-1] = replace(
        latest,
        model=replace(latest.model, origin_idx=None, is_valid=False),
    )
    for ix in [0, 1]:
        state = item.calculator.states[ix]
        item.calculator.states[ix] = replace(
            state,
            signal=RegressionSignal(1, 100, 102, 98),
        )

    item._rebuild_labels()

    first_y = item._signal_items[0].pos().y()
    second_y = item._signal_items[1].pos().y()
    assert second_y < first_y
