"""期货日线提取与换月比例调整的纯函数测试。"""

import numpy as np
import pandas as pd
import pytest

from scripts.extract_futures_daily import (
    aggregate_daily,
    assign_trading_days,
    detect_splice_days,
    merge_reference,
    ratio_adjust,
)


def minute_frame(rows: list[tuple[str, float, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["dt", "open", "high", "low", "close", "volume"]
    ).astype({"dt": "datetime64[ns]"})


class TestAssignTradingDays:
    def test_day_session_keeps_same_day(self) -> None:
        ts = pd.Series([pd.Timestamp("2020-03-02 10:30")])
        assert assign_trading_days(ts).iloc[0] == pd.Timestamp("2020-03-02")

    def test_night_session_belongs_to_next_weekday(self) -> None:
        ts = pd.Series([pd.Timestamp("2020-03-02 21:00")])  # 周一晚
        assert assign_trading_days(ts).iloc[0] == pd.Timestamp("2020-03-03")

    def test_friday_night_belongs_to_monday(self) -> None:
        ts = pd.Series([pd.Timestamp("2020-03-06 21:30")])  # 周五晚
        assert assign_trading_days(ts).iloc[0] == pd.Timestamp("2020-03-09")

    def test_1959_still_counts_as_day_session(self) -> None:
        # 19:59 仍属当日（夜盘最早 21:00，规则边界在 20:00）
        ts = pd.Series([pd.Timestamp("2020-03-02 19:59")])
        assert assign_trading_days(ts).iloc[0] == pd.Timestamp("2020-03-02")

    def test_early_morning_continuation_on_weekday(self) -> None:
        # 周二 00:30 是周一夜盘延续，归属周二
        ts = pd.Series([pd.Timestamp("2020-03-03 00:30")])
        assert assign_trading_days(ts).iloc[0] == pd.Timestamp("2020-03-03")

    def test_saturday_early_morning_belongs_to_monday(self) -> None:
        # 周六 01:00 是周五夜盘延续（贵金属至 02:30），归属周一
        ts = pd.Series([pd.Timestamp("2020-03-07 01:00")])
        assert assign_trading_days(ts).iloc[0] == pd.Timestamp("2020-03-09")

    def test_friday_night_and_saturday_morning_same_day(self) -> None:
        # 周五 21:00 与周六 02:00 同属一个交易日（周一）
        ts = pd.Series([
            pd.Timestamp("2020-03-06 21:00"),
            pd.Timestamp("2020-03-07 02:00"),
            pd.Timestamp("2020-03-09 09:00"),
        ])
        days = assign_trading_days(ts)
        assert days.iloc[0] == days.iloc[1] == pd.Timestamp("2020-03-09")


class TestAggregateDaily:
    def test_ohlc_and_volume(self) -> None:
        df = minute_frame([
            ("2020-03-02 09:00", 100, 101, 99, 100.5, 10),
            ("2020-03-02 10:30", 100.5, 103, 100, 102, 20),
            ("2020-03-02 14:59", 102, 102.5, 101, 101.5, 30),
            ("2020-03-02 21:00", 101.5, 104, 101, 103.5, 40),  # 属 03-03
            ("2020-03-03 09:00", 103.5, 105, 103, 104.5, 50),
        ])
        daily = aggregate_daily(df)
        assert list(daily.index) == [pd.Timestamp("2020-03-02"), pd.Timestamp("2020-03-03")]
        row1, row2 = daily.iloc[0], daily.iloc[1]
        assert row1["open"] == 100 and row1["close"] == 101.5
        assert row1["high"] == 103 and row1["low"] == 99
        assert row1["volume"] == 60 and row1["nbars"] == 3
        # 03-03 由夜盘+日盘组成，开为夜盘首根开、收为日盘末根收
        assert row2["open"] == 101.5 and row2["close"] == 104.5
        assert row2["high"] == 105 and row2["low"] == 101
        assert row2["volume"] == 90 and row2["nbars"] == 2


def daily_frame(closes: list[float], start="2020-01-01") -> pd.DataFrame:
    days = pd.bdate_range(start, periods=len(closes))
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes * 0.999,
            "high": closes * 1.002,
            "low": closes * 0.998,
            "close": closes,
            "volume": 1000.0,
            "nbars": 300,
        },
        index=days,
    )


def with_splice(closes: list[float], splice_index: int, factor: float) -> list[float]:
    """真实换月是永久水位偏移：splice_index 起（新主力）整体乘 factor。"""
    return [
        c * factor if i >= splice_index else c
        for i, c in enumerate(closes)
    ]


