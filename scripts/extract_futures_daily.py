#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""期货 9999 主连/8888 加权 1 分钟K线 → 日线提取与换月比例调整。

预登记协议见 research/随机森林方向预测研究方案-2026-11-17.md：
- 交易日规则：20:00 及以后的夜盘K线属于下一个工作日（次日为非交易日时该夜盘不存在）。
- 换月检测：|9999日收益 - 8888日收益| > 1% 判为换月日。
- 比例调整：换月日真实变动以加权指数收益近似，此前历史按 (1+r8888)/(1+r9999) 回溯缩放。
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "research" / "rf-direction-data"

DIVERGENCE_THRESHOLD = 0.01
START_DATE = "2016-01-04"
END_DATE = "2026-11-01"

# 18 品种（2016-01 起 9999 与 8888 均在库）: (品种, 交易所)
PRODUCTS = [
    ("rb", "SHFE"), ("hc", "SHFE"), ("i", "DCE"), ("j", "DCE"), ("jm", "DCE"),
    ("MA", "CZCE"), ("TA", "CZCE"), ("FG", "CZCE"), ("RM", "CZCE"),
    ("m", "DCE"), ("y", "DCE"),
    ("au", "SHFE"), ("ag", "SHFE"), ("al", "SHFE"), ("ni", "SHFE"), ("sn", "SHFE"),
    ("bu", "SHFE"), ("fu", "SHFE"),
]


@dataclass
class SpliceResult:
    """换月检测的对外结果。"""

    splice_days: list[pd.Timestamp]
    checked_days: int     # 参与检测的公共交易日数（扣除首日与缝隙日）
    unchecked_days: int   # 参考价缺失导致无法检测的 9999 交易日数
    seam_days: int        # 参考价来源切换（8888↔加权）导致跳过比较的交易日数


def assign_trading_days(timestamps: pd.Series) -> pd.Series:
    """把 1 分钟时间戳映射到交易日。

    - >=20:00 的夜盘首段属于下一个工作日（周五夜盘 → 周一）。
    - <05:00 的凌晨K线是前一自然日夜盘的延续（如周六 00:30 属于周五发起、
      归属周一的夜盘），同样映射到 前一自然日+1 个工作日。
    - 其余（日盘）属于当日。
    """
    ts = pd.Series(pd.DatetimeIndex(timestamps)).dt.normalize()
    hour = pd.Series(pd.DatetimeIndex(timestamps)).dt.hour
    night_start = hour >= 20
    night_late = hour < 5
    assigned = ts.copy()
    assigned[night_start] = ts[night_start] + pd.tseries.offsets.BDay(1)
    assigned[night_late] = (
        ts[night_late] - pd.Timedelta(days=1) + pd.tseries.offsets.BDay(1)
    )
    return assigned


def aggregate_daily(minute_df: pd.DataFrame) -> pd.DataFrame:
    """按交易日聚合 1 分钟OHLCV 为日线。"""
    day = assign_trading_days(minute_df["dt"])
    grouped = minute_df.assign(day=day).groupby("day")
    daily = pd.DataFrame({
        "open": grouped["open"].first(),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(),
        "nbars": grouped.size(),
    })
    return daily.sort_index()


def merge_reference(
    closes_8888: pd.Series,
    weighted: pd.Series,
    days: pd.DatetimeIndex,
) -> tuple[pd.Series, pd.Series]:
    """8888 与真实合约加权参考价合并为单一平滑参考。

    返回 (参考收盘价, 来源标记)；来源为 "8888"、"weighted" 或 ""（缺失）。
    """
    ref = closes_8888.reindex(days)
    source = pd.Series("8888", index=days, dtype=object)
    source[ref.isna()] = ""
    if weighted is not None:
        fill = weighted.reindex(days)
        take = ref.isna() & fill.notna()
        ref[take] = fill[take]
        source[take] = "weighted"
    return ref, source


