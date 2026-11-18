#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化指标解码23的正文数字、图片引用与功能口径对账。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.indicators.calculators.random_forest_forecast_calculator import (
    RandomForestForecastCalculator,
)

ARTICLE = ROOT / "articles/量化指标解码23：随机森林预测器 - AI画出未来20根K线.md"
DATA = ROOT / "research/rf-direction-data/daily_rb.parquet"

checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    if not condition:
        raise AssertionError(message)
    checks += 1


def require(text: str, snippet: str) -> None:
    check(snippet in text, f"文章缺少或写错关键内容: {snippet}")


def main() -> None:
    text = ARTICLE.read_text(encoding="utf-8")
    require(text, "# 量化指标解码23：随机森林预测器 - AI画出未来20根K线")
    require(text, "预测一个点，还是画出一段范围")
    require(text, "八个特征，给森林八种看市场的角度")
    require(text, "OOB R²比方向更值得先看")
    require(text, "为什么只给预测器，不附带买卖信号")
    require(text, "下一篇讲 VWAP 深度解码")
    require(text, "增强版指标为会员专享功能")
    check("付费会员专享" not in text, "会员口径应统一为会员专享")

    for forbidden in ("Pine Script", "TradingView", "ShigemiQuant", "formula_mode", "NOTICE"):
        check(forbidden not in text, f"公开文章不应暴露来源或内部标识: {forbidden}")

    for image in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
        if image.startswith("./"):
            check((ARTICLE.parent / image).exists(), f"配图不存在: {image}")
    require(text, "./images/量化指标解码23-cover-v2b.png")
    require(text, "./images/rf-forecast-live-chart.png")
    require(text, "./images/rf-forecast-config.png")

    # 用同一份真实 rb 日线重新训练，逐项核对文章案例数字
    daily = pd.read_parquet(DATA).tail(620)
    bars = [
        SimpleNamespace(
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            volume=float(row["volume"]),
            datetime=timestamp,
        )
        for timestamp, row in daily.iterrows()
    ]
    calc = RandomForestForecastCalculator()
    result = calc.compute(bars)
    check(result.ready, "真实数据应可完成训练")
    check(result.train_samples == 500, "默认训练样本应为500")
    require(text, f"{result.oob_r2:+.4f}")
    require(text, f"{result.base_close:.1f}")
    for index in (0, 4, 9, 19):
        require(text, f"{result.pred_mean[index]:+.2f}%")
    require(text, f"±{1.96 * result.pred_std[0]:.2f}%")
    require(text, f"±{1.96 * result.pred_std[-1]:.2f}%")
    check(result.feature_importance[1] == result.feature_importance.max(),
          "ATR% 应为本次最高重要性特征")
    check(result.feature_importance[4] == sorted(result.feature_importance)[-2],
          "价格/SMA50 应为本次第二重要性特征")

    defaults = calc.get_current_config() if hasattr(calc, "get_current_config") else {
        "n_trees": calc.n_trees,
        "max_depth": calc.max_depth,
        "train_size": calc.train_size,
        "n_threshold_candidates": calc.n_threshold_candidates,
        "seed": calc.seed,
        "min_samples_leaf": calc.min_samples_leaf,
        "horizon": calc.horizon,
    }
    check(defaults == {
        "n_trees": 10,
        "max_depth": 4,
        "train_size": 500,
        "n_threshold_candidates": 5,
        "seed": 42,
        "min_samples_leaf": 10,
        "horizon": 20,
    }, "计算器默认参数与文章配置表不一致")

    chart_code = (ROOT / "core/charts/enhanced_chart_widget.py").read_text(encoding="utf-8")
    require(chart_code, '"random_forest_forecast"')
    require(chart_code, "preferred_x_extension")
    require(text, "17个品种")
    require(text, "方向准确率也没有超过50%")
    require(text, "不是同一个模型，不能直接横比收益")

    # 三个系列的往期回顾都必须各保留三篇真实链接
    for series in ("量化策略开发系列", "以AI量化为生系列", "量化指标解码系列"):
        start = text.index(f"**{series}**")
        next_series = text.find("**", start + len(series) + 4)
        block = text[start: next_series if next_series != -1 else len(text)]
        check(block.count("https://mp.weixin.qq.com/s/") == 3,
              f"{series} 应保留三篇往期链接")

    print(f"量化指标解码23对账通过：{checks} 项检查")


if __name__ == "__main__":
    main()
