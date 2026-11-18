"""随机森林方向批量研究的完整性与选参测试。"""

from datetime import date

import pandas as pd
import pytest

from scripts.batch_backtest_random_forest_direction import (
    BASELINE_SETTING,
    MODEL_GRID,
    MODELS,
    PARAMETER_KEYS,
    _make_bar,
    build_bars,
    get_research_period,
    select_model_parameters,
)


def make_row(model: str, train_window: int, period: str, total_return: float,
             drawdown: float = -1.0):
    return {
        "model": model,
        "train_window": train_window,
        "prob_threshold": 0.05,
        "period": period,
        "vt_symbol": "rb9999.SHFE",
        "total_return": total_return,
        "max_ddpercent": drawdown,
        "trade_count": 10,
    }


def test_preregistered_grid_contains_4_unique_sets() -> None:
    assert len(MODEL_GRID) == 4
    assert len({(row["train_window"], row["prob_threshold"]) for row in MODEL_GRID}) == 4
    for row in MODEL_GRID:
        assert row["label_horizon"] == 5
        assert row["retrain_interval"] == 21
        assert row["max_size"] == 2


def test_two_models_share_identical_grid() -> None:
    """RF 与 LR 的 A/B 唯一差异必须是模型类。"""
    assert MODELS == ("random_forest", "logistic")
    assert PARAMETER_KEYS == ["train_window", "prob_threshold"]
    assert BASELINE_SETTING == {"momentum_window": 21, "fixed_size": 1}


def test_selection_ignores_review_period() -> None:
    """复检段收益再高也不能影响参数选择。"""
    rows = [
        make_row("random_forest", 750, "train", -5.0),
        make_row("random_forest", 1500, "train", -2.0),
        make_row("random_forest", 750, "validation", -3.0),
        make_row("random_forest", 1500, "validation", -8.0),
        # 1500 在复检段大赚——若复检参与排名会翻转结果
        make_row("random_forest", 1500, "review", +100.0),
        make_row("random_forest", 750, "review", -1.0),
    ]
    selected = select_model_parameters(rows, "random_forest")
    assert selected == {"train_window": 750, "prob_threshold": 0.05}


def test_validation_picks_between_train_shortlist_only() -> None:
    """训练段排名前二之外的参数即使验证段最好也不能入选。"""
    rows = [
        make_row("random_forest", 750, "train", -1.0),
        make_row("random_forest", 1500, "train", -2.0),
        make_row("random_forest", 750, "validation", -9.0),
        make_row("random_forest", 1500, "validation", -4.0),
    ]
    selected = select_model_parameters(rows, "random_forest")
    assert selected["train_window"] == 1500


def test_period_mapping_is_chronological() -> None:
    assert get_research_period(date(2020, 6, 1)) == "train"
    assert get_research_period(date(2022, 12, 31)) == "train"
    assert get_research_period(date(2023, 1, 1)) == "validation"
    assert get_research_period(date(2023, 12, 31)) == "validation"
    assert get_research_period(date(2024, 1, 1)) == "review"
    assert get_research_period(date(2026, 10, 30)) == "review"


def test_make_bar_uses_daily_interval_and_15oclock() -> None:
    from vnpy.trader.constant import Exchange, Interval

    row = pd.Series({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                     "volume": 12345.0})
    bar = _make_bar("rb9999", Exchange.SHFE, pd.Timestamp("2020-03-02"), row)
    assert bar.interval == Interval.DAILY
    assert bar.datetime.hour == 15
    assert bar.close_price == 100.5
    assert bar.volume == 12345.0


def test_build_bars_missing_parquet_raises(tmp_path, monkeypatch) -> None:
    import scripts.batch_backtest_random_forest_direction as mod

    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="请先运行"):
        build_bars(("rb", "SHFE"))
