#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为量化指标解码23渲染随机森林预测器真实配图。

离屏运行：QT_QPA_PLATFORM=offscreen ./venv/bin/python scripts/render_random_forest_forecast_article.py
"""

from pathlib import Path
import sys

import pandas as pd
from PySide6 import QtCore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.trader.ui import QtGui, QtWidgets

from core.charts.enhanced_chart_widget import EnhancedChartWidget

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "research" / "rf-direction-data" / "daily_rb.parquet"
IMAGE_DIR = PROJECT_ROOT / "articles" / "images"


def load_bars() -> list[BarData]:
    daily = pd.read_parquet(DATA_PATH).tail(620)
    bars = []
    for timestamp, row in daily.iterrows():
        bars.append(BarData(
            gateway_name="ARTICLE",
            symbol="rb9999",
            exchange=Exchange.SHFE,
            datetime=timestamp.to_pydatetime().replace(hour=15),
            interval=Interval.DAILY,
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            volume=float(row["volume"]),
            turnover=0.0,
            open_interest=0.0,
        ))
    return bars


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    widget = EnhancedChartWidget()
    widget.resize(1680, 1000)
    bars = load_bars()
    widget.update_history(bars)
    widget._toggle_main_indicator(
        "random_forest_forecast", QtCore.Qt.Checked.value
    )
    plot = widget._plots["candle"]
    item = widget._items["random_forest_forecast"]
    item.attach_hud(plot)
    bottom_axis = plot.getAxis("bottom")
    plot.showAxis("bottom")
    bottom_axis.setStyle(showValues=True)
    bottom_axis.setHeight(56)
    bottom_axis.setTextPen(QtGui.QColor("#CBD5E1"))
    # 文章配图隐藏浮层控件，保留真实图表、坐标轴和指标HUD
    widget.main_controls_widget.hide()
    widget.sub_controls_widget.hide()
    widget.interval_panel.hide()
    widget.show()
    app.processEvents()

    # 只截取主图场景区域，避开离屏环境下工具栏与侧边栏的布局伪象
    chart_path = IMAGE_DIR / "rf-forecast-live-chart.png"
    chart_rect = widget.mapFromScene(plot.sceneBoundingRect()).boundingRect()
    widget.grab().copy(chart_rect).save(str(chart_path))

    dialog = item.get_config_dialog(widget)
    dialog.show()
    app.processEvents()
    dialog.adjustSize()
    app.processEvents()
    config_path = IMAGE_DIR / "rf-forecast-config.png"
    content = dialog.grab()
    # 离屏截图不含原生标题栏，手工补一行标题并去掉多余空白
    final = QtGui.QPixmap(content.width(), content.height() + 56)
    final.fill(QtGui.QColor("#F3F4F6"))
    painter = QtGui.QPainter(final)
    painter.setPen(QtGui.QColor("#111827"))
    font = painter.font()
    font.setPointSize(16)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        QtCore.QRect(16, 0, content.width() - 32, 56),
        QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
        "随机森林预测器配置",
    )
    painter.drawPixmap(0, 56, content)
    painter.end()
    final.save(str(config_path))
    dialog.close()

    result = item.calculator.result
    print(f"图表: {chart_path}")
    print(f"配置: {config_path}")
    print(
        f"ready={result.ready} OOB R²={result.oob_r2:+.4f} "
        f"H1={result.pred_mean[0]:+.2f}% "
        f"H5={result.pred_mean[4]:+.2f}% "
        f"H10={result.pred_mean[9]:+.2f}% "
        f"H20={result.pred_mean[-1]:+.2f}%"
    )


if __name__ == "__main__":
    main()
