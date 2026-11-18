#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分卡选股文章配图生成：
1. scorecard-woe.png —— 高IV因子的分箱好票占比与WOE（教学图）
2. scorecard-equity.png —— 复检段净值曲线：评分卡top20 vs 全A等权 vs 沪深300
3. scorecard-ic.png —— 各调仓日IC走势（三段背景色）
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.family"] = ["PingFang HK", "STHeiti", "Songti SC", "Yuanti SC", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "research" / "scorecard-data"
IMG_DIR = PROJECT_ROOT / "articles" / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DATE = "2026-11-05"

FACTOR_CN = {
    "mom20": "20日动量", "mom60": "60日动量", "vol20": "20日波动率",
    "turnover20": "20日换手率", "amp20": "20日振幅", "bias20": "20日乖离率",
    "maxret20": "20日最大单日涨幅",
}


def fig_woe():
    with open(DATA_DIR / f"评分卡分箱表-{RESULT_DATE}.json", encoding="utf-8") as fp:
        bins = json.load(fp)
    # 取IV最高的两个因子
    top2 = sorted(bins.items(), key=lambda kv: -kv[1]["iv"])[:2]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, (f, tbl) in zip(axes, top2):
        edges = tbl["edges"]
        labels = []
        for i in range(len(tbl["woe"])):
            lo, hi = edges[i], edges[i + 1]
            labels.append(f"{lo:.2f}~{hi:.2f}" if np.isfinite(lo) and np.isfinite(hi)
                          else (f"<{hi:.2f}" if not np.isfinite(lo) else f">{lo:.2f}"))
        x = np.arange(len(labels))
        ax.bar(x, tbl["good_rate"], color="#7fb3d3", alpha=0.85, label="跑赢中位数比例")
        ax.axhline(0.5, color="gray", ls="--", lw=0.8)
        ax2 = ax.twinx()
        ax2.plot(x, tbl["woe"], color="#c0392b", marker="o", lw=2, label="WOE")
        ax2.axhline(0, color="#c0392b", ls=":", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.set_title(f"{FACTOR_CN[f]}（{f}）IV={tbl['iv']:.4f}", fontsize=11)
        ax.set_ylabel("箱内跑赢中位数比例")
        ax2.set_ylabel("WOE")
    fig.suptitle("训练段（2021-2023）分箱体检：好票占比与WOE", fontsize=13)
    fig.tight_layout()
    fig.savefig(IMG_DIR / "scorecard-woe.png", dpi=140)
    plt.close(fig)
    print("scorecard-woe.png saved")


def fig_equity():
    bt = pd.read_csv(DATA_DIR / f"评分卡选股回测明细-{RESULT_DATE}.csv", parse_dates=["date"])
    ew = pd.read_csv(DATA_DIR / f"全A等权基准明细-{RESULT_DATE}.csv", parse_dates=["date"])
    idx = pd.read_parquet(DATA_DIR / "index_000300.parquet")

    rv_bt = bt[bt["period"] == "review"].reset_index(drop=True)
    rv_ew = ew[ew["period"] == "review"].reset_index(drop=True)
    start = rv_bt["date"].iloc[0]
    end = rv_bt["date"].iloc[-1]
    idx_rv = idx[(idx["date"] > start) & (idx["date"] <= end + pd.Timedelta(days=5))]

    fig, ax = plt.subplots(figsize=(10, 4.8))
    nav_bt = (1 + rv_bt["net"]).cumprod()
    nav_ew = (1 + rv_ew["net"]).cumprod()
    ax.plot(rv_bt["date"], nav_bt, lw=2, color="#c0392b",
            label=f"评分卡top20（净） 累计{nav_bt.iloc[-1]-1:+.1%}")
    ax.plot(rv_ew["date"], nav_ew, lw=1.6, color="#2c3e50",
            label=f"全A等权（净） 累计{nav_ew.iloc[-1]-1:+.1%}")
    if not idx_rv.empty:
        base = idx_rv["close"].iloc[0]
        ax.plot(idx_rv["date"], idx_rv["close"] / base, lw=1.2, color="#95a5a6", ls="--",
                label=f"沪深300 累计{idx_rv['close'].iloc[-1]/base-1:+.1%}")
    ax.axhline(1, color="gray", lw=0.7)
    ax.set_title("复检段（2025-01 ~ 2026-10）净值曲线：月调仓、含双边成本")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_ylabel("净值")
    fig.tight_layout()
    fig.savefig(IMG_DIR / "scorecard-equity.png", dpi=140)
    plt.close(fig)
    print("scorecard-equity.png saved")


def fig_ic():
    bt = pd.read_csv(DATA_DIR / f"评分卡选股回测明细-{RESULT_DATE}.csv", parse_dates=["date"])
    fig, ax = plt.subplots(figsize=(10, 3.6))
    colors = {"train": "#d6eaf8", "validation": "#fdebd0", "review": "#e8f6f3"}
    bounds = [("train", "2021-01-01", "2023-12-31"),
              ("validation", "2024-01-01", "2024-12-31"),
              ("review", "2025-01-01", "2026-11-01")]
    for name, lo, hi in bounds:
        ax.axvspan(pd.Timestamp(lo), pd.Timestamp(hi), color=colors[name], alpha=0.6)
    ax.plot(bt["date"], bt["ic"], color="#2c3e50", lw=1.2, marker="o", ms=3)
    ax.plot(bt["date"], bt["ic"].rolling(6, min_periods=1).mean(),
            color="#c0392b", lw=2, label="IC 6期滚动均值")
    ax.axhline(0, color="gray", lw=0.8)
    for p in ["train", "validation", "review"]:
        seg = bt[bt["period"] == p]
        ax.text(seg["date"].median(), ax.get_ylim()[1] * 0.9,
                f"{p}\n均值{seg['ic'].mean():.3f}", ha="center", fontsize=9)
    ax.set_title("各调仓日 Rank IC（分数 vs 未来10日收益）")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(IMG_DIR / "scorecard-ic.png", dpi=140)
    plt.close(fig)
    print("scorecard-ic.png saved")


if __name__ == "__main__":
    fig_woe()
    fig_equity()
    fig_ic()
