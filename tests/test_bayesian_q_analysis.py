from __future__ import annotations

import math

import pandas as pd
import pytest

from core.indicators.calculators.bayesian_q_calculator import MODEL_NAMES
from scripts.bayesian_q_analysis import (
    BAYESIAN_Q_MODELS,
    PERIODS,
    evaluate_filter_gates,
    event_study,
    formula_audit,
    summarize_results,
    validate_results,
    _plot_events,
)


ROOTS = ("a", "b")


def _inventory(roots=ROOTS) -> pd.DataFrame:
    return pd.DataFrame([
        {"root": root, "vt_symbol": f"{root}2701.DCE"} for root in roots
    ])


def _complete_detail(roots=ROOTS, costs=(1, 2)) -> pd.DataFrame:
    rows = []
    for cost in costs:
        for root in roots:
            for model in MODEL_NAMES:
                for period in PERIODS:
                    rows.append({
                        "root": root,
                        "vt_symbol": f"{root}2701.DCE",
                        "model": model,
                        "period": period,
                        "slippage_ticks": cost,
                        "total_net_pnl": 100.0,
                        "max_ddpercent": -2.0,
                        "sharpe_ratio": 1.0,
                        "trade_count": 4,
                    })
    return pd.DataFrame(rows)


def _failure(root: str, cost=None, reason="backtest_failed") -> dict:
    return {
        "root": root,
        "vt_symbol": f"{root}2701.DCE",
        "slippage_ticks": cost,
        "reason": reason,
        "detail": reason,
    }


def test_validate_results_accepts_complete_unique_grid_and_dynamic_valid_n():
    detail = _complete_detail()
    detail = detail[~((detail["root"] == "b") & (detail["slippage_ticks"] == 2))]
    failures = pd.DataFrame([
        _failure("c", reason="incomplete_coverage"),
        _failure("b", 2),
    ])

    result = validate_results(
        detail, _inventory(), failures, expected_total_roots=3,
    )

    assert result["total_roots"] == 3
    assert result["valid_n_by_cost"] == {1: 2, 2: 1}
    assert result["runtime_failures"] == 1
    assert result["detail_rows"] == 54


