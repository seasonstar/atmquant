# -*- coding: utf-8 -*-
"""Bayesian BBSMA、nQQE 与 Bayesian Q 图表项的离屏集成测试。"""

from dataclasses import fields, replace
from datetime import datetime, timedelta
import math

import pytest

from vnpy.chart.manager import BarManager
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.trader.ui import QtGui, QtWidgets

from core.charts.enhanced_chart_widget import (
    EXTENDED_INDICATORS_CLASSES,
    EXTENDED_INDICATORS_CONFIG,
    EnhancedChartWidget,
)
from core.indicators.calculators.bayesian_bbsma_calculator import (
    compute as compute_bbsma,
)
from core.indicators.calculators.bayesian_q_calculator import (
    BayesianQCalculator,
    calculate_signals,
)
from core.indicators.calculators.nqqe_calculator import compute as compute_nqqe
from core.indicators.indicator_base import ConfigurableIndicator


ITEM_KEYS = ("bayesian_bbsma", "nqqe", "bayesian_q")


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture
def chart(qapp):
    widget = EnhancedChartWidget()
    yield widget
    # pyqtgraph 的 PlotWidget.close 在未 show 的离屏坐标轴上会访问空 scene。
    widget.deleteLater()


def make_bars(count: int = 140, *, offset: float = 0.0) -> list[BarData]:
    bars = []
    start = datetime(2026, 1, 1, 9, 0)
    for index in range(count):
        close = (
            100.0
            + offset
            + 8.0 * math.sin(index * 0.23)
            + 2.0 * math.sin(index * 0.71)
            + (index % 9) * 0.15
        )
        bars.append(
            BarData(
                symbol="TEST",
                exchange=Exchange.SSE,
                datetime=start + timedelta(minutes=index),
                interval=Interval.MINUTE,
                volume=1000.0 + index,
                turnover=close * (1000.0 + index),
                open_interest=0.0,
                gateway_name="TEST",
                open_price=close - 0.2,
                high_price=close + 1.0,
                low_price=close - 1.0,
                close_price=close,
            )
        )
    return bars


def make_item(key: str, bars: list[BarData] | None = None):
    assert key in EXTENDED_INDICATORS_CLASSES, f"未注册图表项: {key}"
    manager = BarManager()
    item = EXTENDED_INDICATORS_CLASSES[key](manager)
    if bars is not None:
        manager.update_history(bars)
        item.update_history(bars)
    return item


def assert_value_equal(actual, expected, label: str) -> None:
    if isinstance(expected, float) and math.isnan(expected):
        assert math.isnan(actual), label
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected), label
    else:
        assert actual == expected, label


def assert_states_equal(actual, expected) -> None:
    assert len(actual) == len(expected)
    for index, (actual_state, expected_state) in enumerate(zip(actual, expected)):
        for field in fields(expected_state):
            assert_value_equal(
                getattr(actual_state, field.name),
                getattr(expected_state, field.name),
                f"index={index}, field={field.name}",
            )


def assert_q_states_equal(actual, expected) -> None:
    assert len(actual) == len(expected)
    for index, (actual_state, expected_state) in enumerate(zip(actual, expected)):
        assert actual_state.signals == expected_state.signals, index
        assert_states_equal([actual_state.bayes], [expected_state.bayes])
        assert_states_equal([actual_state.nqqe], [expected_state.nqqe])


def expected_states(key: str, bars: list[BarData]):
    if key == "bayesian_bbsma":
        return compute_bbsma(bars)
    if key == "nqqe":
        return compute_nqqe(bars)
    return BayesianQCalculator.compute(bars)


def assert_item_matches_expected(key: str, item, bars: list[BarData]) -> None:
    expected = expected_states(key, bars)
    if key == "bayesian_q":
        assert_q_states_equal(item.states, expected)
    else:
        assert_states_equal(item.states, expected)


def test_registration_and_real_widget_create_hidden_configurable_subplots(chart) -> None:
    for key in ITEM_KEYS:
        config = EXTENDED_INDICATORS_CONFIG[key]
        assert config["type"] == "sub"
        assert config["default_visible"] is False
        assert config["configurable"] is True
        assert key in chart.sub_indicators
        assert key in chart._items
        assert key in chart._plots
        assert isinstance(chart._items[key], ConfigurableIndicator)
        assert not chart._plots[key].isVisible()
        assert not chart.sub_checkboxes[key].isChecked()


def test_real_hidden_items_match_reviewed_calculators_and_expose_ai_values(chart) -> None:
    bars = make_bars()
    chart.update_history(bars)

    for key in ITEM_KEYS:
        item = chart._items[key]
        assert_item_matches_expected(key, item, bars)
        assert item.get_current_values(), key
        assert not chart._plots[key].isVisible()


