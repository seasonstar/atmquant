#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分卡选股研究：下载沪深300成分股日线数据（后复权）

数据源：akshare（东方财富公开接口）
范围：沪深300当前成分股，2021-01-01 ~ 2026-10-31 日线
输出：research/scorecard-data/csi300_daily.parquet + csi300_cons.csv + index_000300.parquet

注意：当前成分股不含历史退市/调出股票，存在幸存者偏差，
研究报告与文章中必须如实声明，结果按偏乐观口径打折解读。
"""

import sys
import time
from pathlib import Path

import akshare as ak
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "research" / "scorecard-data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = "20210101"
END_DATE = "20261031"


def download_cons() -> pd.DataFrame:
    """下载沪深300当前成分股名单"""
    cons = ak.index_stock_cons_csindex("000300")
    cons = cons.rename(columns={"成分券代码": "code", "成分券名称": "name", "交易所": "exchange"})
    cons = cons[["code", "name", "exchange"]]
    cons.to_csv(DATA_DIR / "csi300_cons.csv", index=False, encoding="utf-8-sig")
    print(f"成分股 {len(cons)} 只已保存")
    return cons


def download_daily(code: str, retry: int = 3) -> pd.DataFrame:
    """下载单只股票后复权日线，带重试"""
    for attempt in range(retry):
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=START_DATE, end_date=END_DATE, adjust="hfq",
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            print(f"  {code} 第{attempt + 1}次失败: {e}")
            time.sleep(1 + attempt)
    print(f"  {code} 下载失败，跳过")
    return pd.DataFrame()


def main():
    cons = download_cons()

    frames = []
    failed = []
    t0 = time.time()
    for i, row in cons.iterrows():
        code = row["code"]
        df = download_daily(code)
        if df.empty:
            failed.append(code)
            continue
        df = df.rename(columns={
            "日期": "date", "股票代码": "code", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
            "振幅": "amplitude", "涨跌幅": "pct_chg", "换手率": "turnover",
        })
        df["date"] = pd.to_datetime(df["date"])
        frames.append(df[["date", "code", "open", "close", "high", "low",
                          "volume", "amount", "amplitude", "pct_chg", "turnover"]])
        if (i + 1) % 30 == 0:
            elapsed = time.time() - t0
            print(f"进度 {i + 1}/{len(cons)}，耗时 {elapsed:.0f}s")

    panel = pd.concat(frames, ignore_index=True)
    panel.to_parquet(DATA_DIR / "csi300_daily.parquet", index=False)
    print(f"日线面板 {panel.shape} 已保存，失败 {len(failed)} 只: {failed}")

    # 沪深300指数基准
    idx = ak.index_zh_a_hist(symbol="000300", period="daily",
                             start_date=START_DATE, end_date=END_DATE)
    idx = idx.rename(columns={"日期": "date", "收盘": "close", "开盘": "open",
                              "最高": "high", "最低": "low"})
    idx["date"] = pd.to_datetime(idx["date"])
    idx.to_parquet(DATA_DIR / "index_000300.parquet", index=False)
    print(f"指数 {idx.shape} 已保存")


if __name__ == "__main__":
    main()
