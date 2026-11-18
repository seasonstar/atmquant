from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import json
import warnings

import numpy as np
import pandas as pd
import pytest

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.database import BarOverview
from vnpy.trader.object import BarData

from core.indicators.calculators.bayesian_q_calculator import MODEL_NAMES
from core.strategies.bayesian_q_strategy import BayesianQStrategy
from scripts import batch_backtest_bayesian_q as batch


def _info(exchange: Exchange = Exchange.SHFE, **overrides) -> dict:
    info = {
        "exchange": exchange,
        "size": 10,
        "pricetick": 1.0,
        "rate": 0.0001,
        "slippage": 3.0,
    }
    info.update(overrides)
    return info


def _overview(
    symbol: str,
    exchange: Exchange,
    *,
    count: int = 40_000,
    start: datetime = datetime(2026, 3, 1),
    end: datetime = datetime(2026, 11, 10),
    interval: Interval = Interval.MINUTE,
) -> BarOverview:
    return BarOverview(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        count=count,
        start=start,
        end=end,
    )


def _contract(root: str = "rb", vt_symbol: str = "rb2701.SHFE", **overrides) -> dict:
    contract = {
        "root": root,
        "vt_symbol": vt_symbol,
        "exchange": Exchange.SHFE.value,
        "count": 40_000,
        "start": "2026-03-01T00:00:00",
        "end": "2026-11-10T00:00:00",
        "size": 10,
        "pricetick": 1.0,
        "rate": 0.0001,
        "fixed_fee": 3.0,
    }
    contract.update(overrides)
    return contract


def test_discover_universe_handles_real_contract_selection_and_all_failures():
    config = {
        "rb": _info(),
        "MA": _info(Exchange.CZCE),
        "cu": _info(),
        "hc": _info(),
        "zn": _info(),
    }
    overviews = [
        _overview("rb2601.SHFE".split(".")[0], Exchange.SHFE, count=90),
        _overview("RB2605", Exchange.SHFE, count=120),
        _overview("rb2509", Exchange.SHFE, count=200, end=datetime(2026, 10, 30)),
        _overview("rb8888", Exchange.SHFE, count=999_999, end=datetime(2027, 1, 1)),
        _overview("RB9999", Exchange.SHFE, count=999_999, end=datetime(2027, 1, 1)),
        _overview("ma701", Exchange.CZCE, count=500),
        _overview("MA705", Exchange.CZCE, count=400, end=datetime(2026, 10, 29)),
        _overview("MA9999", Exchange.CZCE, count=999_999),
        _overview("cu2701", Exchange.SHFE, end=datetime(2026, 10, 20)),
        _overview("OI701", Exchange.CZCE, count=321),
        _overview("zn8888", Exchange.SHFE, count=777),
        _overview("jd9999", Exchange.DCE, interval=Interval.DAILY),
    ]

    selected, failures = batch.discover_futures_universe(overviews, config=config)

    assert [row["root"] for row in selected] == ["MA", "rb"]
    by_root = {row["root"]: row for row in selected}
    assert by_root["rb"]["vt_symbol"] == "RB2605.SHFE"
    assert by_root["rb"]["count"] == 120
    assert by_root["MA"]["vt_symbol"] == "ma701.CZCE"
    assert all(not row["vt_symbol"].split(".")[0].endswith(("8888", "9999")) for row in selected)

    reasons = {row["root"]: row["reason"] for row in failures}
    assert reasons == {
        "OI": "missing_config",
        "cu": "incomplete_coverage",
        "hc": "missing_db_data",
        "zn": "no_real_contract",
    }
    incomplete = next(row for row in failures if row["root"] == "cu")
    assert incomplete["vt_symbol"] == "cu2701.SHFE"
    assert incomplete["count"] == 40_000
    assert incomplete["start"] == "2026-03-01T00:00:00"
    assert incomplete["end"] == "2026-10-20T00:00:00"
    unconfigured = next(row for row in failures if row["root"] == "OI")
    assert (unconfigured["count"], unconfigured["start"], unconfigured["end"]) == (
        321,
        "2026-03-01T00:00:00",
        "2026-11-10T00:00:00",
    )
    missing = next(row for row in failures if row["root"] == "hc")
    assert (missing["count"], missing["start"], missing["end"]) == (0, "", "")


