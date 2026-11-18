"""用真实期货分钟线渲染 Bayesian 指标图表与配置对话框。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vnpy.trader.ui import QtCore, QtGui, QtWidgets
from vnpy.trader.utility import BarGenerator

from core.charts.enhanced_chart_widget import EnhancedChartWidget
from scripts.batch_backtest_bayesian_q import _load_bars


def aggregate_minutes(bars: list, minutes: int) -> list:
    completed = []
    generator = BarGenerator(lambda bar: None, minutes, completed.append)
    for bar in bars:
        generator.update_bar(bar)
    return completed


def render(contract: str, minutes: int, output_dir: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    root = "".join(char for char in contract.split(".")[0] if char.isalpha())
    warmup, bars = _load_bars((root, contract))
    hourly = aggregate_minutes([*warmup, *bars], minutes)

    chart = EnhancedChartWidget()
    chart.resize(1600, 1400)
    chart.update_history(hourly)
    for name in list(chart.sub_indicator_visibility):
        chart._toggle_sub_indicator(name, QtCore.Qt.Unchecked.value)
    for name in ("bayesian_bbsma", "nqqe", "bayesian_q"):
        chart._toggle_sub_indicator(name, QtCore.Qt.Checked.value)
    titles = {
        "bayesian_bbsma": "Bayesian BBSMA  |  Up / Down / Prime",
        "nqqe": "nQQE  |  QQEF / QQES",
        "bayesian_q": "Bayesian Q  |  nQQE + sigma direction",
    }
    for name, title in titles.items():
        chart._plots[name].setTitle(title, color="#E5E7EB", size="11pt")
    chart.show()
    app.processEvents()
    cursor = chart._cursor
    for info in cursor._infos.values():
        info.hide()
    for label in cursor._y_labels.values():
        label.hide()
    cursor._x_label.hide()
    for line in cursor._v_lines.values():
        line.hide()
    for line in cursor._h_lines.values():
        line.hide()
    app.processEvents()
    chart_path = output_dir / "bayesian-q-rendered-chart.png"
    if not chart.grab().save(str(chart_path), "PNG"):
        raise RuntimeError("图表截图保存失败")

    item = chart._items["bayesian_q"]
    dialog = item.get_config_dialog(chart)
    dialog.setStyleSheet(
        "QLabel {font-size: 14px;} QSpinBox, QDoubleSpinBox, QComboBox "
        "{font-size: 14px; min-height: 26px;} QPushButton {font-size: 14px;}"
    )
    dialog.show()
    app.processEvents()
    dialog.adjustSize()
    app.processEvents()
    config_path = output_dir / "bayesian-q-config-generated.png"
    pixmap = QtGui.QPixmap(dialog.size() * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(QtCore.Qt.transparent)
    dialog.render(pixmap)
    if not pixmap.save(str(config_path), "PNG"):
        raise RuntimeError("配置截图保存失败")
    dialog.close()
    chart.hide()
    print(f"{contract} {minutes}m bars={len(hourly)} chart={chart_path} config={config_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="a2701.DCE")
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "articles/images",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    render(args.contract, args.minutes, args.output_dir)


if __name__ == "__main__":
    main()
