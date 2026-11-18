#!/usr/bin/env python3
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LassoCV

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lasso_factor_selection_research import (
    ALPHAS, FACTORS, LABEL_HORIZON, TRAIN_END,
    build_sample, cs_zscore, load_panel, make_date_cv, period_metrics, run_backtest,
)
from scripts.lasso_portfolio_optimization import (
    PortfolioConfig, run_portfolio_backtest,
)

RESULT_DATE = "2026-11-06"
OUT_DIR = PROJECT_ROOT / "research" / "lasso-portfolio-data"
IMAGE_DIR = PROJECT_ROOT / "articles" / "images"
CONFIGS = [
    PortfolioConfig("B_actual_top20", 20, 20),
    PortfolioConfig("C_buffer50", 50, 100),
    PortfolioConfig("D_liquid50", 50, 100, liquidity_pct=0.20),
    PortfolioConfig("E_voltarget50", 50, 100, liquidity_pct=0.20, vol_target=0.12),
]


def build_daily_returns(panel: pd.DataFrame) -> dict[str, pd.Series]:
    panel = panel.sort_values(["symbol", "trade_date"]).copy()
    panel["daily_ret"] = panel.groupby("symbol")["close"].pct_change()
    return {
        symbol: df.set_index("trade_date")["daily_ret"].dropna()
        for symbol, df in panel.groupby("symbol")
    }


def train_and_score(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    market_dates = sorted(panel.loc[
        (panel["trade_date"] >= "2021-01-01") & (panel["trade_date"] <= TRAIN_END),
        "trade_date",
    ].unique())
    purge_start = market_dates[-LABEL_HORIZON]
    sample = build_sample(panel).dropna(subset=FACTORS, how="any").copy()
    sample = cs_zscore(sample, FACTORS)
    train = sample[sample["trade_date"] < purge_start].dropna(
        subset=[f"fwd{LABEL_HORIZON}"],
    ).copy()
    train = cs_zscore(train, [f"fwd{LABEL_HORIZON}"])
    train = train.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    X = train[FACTORS].to_numpy(dtype=np.float64)
    y = train[f"fwd{LABEL_HORIZON}"].to_numpy(dtype=np.float64)
    lasso = LassoCV(
        alphas=ALPHAS, cv=make_date_cv(train), fit_intercept=False,
        max_iter=5000, tol=1e-4, selection="cyclic",
    )
    lasso.fit(X, y)
    if abs(lasso.alpha_ - 0.0074438030132516885) > 1e-12:
        raise RuntimeError(f"Frozen alpha mismatch: {lasso.alpha_}")
    if int(np.sum(np.abs(lasso.coef_) > 1e-8)) != 8:
        raise RuntimeError("Frozen Lasso no longer retains eight factors")
    inference = sample[sample["is_rebal"]].copy().reset_index(drop=True)
    inference["lasso_score"] = lasso.predict(
        inference[FACTORS].to_numpy(dtype=np.float64),
    )
    return inference, train


def add_ic(result: pd.DataFrame, inference: pd.DataFrame) -> pd.DataFrame:
    values = []
    for row in result.itertuples():
        snap = inference[inference["trade_date"] == row.date].dropna(
            subset=["hold_ret", f"fwd{LABEL_HORIZON}"],
        )
        values.append(snap["lasso_score"].corr(
            snap[f"fwd{LABEL_HORIZON}"], method="spearman",
        ))
    result = result.copy()
    result["ic"] = values
    return result


def metrics_by_period(result: pd.DataFrame) -> dict:
    return {
        period: period_metrics(result[result["period"] == period])
        for period in ["train", "validation", "review"]
    }


def save_figures(all_results: pd.DataFrame) -> None:
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    review = all_results[all_results["period"] == "review"]
    for kind, filename, title in [
        ("nav", "lasso-portfolio-equity.png", "Lasso组合优化：二次验证段净值"),
        ("drawdown", "lasso-portfolio-drawdown.png", "Lasso组合优化：二次验证段回撤"),
    ]:
        fig, ax = plt.subplots(figsize=(11, 5.8))
        for model, part in review.groupby("model"):
            part = part.sort_values("date")
            nav = (1 + part["net"]).cumprod()
            values = nav if kind == "nav" else nav / nav.cummax() - 1
            ax.plot(part["date"], values, label=model, linewidth=1.8)
        ax.set_title(title)
        ax.legend(frameon=False, fontsize=8)
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(IMAGE_DIR / filename, dpi=180)
        plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    panel, _ = load_panel()
    returns_by_symbol = build_daily_returns(panel)
    inference, _ = train_and_score(panel)
    baseline = run_backtest(inference, "lasso_score")
    baseline["model"] = "A_original_top20"
    expected_baseline = {
        "train": {"total": 1.032835357984268, "max_drawdown": -0.3957938223790598, "mean_ic": 0.10968853282992576},
        "validation": {"total": 0.4899777536264742, "max_drawdown": -0.18439494849324456, "mean_ic": 0.06109755666557217},
        "review": {"total": 1.0222340243259112, "max_drawdown": -0.2603020018049528, "mean_ic": 0.11247398737717516},
    }
    for period, expected in expected_baseline.items():
        actual = period_metrics(baseline[baseline["period"] == period])
        for metric, expected_value in expected.items():
            if abs(actual[metric] - expected_value) > 1e-10:
                raise RuntimeError(
                    f"Baseline mismatch: {period}/{metric}={actual[metric]} vs {expected_value}"
                )

    results = [baseline]
    for config in CONFIGS:
        result = run_portfolio_backtest(inference, returns_by_symbol, config)
        results.append(add_ic(result, inference))
    all_results = pd.concat(results, ignore_index=True, sort=False)
    all_results.to_csv(OUT_DIR / f"Lasso组合优化明细-{RESULT_DATE}.csv", index=False)

    summary = {
        model: metrics_by_period(part)
        for model, part in all_results.groupby("model")
    }
    e_review = summary["E_voltarget50"]["review"]
    summary["success"] = {
        "drawdown_better_than_20pct": e_review["max_drawdown"] > -0.20,
        "sharpe_at_least_0_98": e_review["sharpe"] >= 0.98,
        "return_above_equal_weight_25_65pct": e_review["total"] > 0.2565,
        "evidence_status": "secondary_validation_only",
    }
    (OUT_DIR / f"Lasso组合优化核心结果-{RESULT_DATE}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    lines = [
        "# Lasso 组合优化回测报告", "",
        "> 2025-2026仅作二次验证，不是全新样本外；五组预登记结果全部披露。", "",
        "| 组别 | 分段 | 累计收益 | 最大回撤 | 夏普 | 平均IC |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for model, periods in summary.items():
        if model == "success":
            continue
        for period, metric in periods.items():
            lines.append(
                f"| {model} | {period} | {metric['total']:.2%} | "
                f"{metric['max_drawdown']:.2%} | {metric['sharpe']:.2f} | {metric['mean_ic']:.4f} |"
            )
    lines.extend(["", "## 成功条件", "", "```json", json.dumps(summary["success"], ensure_ascii=False, indent=2), "```"])
    (PROJECT_ROOT / "research" / f"Lasso组合优化回测报告-{RESULT_DATE}.md").write_text(
        "\n".join(lines), encoding="utf-8",
    )
    save_figures(all_results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