@pytest.mark.parametrize("key", ("bayesian_bbsma", "bayesian_q"))
def test_lookback_threshold_config_recomputes_from_same_bars(key) -> None:
    bars = make_bars(24)
    item = make_item(key, bars)
    config = {
        "period": 2,
        "lookback": 2,
        "stddev_mult": 0.0,
        "lower_threshold": 0.2,
    }

    item.apply_config(config)

    assert item.get_current_config() == config
    expected_bayes = compute_bbsma(
        bars,
        period=2,
        lookback=2,
        stddev_mult=0.0,
        lower_threshold=0.2,
    )
    if key == "bayesian_bbsma":
        assert_states_equal(item.states, expected_bayes)
    else:
        expected_nqqe = compute_nqqe(bars)
        for index, (state, bayes, nqqe, bar) in enumerate(
            zip(item.states, expected_bayes, expected_nqqe, bars)
        ):
            assert_states_equal([state.bayes], [bayes])
            assert_states_equal([state.nqqe], [nqqe])
            assert state.signals == calculate_signals(
                bar.close_price, bayes, nqqe
            ), index
        assert item.get_current_values()["background_is_calibrated_probability"] is False
        assert "不是校准概率" in item.get_info_text(len(bars) - 1)

    assert "Bayesian" in item.get_info_text(len(bars) - 1)

    item.apply_config({"lookback": 3, "lower_threshold": 0.25})
    expected_after_change = compute_bbsma(
        bars,
        period=2,
        lookback=3,
        stddev_mult=0.0,
        lower_threshold=0.25,
    )
    actual_bayes = item.states if key == "bayesian_bbsma" else [s.bayes for s in item.states]
    assert_states_equal(actual_bayes, expected_after_change)
    assert item.get_current_config()["lookback"] == 3
    assert item.get_current_config()["lower_threshold"] == 0.25
    assert "formula" + "_mode" not in item.get_current_config()


def test_nqqe_display_config_does_not_change_reviewed_math() -> None:
    bars = make_bars(80)
    item = make_item("nqqe", bars)

    item.apply_config({"show_cross_markers": False, "line_width": 3})

    assert item.get_current_config() == {
        "show_cross_markers": False,
        "line_width": 3,
    }
    assert_states_equal(item.states, compute_nqqe(bars))


@pytest.mark.parametrize("key", ITEM_KEYS)
def test_incremental_update_matches_full_recompute(key) -> None:
    bars = make_bars(90)
    full = make_item(key, bars)

    incremental = make_item(key, bars[:-1])
    incremental._manager.update_bar(bars[-1])
    incremental.update_bar(bars[-1])

    assert_item_matches_expected(key, incremental, bars)
    assert len(incremental._bar_picutures) == len(bars)
    assert incremental._bar_picutures[len(bars) - 1] is None


@pytest.mark.parametrize("key", ITEM_KEYS)
def test_replacing_history_clears_old_state_and_pictures(key) -> None:
    original = make_bars(50)
    replacement = make_bars(50, offset=7.0)
    item = make_item(key, original)
    item._bar_picutures[0] = item._draw_bar_picture(0, original[0])
    item._item_picuture = QtGui.QPicture()

    item._manager.update_history(replacement)
    item.update_history(replacement)

    assert_item_matches_expected(key, item, replacement)
    assert item._item_picuture is None
    assert len(item._bar_picutures) == len(replacement)
    assert all(picture is None for picture in item._bar_picutures.values())


@pytest.mark.parametrize("key", ITEM_KEYS)
def test_clear_all_clears_states_pictures_and_current_values(key) -> None:
    bars = make_bars(50)
    item = make_item(key, bars)
    item._bar_picutures[0] = item._draw_bar_picture(0, bars[0])
    item._item_picuture = item._bar_picutures[0]

    item.clear_all()

    assert item.states == []
    assert item._bar_picutures == {}
    assert item._item_picuture is None
    assert item.get_current_values() == {}


@pytest.mark.parametrize("key", ITEM_KEYS)
def test_offscreen_bar_pictures_are_non_null(chart, key) -> None:
    bars = make_bars(120)
    chart.update_history(bars)
    item = chart._items[key]

    for index in (0, 20, 60, 119):
        picture = item._draw_bar_picture(index, bars[index])
        assert isinstance(picture, QtGui.QPicture)
        assert not picture.isNull(), (key, index)


def test_bbsma_visible_y_range_keeps_negative_and_out_of_range_values() -> None:
    bars = make_bars(50)
    item = make_item("bayesian_bbsma", bars)
    low_index = 40
    high_index = 41
    item.states[low_index] = replace(
        item.states[low_index], prime_fixed=-0.35, sigma_up_fixed=1.4
    )
    item.states[high_index] = replace(item.states[high_index], prime_fixed=1.6)

    low_range = item.get_y_range(low_index, low_index)
    high_range = item.get_y_range(high_index, high_index)

    assert low_range[0] <= -35.0
    assert low_range[1] >= 140.0
    assert low_range[1] < 160.0
    assert high_range[1] >= 160.0


