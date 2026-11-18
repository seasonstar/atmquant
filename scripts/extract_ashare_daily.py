#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分卡选股研究：从在线MySQL抽取全A日线数据到本地

数据说明（已验证）：
- ashare_daily 为前复权日线（茅台2021-02-10收盘2279.86 vs 未复权2601，差异=累计分红）
- 覆盖1990-12-19至2026-11-04，5594只股票（当前在市名单+2026年退市股）
- 2021-2025年退市股未入库，存在幸存者偏差，研究结论需如实声明并打折解读

输出：research/scorecard-data/ashare_daily_2020plus.parquet + ashare_info.csv
"""

import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "research" / "scorecard-data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]


def get_conn():
    return pymysql.connect(
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT", 3306)),
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        database=os.getenv("DATABASE_NAME"),
        connect_timeout=15,
        read_timeout=300,
    )


def main():
    conn = get_conn()

    info = pd.read_sql("SELECT symbol, name, industry, list_date, exchange FROM ashare_info", conn)
    info.to_csv(DATA_DIR / "ashare_info.csv", index=False, encoding="utf-8-sig")
    print(f"ashare_info {info.shape} 已保存")

    frames = []
    for year in YEARS:
        year_file = DATA_DIR / f"ashare_daily_{year}.parquet"
        if year_file.exists():
            df = pd.read_parquet(year_file)
            print(f"{year}: 本地缓存 {len(df)} rows", flush=True)
        else:
            sql = (
                "SELECT symbol, trade_date, open, high, low, close, volume, amount, "
                "turnover_rate, pct_change FROM ashare_daily "
                f"WHERE trade_date >= '{year}-01-01' AND trade_date < '{year + 1}-01-01'"
            )
            df = pd.read_sql(sql, conn)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df.to_parquet(year_file, index=False)  # 每年先落盘，防前功尽弃
            print(f"{year}: {len(df)} rows 已落盘", flush=True)
        frames.append(df)

    conn.close()
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    panel.to_parquet(DATA_DIR / "ashare_daily_2020plus.parquet", index=False)
    print(f"面板 {panel.shape} 已保存", flush=True)


if __name__ == "__main__":
    main()