class TestMergeReference:
    def test_weighted_fills_missing_days(self) -> None:
        days = pd.bdate_range("2020-01-01", periods=6)
        closes8 = pd.Series([100, 101, np.nan, np.nan, 105, 106], index=days)
        weighted = pd.Series([103.0, 104.0, 105.0], index=days[2:5])
        ref, source = merge_reference(closes8, weighted, days)
        assert list(source) == ["8888", "8888", "weighted", "weighted", "8888", "8888"]
        np.testing.assert_allclose(ref.values, [100, 101, 103, 104, 105, 106])

    def test_missing_when_no_weighted(self) -> None:
        days = pd.bdate_range("2020-01-01", periods=3)
        closes8 = pd.Series([100, np.nan, 102], index=days)
        ref, source = merge_reference(closes8, None, days)
        assert list(source) == ["8888", "", "8888"]
        assert pd.isna(ref.iloc[1])


class TestDetectSplice:
    def test_flags_divergent_day_and_counts_coverage(self) -> None:
        # 第5日起 9999 切到价低 2% 的新主力 → 当日检出，次日不再误报
        base = list(np.linspace(100, 101, 8))
        d9 = daily_frame(with_splice(base, 5, 0.98))
        ref = daily_frame(base)["close"]
        result = detect_splice_days(d9, ref, threshold=0.01)
        assert len(result.splice_days) == 1
        assert result.splice_days[0] == d9.index[5]
        assert result.checked_days == 8 - 1  # 首日无收益不参与

    def test_normal_days_not_flagged(self) -> None:
        d = daily_frame(list(np.linspace(100, 104, 10)))
        result = detect_splice_days(d, d["close"], threshold=0.01)
        assert result.splice_days == []
        assert result.unchecked_days == 0

    def test_missing_reference_days_counted_unchecked(self) -> None:
        d9 = daily_frame(list(np.linspace(100, 104, 6)))
        ref = d9["close"].copy()
        ref.iloc[3] = np.nan
        result = detect_splice_days(d9, ref, threshold=0.01)
        # 缺失日当天与其次日（无前收）都无法比较
        assert result.unchecked_days == 2

    def test_reference_source_seam_skipped(self) -> None:
        """8888→加权切换日跳过比较，不计入 checked 也不误报。"""
        base = list(np.linspace(100, 105, 6))
        d9 = daily_frame(base)
        ref = daily_frame(base)["close"].copy()
        source = pd.Series("8888", index=d9.index, dtype=object)
        # 第3日起参考换成加权价，人为差 3%（模拟两类参考水位差）
        ref.iloc[3:] = ref.iloc[3:] * 1.03
        source.iloc[3:] = "weighted"
        result = detect_splice_days(d9, ref, source, threshold=0.01)
        assert result.seam_days == 1
        assert result.splice_days == []  # 缝隙日的大偏离被跳过
        # 缝隙之后的相邻 weighted-weighted 日子常比较
        assert result.checked_days == 6 - 1 - 1


class TestRatioAdjust:
    def test_history_rescaled_and_splice_day_uses_index_return(self) -> None:
        base = [100.0, 100.5, 101.0, 101.5, 102.0]
        ref = daily_frame(base)["close"]
        d9 = daily_frame(with_splice(base, 3, 0.98))  # 第4日起换到低水新主力
        result = detect_splice_days(d9, ref, threshold=0.01)
        adjusted = ratio_adjust(d9, result.splice_days, ref)

        # 换月日的调整后收益应等于参考价收益
        r8 = base[3] / base[2]
        np.testing.assert_allclose(
            adjusted["close"].iloc[3] / adjusted["close"].iloc[2], r8, rtol=1e-10
        )
        # 换月日之前的历史按 r9999/rref 缩放（旧主力价格映射到新主力水位）
        factor = (base[3] * 0.98 / base[2]) / (base[3] / base[2])
        np.testing.assert_allclose(adjusted["close"].iloc[:3], np.array(base[:3]) * factor)
        # 换月日之后保持原始价格（末端贴近可成交价）
        np.testing.assert_allclose(
            adjusted["close"].iloc[3:], [b * 0.98 for b in base[3:]]
        )

    def test_multiple_splices_compose(self) -> None:
        base = [100 + i * 0.2 for i in range(12)]
        ref = daily_frame(base)["close"]
        d9 = daily_frame(with_splice(with_splice(base, 3, 0.97), 8, 1.05))
        result = detect_splice_days(d9, ref, threshold=0.01)
        assert len(result.splice_days) == 2
        adjusted = ratio_adjust(d9, result.splice_days, ref)
        returns = adjusted["close"].pct_change().dropna()
        # 调整后每日收益与参考价收益一致（跳变全部被抹平）
        np.testing.assert_allclose(returns.values, ref.pct_change().dropna().values,
                                   rtol=1e-10)

    def test_no_splice_leaves_prices_untouched(self) -> None:
        d9 = daily_frame([100, 101, 102, 103])
        ref = d9["close"]
        adjusted = ratio_adjust(d9, [], ref)
        np.testing.assert_allclose(adjusted["close"].values, d9["close"].values)
