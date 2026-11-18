"""汇总分位数风险仓位实验并生成文章图表。"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "research" / "quantile-risk-data"
RESEARCH = ROOT / "research"
IMAGES = ROOT / "articles" / "images"
IMAGES.mkdir(parents=True, exist_ok=True)
MODELS = ["fixed", "atr", "historical", "ewma", "caviar"]
RISK_MODELS = ["historical", "ewma", "caviar"]
LABELS = {
    "fixed": "固定2手",
    "atr": "ATR",
    "historical": "历史分位数",
    "ewma": "EWMA",
    "caviar": "CAViaR-AS",
}

strategy_frames = []
risk_frames = []
signal_frames = []
metadata = {}
for path in sorted(DATA.glob("*-strategy.csv")):
    frame = pd.read_csv(path)
    symbol = path.name.split("-slippage")[0].replace("_", ".", 1)
    ticks = int(path.name.split("-slippage")[1].split("-")[0])
    frame["file_symbol"] = symbol
    frame["cost_scenario"] = ticks
    strategy_frames.append(frame)
for path in sorted(DATA.glob("*-risk.csv")):
    frame = pd.read_csv(path)
    ticks = int(path.name.split("-slippage")[1].split("-")[0])
    frame["cost_scenario"] = ticks
    risk_frames.append(frame)
for path in sorted(DATA.glob("*-signals.csv")):
    frame = pd.read_csv(path)
    frame["cost_scenario"] = int(path.name.split("-slippage")[1].split("-")[0])
    signal_frames.append(frame)
for path in sorted(DATA.glob("*-metadata.json")):
    item = json.loads(path.read_text())
    metadata[f"{item['vt_symbol']}|{item['slippage_ticks']}"] = item

strategy = pd.concat(strategy_frames, ignore_index=True)
risks = pd.concat(risk_frames, ignore_index=True).drop_duplicates(
    ["vt_symbol", "period", "model", "count", "pinball_loss"]
)
signals = pd.concat(signal_frames, ignore_index=True)
assert len(strategy) == 360, f"策略结果应为360行，实际{len(strategy)}"
assert set(strategy["cost_scenario"]) == {1, 2}
assert set(strategy["vt_symbol"].unique()) == {
    "rb2701.SHFE", "hc2701.SHFE", "i2701.DCE", "j2701.DCE",
    "jm2701.DCE", "MA701.CZCE", "TA701.CZCE", "SR701.CZCE",
    "m2701.DCE", "FG701.CZCE", "SA701.CZCE", "RM701.CZCE",
}
assert strategy.groupby(["cost_scenario", "vt_symbol", "model"]).size().eq(3).all()
assert not strategy[["total_net_pnl", "total_return", "max_ddpercent", "sharpe_ratio"]].isna().any().any()

signal_checks = []
for (symbol, ticks), group in signals.groupby(["vt_symbol", "cost_scenario"]):
    baseline = group[group["model"] == "fixed"][["datetime", "event", "direction"]].reset_index(drop=True)
    for model in MODELS[1:]:
        candidate = group[group["model"] == model][["datetime", "event", "direction"]].reset_index(drop=True)
        signal_checks.append({
            "vt_symbol": symbol,
            "cost_scenario": ticks,
            "model": model,
            "same_as_fixed": baseline.equals(candidate),
            "fixed_count": len(baseline),
            "candidate_count": len(candidate),
        })
signal_checks = pd.DataFrame(signal_checks)
assert signal_checks["same_as_fixed"].all(), "存在信号时间与固定组不一致"

strategy.to_csv(RESEARCH / f"分位数风险仓位批量回测明细-2026-11-12.csv", index=False)
risks.to_csv(RESEARCH / f"分位数风险预测检验-2026-11-12.csv", index=False)
signal_checks.to_csv(RESEARCH / f"分位数风险仓位信号一致性-2026-11-12.csv", index=False)

summaries = []
for (ticks, period), group in strategy.groupby(["cost_scenario", "period"]):
    for model, rows in group.groupby("model"):
        summaries.append({
            "cost_scenario": ticks,
            "period": period,
            "model": model,
            "net_pnl_sum": rows["total_net_pnl"].sum(),
            "return_median": rows["total_return"].median(),
            "drawdown_median": rows["max_ddpercent"].median(),
            "sharpe_median": rows["sharpe_ratio"].median(),
            "positive_count": int((rows["total_return"] > 0).sum()),
            "turnover_median": rows["turnover_ratio"].median(),
            "traded_volume_sum": rows["traded_volume"].sum(),
            "commission_sum": rows["commission"].sum(),
            "slippage_sum": rows["slippage"].sum(),
        })
summary = pd.DataFrame(summaries)
summary.to_csv(RESEARCH / f"分位数风险仓位分段汇总-2026-11-12.csv", index=False)

risk_summaries = []
for (period, model), rows in risks.groupby(["period", "model"]):
    risk_summaries.append({
        "period": period,
        "model": model,
        "pinball_median": rows["pinball_loss"].median(),
        "breach_rate_median": rows["breach_rate"].median(),
        "kupiec_pass": int((rows["kupiec_p"] > 0.05).sum()),
        "christoffersen_pass": int((rows["christoffersen_p"] > 0.05).sum()),
        "dq_pass": int((rows["dq_p"] > 0.05).sum()),
    })
risk_summary = pd.DataFrame(risk_summaries)
risk_summary.to_csv(RESEARCH / f"分位数风险预测分段汇总-2026-11-12.csv", index=False)

review = strategy[(strategy["cost_scenario"] == 1) & (strategy["period"] == "review")]
fixed = review[review["model"] == "fixed"].set_index("vt_symbol")
caviar = review[review["model"] == "caviar"].set_index("vt_symbol")
joined = fixed[["max_ddpercent", "sharpe_ratio"]].join(
    caviar[["max_ddpercent", "sharpe_ratio"]], lsuffix="_fixed", rsuffix="_caviar"
)
drawdown_improved = int((joined["max_ddpercent_caviar"] > joined["max_ddpercent_fixed"]).sum())
sharpe_improved = int((joined["sharpe_ratio_caviar"] > joined["sharpe_ratio_fixed"]).sum())
fixed_abs_median = joined["max_ddpercent_fixed"].abs().median()
caviar_abs_median = joined["max_ddpercent_caviar"].abs().median()
relative_reduction = (fixed_abs_median - caviar_abs_median) / fixed_abs_median
fixed_sharpe = joined["sharpe_ratio_fixed"].median()
caviar_sharpe = joined["sharpe_ratio_caviar"].median()
gate = {
    "drawdown_improved": drawdown_improved,
    "sharpe_improved": sharpe_improved,
    "drawdown_relative_reduction": relative_reduction,
    "fixed_sharpe": fixed_sharpe,
    "caviar_sharpe": caviar_sharpe,
}
gate["passed"] = bool(
    drawdown_improved >= 8 and relative_reduction >= 0.20 and caviar_sharpe >= fixed_sharpe
)

stress = strategy[(strategy["cost_scenario"] == 2) & (strategy["period"] == "review")]
stress_fixed = stress[stress["model"] == "fixed"].set_index("vt_symbol")
stress_caviar = stress[stress["model"] == "caviar"].set_index("vt_symbol")
stress_joined = stress_fixed[["max_ddpercent", "sharpe_ratio"]].join(
    stress_caviar[["max_ddpercent", "sharpe_ratio"]], lsuffix="_fixed", rsuffix="_caviar"
)
stress_reduction = (
    stress_joined["max_ddpercent_fixed"].abs().median()
    - stress_joined["max_ddpercent_caviar"].abs().median()
) / stress_joined["max_ddpercent_fixed"].abs().median()
stress_gate = {
    "drawdown_improved": int((stress_joined["max_ddpercent_caviar"] > stress_joined["max_ddpercent_fixed"]).sum()),
    "sharpe_improved": int((stress_joined["sharpe_ratio_caviar"] > stress_joined["sharpe_ratio_fixed"]).sum()),
    "drawdown_relative_reduction": stress_reduction,
    "fixed_sharpe": stress_joined["sharpe_ratio_fixed"].median(),
    "caviar_sharpe": stress_joined["sharpe_ratio_caviar"].median(),
}
stress_gate["passed"] = bool(
    stress_gate["drawdown_improved"] >= 8
    and stress_reduction >= 0.20
    and stress_gate["caviar_sharpe"] >= stress_gate["fixed_sharpe"]
)

review_risks = risks[risks["period"] == "review"].set_index(["vt_symbol", "model"])
pinball_comparison = {}
for baseline in ["historical", "ewma"]:
    count = 0
    for symbol in strategy["vt_symbol"].unique():
        candidate_loss = review_risks.loc[(symbol, "caviar"), "pinball_loss"]
        baseline_loss = review_risks.loc[(symbol, baseline), "pinball_loss"]
        count += int(candidate_loss < baseline_loss)
    pinball_comparison[f"caviar_beats_{baseline}"] = count

model_comparisons = []
for ticks in [1, 2]:
    period_rows = strategy[(strategy["cost_scenario"] == ticks) & (strategy["period"] == "review")]
    baseline = period_rows[period_rows["model"] == "fixed"].set_index("vt_symbol")
    for model in MODELS[1:]:
        candidate = period_rows[period_rows["model"] == model].set_index("vt_symbol")
        pair = baseline[["max_ddpercent", "sharpe_ratio"]].join(
            candidate[["max_ddpercent", "sharpe_ratio"]], lsuffix="_fixed", rsuffix="_candidate"
        )
        fixed_dd = pair["max_ddpercent_fixed"].abs().median()
        candidate_dd = pair["max_ddpercent_candidate"].abs().median()
        reduction = (fixed_dd - candidate_dd) / fixed_dd
        candidate_sharpe = pair["sharpe_ratio_candidate"].median()
        baseline_sharpe = pair["sharpe_ratio_fixed"].median()
        improved = int((pair["max_ddpercent_candidate"] > pair["max_ddpercent_fixed"]).sum())
        model_comparisons.append({
            "cost_scenario": ticks,
            "model": model,
            "drawdown_improved": improved,
            "sharpe_improved": int((pair["sharpe_ratio_candidate"] > pair["sharpe_ratio_fixed"]).sum()),
            "drawdown_relative_reduction": reduction,
            "fixed_sharpe": baseline_sharpe,
            "candidate_sharpe": candidate_sharpe,
            "passed_same_gate": bool(improved >= 8 and reduction >= 0.20 and candidate_sharpe >= baseline_sharpe),
        })
pd.DataFrame(model_comparisons).to_csv(RESEARCH / "分位数风险仓位全模型门槛对照-2026-11-12.csv", index=False)

conclusion = {
    "strategy_gate_regular_cost": gate,
    "strategy_gate_double_slippage": stress_gate,
    "risk_review": pinball_comparison,
    "model_comparisons": model_comparisons,
    "signal_checks": int(signal_checks["same_as_fixed"].sum()),
    "signal_check_total": int(len(signal_checks)),
    "review_scope": "2026-09-16至2026-10-30，二次验证，非全新样本外",
    "position_rule": "固定2手；动态1至2手，不超过固定组风险上限",
}
(RESEARCH / f"分位数风险仓位核心结论-2026-11-12.json").write_text(
    json.dumps(conclusion, ensure_ascii=False, indent=2)
)

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
colors = {"fixed": "#5B6573", "atr": "#D18B47", "historical": "#4E89AE", "ewma": "#78A689", "caviar": "#A34A62"}
review_summary = summary[(summary["cost_scenario"] == 1) & (summary["period"] == "review")].set_index("model").loc[MODELS]
fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))
for ax, column, title in zip(
    axes,
    ["return_median", "drawdown_median", "sharpe_median"],
    ["净收益中位数（%）", "最大回撤中位数（%）", "夏普中位数"],
):
    values = review_summary[column]
    ax.bar([LABELS[m] for m in MODELS], values, color=[colors[m] for m in MODELS])
    ax.set_title(title)
    ax.tick_params(axis="x", rotation=25)
    ax.grid(axis="y", alpha=0.2)
    ax.axhline(0, color="#333333", linewidth=0.7)
fig.suptitle("复检段：同一CTA信号下的仓位对照（12品种）", fontsize=15)
fig.tight_layout()
fig.savefig(IMAGES / "quantile-risk-review-summary.png", dpi=180, bbox_inches="tight")
plt.close(fig)

review_risk_summary = risk_summary[risk_summary["period"] == "review"].set_index("model").loc[RISK_MODELS]
fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
axes[0].bar([LABELS[m] for m in RISK_MODELS], review_risk_summary["pinball_median"], color=[colors[m] for m in RISK_MODELS])
axes[0].set_title("Pinball loss中位数（越低越好）")
axes[1].bar([LABELS[m] for m in RISK_MODELS], review_risk_summary["breach_rate_median"] * 100, color=[colors[m] for m in RISK_MODELS])
axes[1].axhline(5, color="#333333", linestyle="--", linewidth=1, label="目标5%")
axes[1].set_title("穿越率中位数（%）")
axes[1].legend()
for ax in axes:
    ax.grid(axis="y", alpha=0.2)
fig.suptitle("复检段：尾部风险预测检验（12品种）", fontsize=15)
fig.tight_layout()
fig.savefig(IMAGES / "quantile-risk-forecast.png", dpi=180, bbox_inches="tight")
plt.close(fig)

pd.set_option("display.max_columns", 30)
pd.set_option("display.width", 180)
print("\n=== 常规成本复检段 ===")
print(review_summary[["return_median", "drawdown_median", "sharpe_median", "positive_count", "turnover_median", "net_pnl_sum"]].round(4).to_string())
print("\n=== 双倍滑点复检段 ===")
print(summary[(summary["cost_scenario"] == 2) & (summary["period"] == "review")].set_index("model").loc[MODELS][["return_median", "drawdown_median", "sharpe_median", "positive_count", "turnover_median"]].round(4).to_string())
print("\n=== 风险预测复检段 ===")
print(review_risk_summary.round(4).to_string())
print("\n=== 核心结论 ===")
print(json.dumps(conclusion, ensure_ascii=False, indent=2))
print("\n=== 各品种常规成本复检段 ===")
print(review.pivot(index="vt_symbol", columns="model", values="total_return")[MODELS].round(3).to_string())
print("\n=== 各品种回撤 ===")
print(review.pivot(index="vt_symbol", columns="model", values="max_ddpercent")[MODELS].round(3).to_string())