@pytest.mark.parametrize("key", ("nqqe", "bayesian_q"))
def test_nqqe_visible_y_range_keeps_raw_qqes_outliers(key) -> None:
    bars = make_bars(50)
    item = make_item(key, bars)
    low_index = 40
    high_index = 41
    if key == "nqqe":
        item.states[low_index] = replace(item.states[low_index], qqes=-12.0)
        item.states[high_index] = replace(item.states[high_index], qqes=125.0)
    else:
        item.states[low_index] = replace(
            item.states[low_index],
            nqqe=replace(item.states[low_index].nqqe, qqes=-12.0),
        )
        item.states[high_index] = replace(
            item.states[high_index],
            nqqe=replace(item.states[high_index].nqqe, qqes=125.0),
        )

    low_range = item.get_y_range(low_index, low_index)
    high_range = item.get_y_range(high_index, high_index)

    assert low_range[0] <= -12.0
    assert low_range[1] < 125.0
    assert high_range[1] >= 125.0


@pytest.mark.parametrize("key", ITEM_KEYS)
def test_config_dialog_exposes_real_controls(qapp, key) -> None:
    item = make_item(key)

    dialog = item.get_config_dialog(None)

    assert isinstance(dialog, QtWidgets.QDialog)
    assert hasattr(dialog, "config_widgets")
    if key == "nqqe":
        assert isinstance(
            dialog.config_widgets["show_cross_markers"], QtWidgets.QCheckBox
        )
    else:
        assert "formula" + "_mode" not in dialog.config_widgets
        assert "lookback" in dialog.config_widgets
        assert "lower_threshold" in dialog.config_widgets
    dialog.close()
    dialog.deleteLater()


def test_bayesian_q_range_expanding_append_invalidates_old_background_pictures() -> None:
    bars = make_bars(40)
    item = make_item("bayesian_q", bars)
    warm_index = 39
    item._bar_picutures[warm_index] = item._draw_bar_picture(
        warm_index, bars[warm_index]
    )
    item._item_picuture = QtGui.QPicture()
    previous_range = item.get_y_range()
    expanding_bar = replace(
        bars[-1],
        datetime=bars[-1].datetime + timedelta(minutes=1),
        open_price=9999.8,
        high_price=10001.0,
        low_price=9999.0,
        close_price=10000.0,
    )

    item._manager.update_bar(expanding_bar)
    item.update_bar(expanding_bar)

    expanded_range = item.get_y_range()
    assert expanded_range[1] > previous_range[1]
    assert item._bar_picutures[warm_index] is None
    assert item._item_picuture is None


def test_real_widget_clear_all_then_disjoint_history_drops_old_bars(chart) -> None:
    old_bars = make_bars(60)
    chart.update_history(old_bars)
    new_bars = [
        replace(bar, datetime=bar.datetime + timedelta(days=3))
        for bar in make_bars(20, offset=40.0)
    ]

    chart.clear_all()
    chart.update_history(new_bars)

    assert chart._manager.get_all_bars() == new_bars
    assert chart.base_minute_bars == new_bars
    assert all(chart._manager.get_index(bar.datetime) is None for bar in old_bars)
    for key in ITEM_KEYS:
        assert_item_matches_expected(key, chart._items[key], new_bars)


@pytest.mark.parametrize("key", ("nqqe", "bayesian_q"))
def test_cross_marker_uses_previous_bar_without_changing_signal_state(key) -> None:
    item = make_item(key, make_bars(80))
    state_before = item.states[-1]

    assert item._cross_marker_index(50) == 49
    assert item._cross_marker_index(0) == 0
    assert item.states[-1] == state_before


@pytest.mark.parametrize("key", ("bayesian_bbsma", "bayesian_q"))
def test_bayesian_items_use_corrected_values_without_mode(key, qapp) -> None:
    item = make_item(key, make_bars(80))

    assert not hasattr(item, "formula" + "_mode")
    assert "formula" + "_mode" not in item.get_current_config()
    assert "formula" + "_mode" not in item.get_current_values()
    assert "旧版" not in item.get_info_text(len(item.states) - 1)
    assert "原始公式" not in item.get_info_text(len(item.states) - 1)
    if key == "bayesian_bbsma":
        state = item.states[-1]
        assert item._selected_values(state) == (
            state.sigma_up_fixed,
            state.sigma_down_fixed,
            state.prime_fixed,
        )
    else:
        assert item._accepted_signal(item.states[-1]) == item.states[-1].signals[
            "bayes_q_fixed"
        ]

    dialog = item.get_config_dialog(None)
    assert "formula" + "_mode" not in dialog.config_widgets
    dialog.close()
    dialog.deleteLater()


@pytest.mark.parametrize("key", ITEM_KEYS)
def test_chinese_market_red_up_green_down_colors(key) -> None:
    from core.indicators.market_colors import MARKET_DOWN_RGB, MARKET_UP_RGB

    item = make_item(key)
    assert item.up_pen.color().getRgb()[:3] == MARKET_UP_RGB
    assert item.down_pen.color().getRgb()[:3] == MARKET_DOWN_RGB
    assert item.up_brush.color().getRgb()[:3] == MARKET_UP_RGB
    assert item.down_brush.color().getRgb()[:3] == MARKET_DOWN_RGB
    if key == "bayesian_q":
        assert item.up_background.color().getRgb()[:3] == MARKET_UP_RGB
        assert item.down_background.color().getRgb()[:3] == MARKET_DOWN_RGB