@pytest.mark.parametrize("field", ["size", "pricetick", "rate", "slippage"])
def test_discover_universe_rejects_missing_cost_or_contract_fields(field):
    info = _info()
    del info[field]
    selected, failures = batch.discover_futures_universe(
        [_overview("rb2701", Exchange.SHFE)], config={"rb": info}
    )

    assert selected == []
    expected = "missing_fixed_fee" if field == "slippage" else f"missing_{field}"
    assert [row["reason"] for row in failures] == [expected]
    assert failures[0]["vt_symbol"] == "rb2701.SHFE"


def test_discover_universe_combines_config_and_coverage_failures_per_root():
    info = _info(rate=-1)
    del info["size"]

    selected, failures = batch.discover_futures_universe(
        [_overview("rb2701", Exchange.SHFE, end=datetime(2026, 10, 20))],
        config={"rb": info},
    )

    assert selected == []
    assert len(failures) == 1
    assert set(failures[0]["reason"].split(";")) == {
        "missing_size", "invalid_rate", "incomplete_coverage",
    }
    assert "missing_size" in failures[0]["detail"]
    assert "incomplete_coverage" in failures[0]["detail"]


def test_discover_universe_combines_multiple_config_errors_and_counts_roots(tmp_path):
    info = _info(pricetick=0)
    del info["size"]
    del info["slippage"]
    selected, failures = batch.discover_futures_universe(
        [_overview("rb2701", Exchange.SHFE)], config={"rb": info},
    )

    assert selected == []
    assert len(failures) == 1
    assert set(failures[0]["reason"].split(";")) == {
        "missing_size", "invalid_pricetick", "missing_fixed_fee",
    }

    batch.write_inventory_outputs(
        selected,
        failures,
        [],
        output_dir=tmp_path,
        config_count=1,
        db_root_count=1,
    )
    counts = json.loads((tmp_path / "metadata.json").read_text())["counts"]
    assert counts["failure_records"] == 1
    assert counts["failed_roots"] == 1
    assert counts["union_roots"] == 1


def test_discover_universe_accepts_zero_fixed_fee_and_rate():
    selected, failures = batch.discover_futures_universe(
        [_overview("rb2701", Exchange.SHFE)],
        config={"rb": _info(rate=0, slippage=0)},
    )

    assert failures == []
    assert selected[0]["fixed_fee"] == 0
    assert selected[0]["rate"] == 0


@pytest.mark.parametrize("ticks", [1, 2])
def test_make_engine_uses_frozen_cost_and_contract_parameters(ticks):
    engine = batch._make_engine(_contract(), ticks)

    assert engine.vt_symbol == "rb2701.SHFE"
    assert engine.interval == Interval.MINUTE
    assert engine.start == batch.START
    assert engine.rate == 0.0001
    assert engine.slippage == ticks
    assert engine.size == 10
    assert engine.pricetick == 1
    assert engine.capital == batch.CAPITAL


def test_add_fixed_fees_is_per_executed_lot_without_size_multiplier():
    day = datetime(2026, 5, 6).date()
    df = pd.DataFrame(
        {"net_pnl": [100.0], "commission": [1.0], "slippage": [0.0]},
        index=[day],
    )
    trades = [
        SimpleNamespace(datetime=datetime(2026, 5, 6, 9, 1), volume=2),
        SimpleNamespace(datetime=datetime(2026, 5, 6, 10, 1), volume=1),
    ]

    batch.add_fixed_fees(df, trades, fixed_fee=3.0)

    assert df.loc[day, "commission"] == 10.0
    assert df.loc[day, "net_pnl"] == 91.0
    before = df.copy()
    batch.add_fixed_fees(df, trades, fixed_fee=0)
    pd.testing.assert_frame_equal(df, before)