def detect_splice_days(
    daily_9999: pd.DataFrame,
    ref_close: pd.Series,
    ref_source: pd.Series | None = None,
    threshold: float = DIVERGENCE_THRESHOLD,
) -> SpliceResult:
    """按 9999/参考价日收益偏离检测主连换月日。

    只在参考价当日与昨日都存在的相邻交易日上比较；9999 有而参考价无的
    交易日计入 unchecked；参考价来源在相邻日切换（8888↔加权）时跳过比较
    并计入 seam，避免两类参考的水位差被误判为换月。
    """
    ref = ref_close.reindex(daily_9999.index)
    r9 = daily_9999["close"].pct_change(fill_method=None)
    r8 = ref.pct_change(fill_method=None)
    unchecked = int((r9.notna() & r8.isna()).sum())
    comparable = r9.notna() & r8.notna()
    seam_days = 0
    if ref_source is not None:
        src = ref_source.reindex(daily_9999.index).fillna("")
        prev_src = src.shift(1).fillna("")
        seam = comparable & (src != prev_src) & (src != "") & (prev_src != "")
        seam_days = int(seam.sum())
        comparable = comparable & ~seam
    divergence = (r9 - r8)[comparable]
    splice_days = list(divergence[divergence.abs() > threshold].index)
    return SpliceResult(
        splice_days=splice_days,
        checked_days=int(len(divergence)),
        unchecked_days=unchecked,
        seam_days=seam_days,
    )


def ratio_adjust(
    daily_9999: pd.DataFrame,
    splice_days: list[pd.Timestamp],
    ref_close: pd.Series,
) -> pd.DataFrame:
    """对 9999 日线做比例回溯调整，抹平换月跳价。

    换月日 t 的原始收益 r9999_t 同时包含真实变动与换月跳价，参考价收益
    rref_t 只含真实变动。保持末端（最新主力）原始价格可成交，把 t 之前的
    历史全部乘以 r9999_t/rref_t，使 t 日调整后收益等于参考价收益；
    多次换月按时间顺序复合。
    """
    adjusted = daily_9999.copy()
    ref = ref_close.reindex(daily_9999.index)
    cum_factor = 1.0
    applied = 0
    for day in sorted(splice_days):
        loc = daily_9999.index.get_loc(day)
        if loc == 0 or pd.isna(ref.iloc[loc]) or pd.isna(ref.iloc[loc - 1]):
            continue
        r9 = daily_9999["close"].iloc[loc] / daily_9999["close"].iloc[loc - 1]
        r8 = ref.iloc[loc] / ref.iloc[loc - 1]
        if r9 <= 0 or r8 <= 0:
            continue
        factor = r9 / r8
        for column in ["open", "high", "low", "close"]:
            adjusted.iloc[:loc, adjusted.columns.get_loc(column)] *= factor
        cum_factor *= factor
        applied += 1
    adjusted.attrs["adjustment_factor"] = cum_factor
    adjusted.attrs["applied_splices"] = applied
    return adjusted


def load_1m(engine_factory, symbol: str, exchange: str) -> pd.DataFrame:
    """按年分块从 MySQL 读 1 分钟K线，失败自动重连重试。

    整段 10 年一次流式返回约百万行，实测会被服务端重置连接；
    按年查询每块约十万行，并对 OperationalError 重试。
    engine_factory 是无参可调用，每次重试用新连接。
    """
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    query = text(
        'SELECT datetime AS dt, open_price AS "open", high_price AS "high", '
        'low_price AS "low", close_price AS "close", volume '
        'FROM dbbardata WHERE symbol=:symbol AND exchange=:exchange '
        'AND `interval`="1m" AND datetime >= :start AND datetime < :end '
        'ORDER BY datetime'
    )
    start_year = int(START_DATE[:4])
    end_year = int(END_DATE[:4])
    frames = []
    engine = engine_factory()
    for year in range(start_year, end_year + 1):
        chunk_start = max(f"{year}-01-01", START_DATE)
        chunk_end = min(f"{year + 1}-01-01", END_DATE)
        for attempt in range(3):
            try:
                with engine.connect() as conn:
                    rows = conn.execute(
                        query,
                        {
                            "symbol": symbol,
                            "exchange": exchange,
                            "start": chunk_start,
                            "end": chunk_end,
                        },
                    ).fetchall()
                frames.append(pd.DataFrame(
                    rows, columns=["dt", "open", "high", "low", "close", "volume"]
                ))
                break
            except OperationalError as exc:
                engine.dispose()
                engine = engine_factory()
                if attempt == 2:
                    raise RuntimeError(
                        f"{symbol}.{exchange} {chunk_start[:4]} 年数据读取失败"
                    ) from exc
                print(f"  {symbol} {year} 年读取失败重试: {exc}", flush=True)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if combined.empty:
        raise RuntimeError(f"{symbol}.{exchange} 无 1 分钟数据")
    return combined