def test_validate_results_rejects_duplicate_model_root_period_cost():
    detail = _complete_detail()
    duplicate = pd.concat([detail, detail.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="重复"):
        validate_results(
            duplicate, _inventory(), pd.DataFrame(), expected_total_roots=2,
        )


@pytest.mark.parametrize("missing", ["model", "root", "cost"])
def test_validate_results_rejects_missing_model_root_or_cost(missing):
    detail = _complete_detail()
    if missing == "model":
        detail = detail[~((detail["root"] == "a") & (detail["model"] == "nqqe"))]
    elif missing == "root":
        detail = detail[~((detail["root"] == "b") & (detail["slippage_ticks"] == 1))]
    else:
        detail = detail[detail["slippage_ticks"] == 1]

    with pytest.raises(ValueError, match="完整|成本"):
        validate_results(
            detail, _inventory(), pd.DataFrame(), expected_total_roots=2,
        )


def test_validate_results_requires_full_root_accounting_and_explicit_runtime_failure():
    with pytest.raises(ValueError, match="品种全集"):
        validate_results(
            _complete_detail(), _inventory(), pd.DataFrame(), expected_total_roots=3,
        )

    missing_b_cost_two = _complete_detail()
    missing_b_cost_two = missing_b_cost_two[
        ~((missing_b_cost_two["root"] == "b") & (missing_b_cost_two["slippage_ticks"] == 2))
    ]
    with pytest.raises(ValueError, match="完整"):
        validate_results(
            missing_b_cost_two,
            _inventory(),
            pd.DataFrame([_failure("c", reason="incomplete_coverage")]),
            expected_total_roots=3,
        )


def _comparison_detail(roots=("a", "b", "c"), costs=(1, 2)) -> pd.DataFrame:
    rows = []
    for cost in costs:
        for root in roots:
            for period in PERIODS:
                rows.append({
                    "root": root, "model": "nqqe", "period": period,
                    "slippage_ticks": cost, "total_net_pnl": 100.0,
                    "sharpe_ratio": 1.0, "max_ddpercent": -5.0,
                    "trade_count": 10,
                })
                for model in BAYESIAN_Q_MODELS:
                    rows.append({
                        "root": root, "model": model, "period": period,
                        "slippage_ticks": cost, "total_net_pnl": 200.0,
                        "sharpe_ratio": 2.0, "max_ddpercent": -4.0,
                        "trade_count": 4,
                    })
    return pd.DataFrame(rows)


def _review_trades(roots=("a", "b", "c"), costs=(1, 2), active=True) -> pd.DataFrame:
    rows = []
    for cost in costs:
        for root in roots:
            for index in range(10):
                rows.append({
                    "root": root, "model": "nqqe", "slippage_ticks": cost,
                    "datetime": f"2026-09-{16 + index:02d} 10:00:00",
                    "offset": "开",
                })
            if active:
                for index in range(2):
                    rows.append({
                        "root": root, "model": "bayes_q_legacy",
                        "slippage_ticks": cost,
                        "datetime": f"2026-09-{16 + index:02d} 11:00:00",
                        "offset": "开",
                    })
    return pd.DataFrame(rows)


def test_filter_gates_use_ceil_two_thirds_and_all_required_metrics():
    detail = _comparison_detail()
    # N=3, threshold=ceil(2N/3)=2. Two roots improve net pnl, but only
    # one improves Sharpe, so a single-metric improvement cannot pass.
    mask = (
        (detail["model"] == "bayes_q_legacy")
        & (detail["root"] == "c")
        & (detail["slippage_ticks"] == 1)
    )
    detail.loc[mask, "total_net_pnl"] = 50.0
    sharpe_mask = (
        (detail["model"] == "bayes_q_legacy")
        & (detail["root"].isin(["b", "c"]))
        & (detail["slippage_ticks"] == 1)
    )
    detail.loc[sharpe_mask, "sharpe_ratio"] = 0.5

    gates = evaluate_filter_gates(detail, _review_trades())
    row = gates[
        (gates["model"] == "bayes_q_legacy")
        & (gates["period"] == "review")
        & (gates["slippage_ticks"] == 1)
    ].iloc[0]

    assert row["n_roots"] == 3
    assert row["required_roots"] == 2
    assert row["improved_net_pnl_roots"] == 2
    assert row["improved_net_pnl_pass"]
    assert not row["median_sharpe_pass"]
    assert not row["filter_pass"]
    assert math.ceil(2 * 4 / 3) == 3


def test_near_flat_filter_cannot_pass_even_with_better_performance():
    detail = _comparison_detail(costs=(1,))
    trades = _review_trades(costs=(1,), active=False)
    close_only = _review_trades(costs=(1,), active=True)
    close_only = close_only[close_only["model"] == "bayes_q_legacy"].copy()
    close_only["offset"] = "平"
    trades = pd.concat([trades, close_only], ignore_index=True)

    gates = evaluate_filter_gates(detail, trades)
    row = gates[gates["period"] == "review"].iloc[0]

    assert row["review_active_roots"] == 0
    assert row["review_open_entries"] == 0
    assert not row["review_activity_pass"]
    assert not row["filter_pass"]
    assert not row["candidate"]


def test_double_cost_reversal_fails_same_direction_conclusion():
    detail = _comparison_detail()
    reverse = (detail["model"] == "bayes_q_legacy") & (detail["slippage_ticks"] == 2)
    detail.loc[reverse, ["total_net_pnl", "sharpe_ratio", "max_ddpercent"]] = [0.0, 0.5, -8.0]

    gates = evaluate_filter_gates(detail, _review_trades())
    cost_one = gates[(gates["period"] == "review") & (gates["slippage_ticks"] == 1)].iloc[0]
    cost_two = gates[(gates["period"] == "review") & (gates["slippage_ticks"] == 2)].iloc[0]

    assert cost_one["filter_pass"]
    assert not cost_two["filter_pass"]
    assert not cost_one["double_cost_same_direction"]
    assert not cost_one["double_cost_pass"]
    assert not cost_two["double_cost_pass"]


def test_candidate_additionally_requires_profitable_breadth_and_positive_medians():
    detail = _comparison_detail(roots=("a", "b", "c", "d"), costs=(1,))
    trades = _review_trades(roots=("a", "b", "c", "d"), costs=(1,))
    pnl_by_root = {"a": -100.0, "b": 1.0, "c": 100.0, "d": 101.0}
    for root, pnl in pnl_by_root.items():
        mask = (detail["model"] == "bayes_q_legacy") & (detail["root"] == root)
        detail.loc[mask, "total_net_pnl"] = pnl
        detail.loc[(detail["model"] == "nqqe") & (detail["root"] == root), "total_net_pnl"] = -200.0

    row = evaluate_filter_gates(detail, trades).query("period == 'review'").iloc[0]

    assert row["required_roots"] == 3
    # Root a is not profitable; roots b/c/d are, so breadth passes.
    assert row["profitable_roots"] == 3
    assert row["profitable_roots_pass"]
    assert row["positive_median_net_pnl_pass"]
    assert row["candidate"]


def test_candidate_rejects_insufficient_profitable_breadth():
    detail = _comparison_detail(roots=("a", "b", "c", "d"), costs=(1,))
    trades = _review_trades(roots=("a", "b", "c", "d"), costs=(1,))
    for root, pnl in {"a": -100.0, "b": -1.0, "c": 100.0, "d": 101.0}.items():
        mask = (detail["model"] == "bayes_q_legacy") & (detail["root"] == root)
        detail.loc[mask, "total_net_pnl"] = pnl
        # nQQE=-100 is lower than every Bayesian Q value except root a ties;
        # adjust all baselines so all four still improve.
        detail.loc[(detail["model"] == "nqqe") & (detail["root"] == root), "total_net_pnl"] = -200.0

    row = evaluate_filter_gates(detail, trades).query("period == 'review'").iloc[0]

    assert row["profitable_roots"] == 2
    assert not row["profitable_roots_pass"]
    assert row["positive_median_net_pnl_pass"]
    assert not row["candidate"]


def test_summarize_results_reports_model_period_cost_medians_and_breadth():
    detail = _comparison_detail(costs=(1,))
    summary = summarize_results(detail)
    row = summary.query(
        "model == 'bayes_q_legacy' and period == 'review' and slippage_ticks == 1"
    ).iloc[0]

    assert row["n_roots"] == 3
    assert row["median_net_pnl"] == 200
    assert row["profitable_roots"] == 3
    assert row["profitable_ratio"] == 1
    assert row["median_sharpe_ratio"] == 2
    assert row["median_max_ddpercent"] == -4


def test_summary_discloses_insolvent_and_legacy_unrecomputed_roots():
    detail = _comparison_detail(costs=(1,))
    detail["solvency_status"] = "solvent"
    legacy = detail["model"] == "bayes_q_legacy"
    detail.loc[legacy & detail["root"].eq("a"), "solvency_status"] = "insolvent"
    detail.loc[legacy & detail["root"].eq("b"), "solvency_status"] = "legacy_not_recomputed"

    row = summarize_results(detail).query(
        "model == 'bayes_q_legacy' and period == 'review' and slippage_ticks == 1"
    ).iloc[0]

    assert row["insolvent_roots"] == 1
    assert row["solvency_unknown_roots"] == 1
    assert row["legacy_sharpe_provisional"]


def test_gate_marks_legacy_numeric_sharpe_and_pass_flag_provisional():
    detail = _comparison_detail(costs=(1,))
    detail["solvency_status"] = "solvent"
    detail.loc[detail["root"] == "a", "solvency_status"] = "legacy_not_recomputed"

    row = evaluate_filter_gates(detail, _review_trades(costs=(1,))).query(
        "model == 'bayes_q_legacy' and period == 'review'"
    ).iloc[0]

    assert row["legacy_sharpe_provisional"]
    assert row["median_sharpe_pass_provisional"]


def _signal_streams(root="a", cost=1, models=MODEL_NAMES) -> pd.DataFrame:
    rows = []
    for model in models:
        for index, close in enumerate([100.0, 110.0, 121.0, 130.0, 140.0, 150.0, 160.0, 170.0]):
            rows.append({
                "root": root,
                "vt_symbol": f"{root}2701.DCE",
                "slippage_ticks": cost,
                "datetime": f"2026-09-{16 + index // 4:02d} {10 + index % 4:02d}:00:00+08:00",
                "model": model,
                "close_price": close,
                "sma": 100.0,
                "basis": 100.0,
                "upper": 110.0,
                "sigma_up_legacy": [0.0, 1.2, 0.4, 0.5, 0.5, 0.5, 0.5, 0.5][index],
                "sigma_down_legacy": 0.25,
                "prime_legacy": 0.5,
                "sigma_up_fixed": 0.5,
                "sigma_down_fixed": 0.25,
                "prime_fixed": 0.5,
                "bayes_ready": True,
                "rsi": 50.0,
                "qqef": 50.0,
                "qqes": 50.0,
                "nqqe_ready": True,
                "nqqe_trend": "neutral",
                "bayes_legacy": 0,
                "bayes_fixed": 0,
                "nqqe": 1 if index == 0 else (-1 if index == 1 else 0),
                "bayes_q_legacy": 1 if index == 0 else 0,
                "bayes_q_fixed": -1 if index == 1 else 0,
                "sma_momentum": 0,
            })
    return pd.DataFrame(rows)


def test_formula_audit_uses_one_canonical_stream_and_recomputes_actual_ratios():
    signals = _signal_streams()
    formula, counts = formula_audit(signals)

    legacy = formula.query("root == 'a' and field == 'sigma_up_legacy'").iloc[0]
    assert legacy["row_count"] == 8  # not 8 rows × six duplicate model streams
    assert legacy["minimum"] == 0
    assert legacy["maximum"] == pytest.approx(1.2)
    assert legacy["out_of_range_count"] == 1
    assert legacy["out_of_range_ratio"] == pytest.approx(1 / 8)
    assert legacy["zero_count"] == 1
    assert legacy["zero_ratio"] == pytest.approx(1 / 8)
    assert counts.query("model == 'nqqe'")["long_signals"].iloc[0] == 1
    assert counts.query("model == 'nqqe'")["short_signals"].iloc[0] == 1
    assert counts.query("model == 'bayes_q_legacy'")["total_signals"].iloc[0] == 1


def test_formula_audit_rejects_shared_state_mismatch_across_models():
    signals = _signal_streams()
    mask = (signals["model"] == "bayes_fixed") & (signals.index % 8 == 0)
    signals.loc[mask, "sigma_up_legacy"] = 0.9

    with pytest.raises(ValueError, match="共享状态"):
        formula_audit(signals)


def test_event_study_uses_one_tick_canonical_crosses_and_future_hourly_closes():
    signals = pd.concat([
        _signal_streams(),
        _signal_streams(cost=2),
    ], ignore_index=True)

    detail = event_study(signals, detailed=True)
    accepted = detail.query(
        "model == 'bayes_q_legacy' and horizon == 1 and status == 'accepted'"
    ).iloc[0]
    rejected = detail.query(
        "model == 'bayes_q_legacy' and horizon == 1 and status == 'rejected'"
    ).iloc[0]

    assert accepted["period"] == "review"
    assert accepted["direction"] == 1
    assert accepted["forward_return"] == pytest.approx(0.1)
    assert rejected["direction"] == -1
    assert rejected["forward_return"] == pytest.approx(-0.1)

    summary = event_study(signals)
    legacy_h1 = summary.query(
        "model == 'bayes_q_legacy' and period == 'review' and horizon == 1"
    ).set_index("status")
    assert legacy_h1.loc["accepted", "count"] == 1
    assert legacy_h1.loc["rejected", "count"] == 1
    assert legacy_h1.loc["accepted", "hit_rate"] == 1
    assert legacy_h1.loc["rejected", "hit_rate"] == 0
    assert set(summary["horizon"]) == {1, 4}
    assert len(detail) == 8  # two crosses × two Q models × two horizons; no cost/model duplication


def test_event_plot_accepts_summary_without_ambiguous_index(tmp_path):
    signals = _signal_streams()
    summary = event_study(signals)
    output = tmp_path / "event.png"

    _plot_events(summary, output)

    assert output.exists()
    assert output.stat().st_size > 0


def test_bayesian_q_models_are_only_the_two_pre_registered_filters():
    assert BAYESIAN_Q_MODELS == ("bayes_q_legacy", "bayes_q_fixed")