def test_period_metrics_keep_legacy_accounting():
    df = pd.DataFrame(
        {
            "net_pnl": [100.0, -50.0],
            "commission": [10.0, 5.0],
            "slippage": [4.0, 1.0],
            "trade_count": [1, 1],
        },
        index=[datetime(2026, 5, 6).date(), datetime(2026, 5, 7).date()],
    )

    metrics = batch.calculate_period_metrics(df)

    assert metrics["total_net_pnl"] == 50
    assert metrics["gross_pnl"] == 70
    assert metrics["total_return"] == pytest.approx(0.025)
    assert metrics["max_ddpercent"] == pytest.approx(-50 / 200_100 * 100)
    assert metrics["commission"] == 15
    assert metrics["slippage"] == 5
    assert metrics["trade_count"] == 2
    assert metrics["days"] == 2
    assert metrics["solvency_ok"] is True
    assert metrics["solvency_status"] == "solvent"
    assert metrics["invalid_log_return_days"] == 0
    assert batch.get_research_period(datetime(2026, 8, 14).date()) == "train"
    assert batch.get_research_period(datetime(2026, 8, 15).date()) == "validation"
    assert batch.get_research_period(datetime(2026, 9, 16).date()) == "review"


def test_period_metrics_flags_insolvency_and_leaves_sharpe_undefined():
    df = pd.DataFrame(
        {
            "net_pnl": [-200_000.0, -100.0, 400.0],
            "commission": [0.0, 0.0, 0.0],
            "slippage": [0.0, 0.0, 0.0],
            "trade_count": [1, 1, 1],
        },
        index=[datetime(2026, 5, 6).date(), datetime(2026, 5, 7).date(), datetime(2026, 5, 8).date()],
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        metrics = batch.calculate_period_metrics(df)

    assert metrics["solvency_ok"] is False
    assert metrics["solvency_status"] == "insolvent"
    assert metrics["nonpositive_balance_days"] == 2
    assert metrics["nonpositive_pre_balance_days"] == 2
    assert metrics["invalid_log_return_days"] == 3
    assert metrics["min_balance"] == -100
    assert metrics["min_pre_balance"] == -100
    assert np.isnan(metrics["sharpe_ratio"])
    assert metrics["total_net_pnl"] == -199_700
    assert metrics["total_return"] == pytest.approx(-99.85)
    assert np.isfinite(metrics["max_ddpercent"])


def _session_bars_with_count(contract: dict, count: int) -> list:
    first, final = batch._expected_session_bounds(contract)
    return [SimpleNamespace(datetime=first)] + [
        SimpleNamespace(datetime=first + timedelta(minutes=index))
        for index in range(1, count - 1)
    ] + [SimpleNamespace(datetime=final)]


def test_load_bars_accepts_27225_day_only_bars_with_exact_session_bounds(monkeypatch):
    from vnpy.trader.setting import SETTINGS

    monkeypatch.setitem(SETTINGS, "database.name", "sqlite")
    contract = _contract(root="AP", vt_symbol="AP701.CZCE", exchange=Exchange.CZCE.value)
    bars = _session_bars_with_count(contract, 27_225)
    warmup = [SimpleNamespace(datetime=datetime(2026, 3, 17, 9, 0))]
    database = SimpleNamespace(load_bar_data=lambda **kwargs: [*warmup, *bars])
    monkeypatch.setattr("vnpy.trader.database.get_database", lambda: database)

    loaded_warmup, loaded = batch._load_bars(contract)

    assert batch.MIN_MAIN_BARS == 40 * 60 == 2_400
    assert len(loaded) == 27_225
    assert loaded_warmup == warmup
    assert loaded[0].datetime == datetime(2026, 5, 6, 9, 0)
    assert loaded[-1].datetime == datetime(2026, 10, 30, 14, 59)


def test_load_bars_still_rejects_fewer_than_2400_bars(monkeypatch):
    from vnpy.trader.setting import SETTINGS

    monkeypatch.setitem(SETTINGS, "database.name", "sqlite")
    contract = _contract(root="AP", vt_symbol="AP701.CZCE", exchange=Exchange.CZCE.value)
    bars = _session_bars_with_count(contract, 2_399)
    warmup = [SimpleNamespace(datetime=datetime(2026, 3, 17, 9, 0))]
    database = SimpleNamespace(load_bar_data=lambda **kwargs: [*warmup, *bars])
    monkeypatch.setattr("vnpy.trader.database.get_database", lambda: database)

    with pytest.raises(RuntimeError, match="2400"):
        batch._load_bars(contract)


def test_period_metrics_solvency_resets_at_period_boundary():
    # Earlier periods may be insolvent, but this reset period starts again at
    # CAPITAL; whole-main insolvency must not be propagated into it.
    df = pd.DataFrame(
        {
            "net_pnl": [-100_000.0, 10_000.0],
            "commission": [0.0, 0.0],
            "slippage": [0.0, 0.0],
            "trade_count": [1, 1],
        },
        index=[datetime(2026, 8, 17).date(), datetime(2026, 8, 18).date()],
    )

    metrics = batch.calculate_period_metrics(df)

    assert metrics["solvency_status"] == "solvent"
    assert metrics["nonpositive_balance_days"] == 0
    assert metrics["invalid_log_return_days"] == 0
    assert np.isfinite(metrics["sharpe_ratio"])


@pytest.mark.parametrize(
    ("messages", "consumed"),
    [
        (["触发异常，回测终止"], datetime(2026, 10, 30, 15, 0)),
        ([], datetime(2026, 10, 30, 14, 59)),
        ([], None),
    ],
)
def test_completion_check_rejects_exception_or_missing_final_bar(messages, consumed):
    strategy = SimpleNamespace(last_bar_datetime=consumed)
    final_bar = SimpleNamespace(datetime=datetime(2026, 10, 30, 15, 0))

    with pytest.raises(RuntimeError):
        batch.ensure_backtest_completed(messages, strategy, final_bar)


def _bar(symbol: str, dt: datetime, close: float) -> BarData:
    return BarData(
        symbol=symbol,
        exchange=Exchange.SHFE,
        datetime=dt,
        interval=Interval.MINUTE,
        open_price=close - 0.2,
        high_price=close + 1,
        low_price=close - 1,
        close_price=close,
        volume=100,
        gateway_name="BACKTESTING",
    )


def _controlled_bars() -> tuple[list[BarData], list[BarData]]:
    warmup_start = datetime(2026, 4, 29, 9, 0)
    main_start = datetime(2026, 5, 6, 9, 0)
    warmup = [
        _bar("rb2701", warmup_start + timedelta(minutes=index), 3500 + np.sin(index / 4))
        for index in range(120)
    ]
    bars = [
        _bar(
            "rb2701",
            main_start + timedelta(minutes=index),
            3500 + index * 0.05 + np.sin(index / 5) * 4,
        )
        for index in range(180)
    ]
    return warmup, bars


def test_run_contract_real_engine_has_six_models_three_periods_and_one_data_load(monkeypatch):
    warmup, bars = _controlled_bars()
    loads = []

    def fake_load(contract):
        loads.append(contract["vt_symbol"])
        return warmup, bars

    monkeypatch.setattr(batch, "_load_bars", fake_load)
    result = batch.run_contract(_contract(), slippage_ticks=1)
    rows = result["rows"]

    assert loads == ["rb2701.SHFE"]
    assert len(rows) == 18
    assert [row["model"] for row in rows] == [
        model for model in MODEL_NAMES for _ in range(3)
    ]
    assert [row["period"] for row in rows] == ["train", "validation", "review"] * 6
    assert {row["fixed_size"] for row in rows} == {1}
    assert {row["price_slippage"] for row in rows} == {1}
    assert {row["fixed_fee"] for row in rows} == {3}
    assert {row["bars_loaded"] for row in rows} == {180}
    assert {row["warmup_bars"] for row in rows} == {120}
    assert {row["last_bar"] for row in rows} == {str(bars[-1].datetime)}
    assert tuple(result["signals"]) == MODEL_NAMES
    assert tuple(result["trades"]) == MODEL_NAMES
    assert all(result["signals"][model] for model in MODEL_NAMES)


def test_load_bars_rejects_late_main_data_despite_count_and_final_day(monkeypatch):
    from vnpy.trader.setting import SETTINGS

    monkeypatch.setitem(SETTINGS, "database.name", "sqlite")
    final_bar = datetime(2026, 10, 30, 15, 0)
    late_bars = [
        SimpleNamespace(datetime=final_bar - timedelta(minutes=offset))
        for offset in reversed(range(30_000))
    ]
    warmup = [SimpleNamespace(datetime=datetime(2026, 3, 17, 9, 0))]
    database = SimpleNamespace(
        load_bar_data=lambda **kwargs: [*warmup, *late_bars],
    )
    monkeypatch.setattr("vnpy.trader.database.get_database", lambda: database)

    with pytest.raises(RuntimeError, match="主区间起点"):
        batch._load_bars(_contract())


def test_load_bars_rejects_early_final_session_bar(monkeypatch):
    from vnpy.trader.setting import SETTINGS

    monkeypatch.setitem(SETTINGS, "database.name", "sqlite")
    first_bar = datetime(2026, 5, 6, 9, 0)
    final_bar = datetime(2026, 10, 30, 9, 0)
    bars = [SimpleNamespace(datetime=first_bar)] + [
        SimpleNamespace(datetime=final_bar - timedelta(minutes=offset))
        for offset in reversed(range(29_999))
    ]
    warmup = [SimpleNamespace(datetime=datetime(2026, 3, 17, 9, 0))]
    database = SimpleNamespace(load_bar_data=lambda **kwargs: [*warmup, *bars])
    monkeypatch.setattr("vnpy.trader.database.get_database", lambda: database)

    with pytest.raises(RuntimeError, match="最终交易时段"):
        batch._load_bars(_contract())


@pytest.mark.parametrize(
    ("root", "vt_symbol", "exchange", "expected_first", "expected_final"),
    [
        ("rb", "rb2701.SHFE", "SHFE", datetime(2026, 5, 6, 9), datetime(2026, 10, 30, 22, 59)),
        ("au", "au2612.SHFE", "SHFE", datetime(2026, 5, 6, 9), datetime(2026, 10, 31, 2, 29)),
        ("cu", "cu2612.SHFE", "SHFE", datetime(2026, 5, 6, 9), datetime(2026, 10, 31, 0, 59)),
        ("a", "a2701.DCE", "DCE", datetime(2026, 5, 6, 9), datetime(2026, 10, 30, 22, 59)),
        ("MA", "MA701.CZCE", "CZCE", datetime(2026, 5, 6, 9), datetime(2026, 10, 30, 22, 59)),
        ("AP", "AP701.CZCE", "CZCE", datetime(2026, 5, 6, 9), datetime(2026, 10, 30, 14, 59)),
        ("IF", "IF2612.CFFEX", "CFFEX", datetime(2026, 5, 6, 9, 30), datetime(2026, 10, 30, 14, 59)),
        ("T", "T2612.CFFEX", "CFFEX", datetime(2026, 5, 6, 9, 30), datetime(2026, 10, 30, 15, 14)),
        ("si", "si2701.GFEX", "GFEX", datetime(2026, 5, 6, 9), datetime(2026, 10, 30, 14, 59)),
        ("ec", "ec2612.INE", "INE", datetime(2026, 5, 6, 9), datetime(2026, 10, 30, 14, 59)),
        ("sc", "sc2612.INE", "INE", datetime(2026, 5, 6, 9), datetime(2026, 10, 31, 2, 29)),
    ],
)
def test_expected_session_bounds_use_exchange_and_root_specific_close(
    root, vt_symbol, exchange, expected_first, expected_final,
):
    contract = _contract(root=root, vt_symbol=vt_symbol, exchange=exchange)
    assert batch._expected_session_bounds(contract) == (expected_first, expected_final)


def test_run_contract_rejects_external_parameter_override(monkeypatch):
    warmup, bars = _controlled_bars()
    monkeypatch.setattr(batch, "_load_bars", lambda contract: (warmup, bars))

    def override_params(self, setting, vt_symbol):
        setting["fixed_size"] = 2

    monkeypatch.setattr(BayesianQStrategy, "_fill_optimized_params", override_params)

    with pytest.raises(RuntimeError, match="外部配置覆盖"):
        batch.run_contract(_contract(), slippage_ticks=1, models=("nqqe",))


def _fake_result(contract: dict, ticks: int) -> dict:
    rows = [
        {
            "root": contract["root"],
            "vt_symbol": contract["vt_symbol"],
            "model": model,
            "period": period,
            "slippage_ticks": ticks,
            "fixed_size": 1,
        }
        for model in MODEL_NAMES
        for period in ("train", "validation", "review")
    ]
    return {
        "rows": rows,
        "signals": {
            model: [{"datetime": "2026-05-06 10:00:00", "model": model}]
            for model in MODEL_NAMES
        },
        "trades": {model: [] for model in MODEL_NAMES},
        "metadata": {
            "root": contract["root"],
            "vt_symbol": contract["vt_symbol"],
            "models": list(MODEL_NAMES),
            "slippage_ticks": ticks,
            "last_bar": "2026-10-30 15:00:00",
        },
    }


def test_fill_audit_rejects_mixed_fills_and_has_explicit_zero_trade_policy():
    with pytest.raises(RuntimeError, match="2 笔成交时序异常"):
        batch._audit_trade_fills(
            [
                {"next_minute_fill": True},
                {"next_minute_fill": False},
                {"next_minute_fill": False},
            ],
            vt_symbol="rb2701.SHFE",
            model="nqqe",
        )

    assert batch._audit_trade_fills([]) == {
        "next_minute_fill_verified": False,
        "fill_audit_status": "no_trades",
        "invalid_fill_count": 0,
    }
    assert batch._audit_trade_fills([{"next_minute_fill": True}]) == {
        "next_minute_fill_verified": True,
        "fill_audit_status": "verified",
        "invalid_fill_count": 0,
    }


def test_run_metadata_aggregates_fill_verification_with_all(tmp_path):
    batch._update_run_metadata(
        tmp_path,
        {
            "rows": [
                {"vt_symbol": "a2701.DCE", "next_minute_fill_verified": True},
                {"vt_symbol": "a2701.DCE", "next_minute_fill_verified": False},
            ],
            "failures": [],
        },
        1,
        MODEL_NAMES,
    )

    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["last_run"]["next_minute_fill_verified"] is False


def test_run_batch_persists_each_contract_before_next_and_records_failure(tmp_path):
    contracts = [_contract(), _contract(root="hc", vt_symbol="hc2701.SHFE")]
    calls = []

    def runner(contract, ticks, models):
        calls.append(contract["vt_symbol"])
        if len(calls) == 2:
            # The first contract must already be durable before the second starts.
            assert len(pd.read_csv(tmp_path / "batch_detail.csv")) == 18
            raise RuntimeError("synthetic engine failure")
        return _fake_result(contract, ticks)

    result = batch.run_batch(
        contracts,
        slippage_ticks=1,
        output_dir=tmp_path,
        runner=runner,
    )

    assert len(pd.read_csv(tmp_path / "batch_detail.csv")) == 18
    failures = pd.read_csv(tmp_path / "contract_failures.csv")
    assert failures["reason"].tolist() == ["backtest_failed"]
    assert failures["vt_symbol"].tolist() == ["hc2701.SHFE"]
    assert "synthetic engine failure" in failures["detail"].iloc[0]
    assert len(result["rows"]) == 18
    assert len(list(tmp_path.glob("signals_*_slippage1.csv"))) == 6
    assert len(list(tmp_path.glob("trades_*_slippage1.csv"))) == 6


def test_failed_same_cost_retry_prunes_prior_success_detail_and_artifacts(tmp_path):
    contract = _contract()
    batch.run_batch(
        [contract],
        slippage_ticks=1,
        output_dir=tmp_path,
        runner=lambda contract, ticks, models: _fake_result(contract, ticks),
    )
    assert len(pd.read_csv(tmp_path / "batch_detail.csv")) == 18

    def fail(contract, ticks, models):
        raise RuntimeError("retry failed")

    batch.run_batch(
        [contract], slippage_ticks=1, output_dir=tmp_path, runner=fail,
    )

    assert pd.read_csv(tmp_path / "batch_detail.csv").empty
    failures = pd.read_csv(tmp_path / "contract_failures.csv")
    assert failures["reason"].tolist() == ["backtest_failed"]
    assert failures["slippage_ticks"].tolist() == [1]
    assert not list(tmp_path.glob("signals_rb2701_SHFE_*_slippage1.csv"))
    assert not list(tmp_path.glob("trades_rb2701_SHFE_*_slippage1.csv"))
    assert not (tmp_path / "rb2701_SHFE-slippage1-metadata.json").exists()


@pytest.mark.parametrize("artifact_prefix", ["signals_", "trades_"])
def test_post_detail_save_failure_prunes_partial_result_and_records_traceback(
    tmp_path, monkeypatch, artifact_prefix,
):
    contract = _contract()
    original_write_frame = batch._write_frame

    def injected_write(path, records, fields):
        if path.name.startswith(artifact_prefix):
            raise OSError(f"injected post-detail {artifact_prefix} write failure")
        return original_write_frame(path, records, fields)

    monkeypatch.setattr(batch, "_write_frame", injected_write)
    batch.run_batch(
        [contract],
        slippage_ticks=1,
        output_dir=tmp_path,
        runner=lambda contract, ticks, models: _fake_result(contract, ticks),
    )

    assert pd.read_csv(tmp_path / "batch_detail.csv").empty
    failures = pd.read_csv(tmp_path / "contract_failures.csv")
    assert failures["exception_type"].tolist() == ["OSError"]
    assert f"injected post-detail {artifact_prefix} write failure" in failures["traceback"].iloc[0]
    assert not list(tmp_path.glob("signals_rb2701_SHFE_*_slippage1.csv"))
    assert not list(tmp_path.glob("trades_rb2701_SHFE_*_slippage1.csv"))
    assert not (tmp_path / "rb2701_SHFE-slippage1-metadata.json").exists()
    run_metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert run_metadata["last_run"]["detail_rows"] == 0
    assert run_metadata["last_run"]["errors"][0]["exception_type"] == "OSError"
    assert "Traceback" in run_metadata["last_run"]["errors"][0]["traceback"]


def test_post_detail_metadata_failure_prunes_complete_prefix(tmp_path, monkeypatch):
    contract = _contract()
    original_write_json = batch._write_json

    def injected_write(path, value):
        if path.name == "rb2701_SHFE-slippage1-metadata.json":
            raise OSError("injected post-detail metadata write failure")
        return original_write_json(path, value)

    monkeypatch.setattr(batch, "_write_json", injected_write)
    batch.run_batch(
        [contract],
        slippage_ticks=1,
        output_dir=tmp_path,
        runner=lambda contract, ticks, models: _fake_result(contract, ticks),
    )

    assert pd.read_csv(tmp_path / "batch_detail.csv").empty
    assert not list(tmp_path.glob("signals_rb2701_SHFE_*_slippage1.csv"))
    assert not list(tmp_path.glob("trades_rb2701_SHFE_*_slippage1.csv"))
    assert not (tmp_path / "rb2701_SHFE-slippage1-metadata.json").exists()
    failures = pd.read_csv(tmp_path / "contract_failures.csv")
    assert failures["exception_type"].tolist() == ["OSError"]
    assert "metadata write failure" in failures["traceback"].iloc[0]


def test_run_batch_preserves_other_cost_failure_and_supersedes_same_cost(tmp_path):
    contract = _contract()

    def fail(contract, ticks, models):
        raise RuntimeError(f"cost {ticks} failed")

    batch.run_batch(
        [contract], slippage_ticks=1, output_dir=tmp_path, runner=fail,
    )
    first_failures = pd.read_csv(tmp_path / "contract_failures.csv")
    assert first_failures["slippage_ticks"].tolist() == [1]

    # 每次 CLI 都会先刷新 inventory；这不得抹掉另一成本已有的运行失败。
    batch.write_inventory_outputs([], [], [], output_dir=tmp_path)
    batch.run_batch(
        [contract],
        slippage_ticks=2,
        output_dir=tmp_path,
        runner=lambda contract, ticks, models: _fake_result(contract, ticks),
    )
    preserved = pd.read_csv(tmp_path / "contract_failures.csv")
    assert preserved["reason"].tolist() == ["backtest_failed"]
    assert preserved["slippage_ticks"].tolist() == [1]
    assert set(pd.read_csv(tmp_path / "batch_detail.csv")["slippage_ticks"]) == {2}

    batch.run_batch(
        [contract],
        slippage_ticks=1,
        output_dir=tmp_path,
        runner=lambda contract, ticks, models: _fake_result(contract, ticks),
    )
    assert pd.read_csv(tmp_path / "contract_failures.csv").empty
    detail = pd.read_csv(tmp_path / "batch_detail.csv")
    assert len(detail) == 36
    assert set(detail["slippage_ticks"]) == {1, 2}


def test_save_result_replaces_empty_inventory_placeholder_without_future_warning(tmp_path):
    batch.write_inventory_outputs([], [], [], output_dir=tmp_path)
    result = _fake_result(_contract(), 1)
    for row in result["rows"]:
        for field in batch.DETAIL_FIELDS:
            row.setdefault(field, 0.0)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        batch.save_contract_result(tmp_path, result)

    assert len(pd.read_csv(tmp_path / "batch_detail.csv")) == 18


def test_inventory_outputs_keep_headers_and_metadata_with_zero_failures(tmp_path):
    batch.write_inventory_outputs([], [], [], output_dir=tmp_path)

    inventory = pd.read_csv(tmp_path / "contract_inventory.csv")
    failures = pd.read_csv(tmp_path / "contract_failures.csv")
    assert inventory.empty
    assert failures.empty
    assert list(inventory.columns) == batch.INVENTORY_FIELDS
    assert list(failures.columns) == batch.FAILURE_FIELDS

    import json

    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["overview_snapshot"] == []
    assert metadata["models"] == list(MODEL_NAMES)
    assert metadata["fixed_size"] == 1
    assert metadata["costs"]["slippage_ticks"] == [1, 2]
    assert set(metadata["git"]) == {"head", "dirty"}


def test_mysql_overview_is_select_only_and_retains_invalid_exchange(monkeypatch):
    import vnpy_mysql.mysql_database as mysql
    from vnpy.trader.setting import SETTINGS

    valid = SimpleNamespace(
        symbol="rb2701",
        exchange="SHFE",
        interval="1m",
        count=40_000,
        start=datetime(2026, 3, 1),
        end=datetime(2026, 11, 10),
    )
    invalid = SimpleNamespace(
        symbol="BTCUSDT",
        exchange="BINANCE",
        interval="1m",
        count=10,
        start=datetime(2026, 3, 1),
        end=datetime(2026, 11, 10),
    )
    query = Mock()
    query.filter.return_value = query
    query.all.return_value = [valid, invalid]
    session = Mock()
    session.query.return_value = query
    database = SimpleNamespace(
        session=session,
        get_bar_overview=Mock(return_value=[]),
        init_bar_overview=Mock(),
    )
    factory = Mock(return_value=database)
    create_all = Mock()
    monkeypatch.setitem(SETTINGS, "database.name", "mysql")
    monkeypatch.setattr("vnpy.trader.database.get_database", factory)
    monkeypatch.setattr(mysql, "SessionLocal", Mock(return_value=session))
    monkeypatch.setattr(mysql.Base.metadata, "create_all", create_all)

    overviews, recovery = batch._load_database_overviews()

    assert [row.symbol for row in overviews] == ["rb2701"]
    assert recovery["source"] == "mysql_select_only_1m_overview"
    assert recovery["public_overview"]["called"] is False
    assert recovery["invalid_rows"][0]["exchange"] == "BINANCE"
    factory.assert_not_called()
    database.get_bar_overview.assert_not_called()
    database.init_bar_overview.assert_not_called()
    create_all.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.init_bar_overview.assert_not_called()
    session.close.assert_called_once_with()