def build_weighted_reference(
    engine_factory,
    root: str,
    exchange: str,
    first_day: pd.Timestamp,
    last_day: pd.Timestamp,
) -> pd.Series | None:
    """用真实合约自建成交量加权参考价，回补 8888 缺口。

    8888 加权指数与成交量的逐合约加权价同为全合约平滑参考，仅用于换月检测
    与当日真实变动近似，不用于成交。只载入缺口窗口（前后各留 10 天）的数据，
    按合约逐个查询避免大结果集被服务端重置。
    """
    from sqlalchemy import text

    load_start = (first_day - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    load_end = (last_day + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    engine = engine_factory()
    overview_sql = text(
        "SELECT symbol, count FROM dbbaroverview "
        'WHERE `interval`="1m" AND exchange=:exchange '
        "AND symbol REGEXP :pattern"
    )
    with engine.connect() as conn:
        symbols = [
            row[0] for row in conn.execute(
                overview_sql, {"exchange": exchange, "pattern": f"^{root}[0-9]+$"}
            ).fetchall()
        ]
    symbols = [s for s in symbols if s not in (f"{root}9999", f"{root}8888")]
    if not symbols:
        return None

    bars_sql = text(
        "SELECT datetime AS dt, close_price AS close, volume "
        "FROM dbbardata WHERE symbol=:symbol AND exchange=:exchange "
        'AND `interval`="1m" AND datetime >= :start AND datetime < :end'
    )
    frames = []
    for symbol in symbols:
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    bars_sql,
                    {"symbol": symbol, "exchange": exchange,
                     "start": load_start, "end": load_end},
                ).fetchall()
        except Exception as exc:  # 单合约失败不阻断整体回补
            print(f"  加权参考 {symbol} 读取失败: {exc}", flush=True)
            continue
        if not rows:
            continue
        minute = pd.DataFrame(rows, columns=["dt", "close", "volume"])
        daily = aggregate_daily(minute.assign(open=minute["close"],
                                              high=minute["close"],
                                              low=minute["close"]))
        daily = daily[daily["volume"] > 0]
        frames.append(pd.DataFrame({
            "close": daily["close"], "volume": daily["volume"]
        }, index=daily.index))
    if not frames:
        return None
    combined = pd.concat([
        frame.assign(contract=i) for i, frame in enumerate(frames)
    ])
    # 每个交易日跨所有合约做成交量加权：Σ(close×volume)/Σ(volume)
    grouped = combined.groupby(combined.index)
    weighted_close = (grouped.apply(
        lambda g: (g["close"] * g["volume"]).sum() / g["volume"].sum()
    ))
    weighted_close = weighted_close[weighted_close > 0]
    return None if weighted_close.empty else weighted_close.sort_index()


def extract_product(engine_factory, root: str, exchange: str) -> dict:
    """提取一个品种：聚合、检测、调整、落盘，返回摘要。"""
    raw9 = aggregate_daily(load_1m(engine_factory, f"{root}9999", exchange))
    raw8 = aggregate_daily(load_1m(engine_factory, f"{root}8888", exchange))
    ref, source = merge_reference(raw8["close"], None, raw9.index)
    weighted_days = 0
    if ref.isna().any():
        gap_days = ref.index[ref.isna()]
        weighted = build_weighted_reference(
            engine_factory, root, exchange, gap_days.min(), gap_days.max()
        )
        if weighted is not None:
            ref, source = merge_reference(raw8["close"], weighted, raw9.index)
            weighted_days = int((source == "weighted").sum())
    result = detect_splice_days(raw9, ref, source)
    adjusted = ratio_adjust(raw9, result.splice_days, ref)

    out = adjusted.copy()
    out["raw_open"] = raw9["open"]
    out["raw_close"] = raw9["close"]
    out["close_ref"] = ref
    out["ref_source"] = source
    out["is_splice"] = False
    out.loc[result.splice_days, "is_splice"] = True
    out.index.name = "trading_day"
    out.to_parquet(OUTPUT_DIR / f"daily_{root}.parquet")

    years = max(out.index[-1].year - out.index[0].year, 1)
    return {
        "root": root,
        "exchange": exchange,
        "minute_bars_9999": int(raw9["nbars"].sum()),
        "minute_bars_8888": int(raw8["nbars"].sum()),
        "daily_days": int(len(out)),
        "first_day": str(out.index[0].date()),
        "last_day": str(out.index[-1].date()),
        "splice_days": len(result.splice_days),
        "splices_per_year": round(len(result.splice_days) / years, 2),
        "splice_list": [str(d.date()) for d in result.splice_days],
        "unchecked_days": result.unchecked_days,
        "weighted_reference_days": weighted_days,
        "seam_days": result.seam_days,
        "adjustment_factor": round(float(adjusted.attrs["adjustment_factor"]), 6),
    }


def main() -> None:
    import config.settings  # noqa: F401 应用 .env
    from sqlalchemy import create_engine
    from vnpy_mysql import mysql_database

    def engine_factory():
        # 连接/读取超时防止网络悬挂卡死整轮提取；超时后走分块重试
        return create_engine(
            mysql_database.DATABASE_URL,
            pool_recycle=3600,
            connect_args={"connect_timeout": 15, "read_timeout": 300},
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for root, exchange in PRODUCTS:
        parquet = OUTPUT_DIR / f"daily_{root}.parquet"
        if parquet.exists():
            print(f"{root:3s} 已提取，跳过", flush=True)
            continue
        summary = extract_product(engine_factory, root, exchange)
        # 换月异常频繁或参考价缺口仍然过大时显式标记供复核
        summary["needs_review"] = (
            summary["splices_per_year"] > 12 or summary["unchecked_days"] > 60
        )
        summaries.append(summary)
        flag = " [需复核]" if summary["needs_review"] else ""
        print(
            f"{root:3s} {summary['daily_days']:>5} 交易日 "
            f"{summary['first_day']}~{summary['last_day']} "
            f"换月 {summary['splice_days']:>3} 个 "
            f"({summary['splices_per_year']:.1f}/年) "
            f"加权回补 {summary['weighted_reference_days']} 天 "
            f"未检测 {summary['unchecked_days']} 天{flag}",
            flush=True,
        )
    # 摘要聚合已有结果（断点续跑时也覆盖全部品种）
    if (OUTPUT_DIR / "extraction_summary.json").exists():
        with open(OUTPUT_DIR / "extraction_summary.json", encoding="utf-8") as f:
            known = {row["root"]: row for row in json.load(f)}
    else:
        known = {}
    for summary in summaries:
        known[summary["root"]] = summary
    with open(OUTPUT_DIR / "extraction_summary.json", "w", encoding="utf-8") as f:
        json.dump(list(known.values()), f, ensure_ascii=False, indent=2)
    print(f"完成 {len(known)} 个品种，摘要写入 {OUTPUT_DIR / 'extraction_summary.json'}")


if __name__ == "__main__":
    main()
