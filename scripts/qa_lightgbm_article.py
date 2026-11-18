"""量化策略开发09：文章、报告与实验产物的静态对账。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lasso_factor_selection_research import period_metrics

ARTICLE = ROOT / "articles/量化策略开发09：LightGBM横截面选股 - 更复杂的模型，为什么没赢.md"
DATA = ROOT / "research/lightgbm-factor-data"
REPORT = ROOT / "research/LightGBM横截面选股回测报告-2026-11-14.md"
text = ARTICLE.read_text(encoding="utf-8")
report = REPORT.read_text(encoding="utf-8")
checks: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    checks.append((name, bool(condition), detail))


def reject_nonstandard_json(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")


summary = json.loads(
    (DATA / "LightGBM核心结果-2026-11-14.json").read_text(encoding="utf-8"),
    parse_constant=reject_nonstandard_json,
)
check("JSON严格解析且等权IC为null", summary["metrics"]["equal_weight"]["review"]["mean_ic"] is None)
check("训练样本与树数", summary["train_rows"] == 568372 and summary["tree_count"] == 60)
check("五折树数进入正文", "17、60、200、38和86" in text and "n_estimators=60" in text)
check("正文含行采样参数", "subsample=0.8" in text and "subsample_freq=1" in text)

labels = {"lightgbm": "LightGBM", "lasso": "Lasso", "equal_weight": "全A等权"}
for model in ["lightgbm", "equal_weight"]:
    label = labels[model]
    metrics = summary["metrics"][model]
    expected = (
        f"| {label} | +{metrics['train']['total']:.1%} | "
        f"+{metrics['validation']['total']:.1%} | **+{metrics['review']['total']:.1%}** |"
    )
    check(f"文章{label}收益表", expected in text, expected)
for model, label in labels.items():
    metrics = summary["metrics"][model]
    for period in ["train", "validation", "review"]:
        m = metrics[period]
        ic = "nan" if m["mean_ic"] is None else f"{m['mean_ic']:.4f}"
        report_row = (
            f"| {label} | {period} | {m['total']:.2%} | {m['annual']:.2%} | "
            f"{m['max_drawdown']:.2%} | {m['sharpe']:.2f} | {ic} | "
            f"{m['gross_total']:.2%} | {m['cost_sum']:.2%} | {m['rebalances']} |"
        )
        check(f"报告对账{label}/{period}", report_row in report, report_row)

lgbm = summary["metrics"]["lightgbm"]
equal = summary["metrics"]["equal_weight"]
value = (equal["review"]["total"] - lgbm["review"]["total"]) * 100
check("落后等权百分点", f"{value:.2f}个百分点" in text, f"{value:.2f}")
for model in ["lightgbm"]:
    m = summary["metrics"][model]
    row = (
        f"| {labels[model]} | {m['train']['mean_ic']:.4f} | "
        f"{m['validation']['mean_ic']:.4f} | {m['review']['mean_ic']:.4f} | "
        f"{m['review']['sharpe']:.2f} |"
    )
    check(f"文章IC表{model}", row in text, row)

stress = summary["stress_review_lightgbm"]
check(
    "双倍成本数字",
    all(value in text for value in [
        f"{stress['total']:.2%}", f"{abs(stress['max_drawdown']):.2%}", f"{stress['sharpe']:.2f}",
    ]),
)
check("毛利与等权口径", f"{lgbm['review']['gross_total']:.2%}" in text and f"{equal['review']['gross_total']:.2%}" in text)
check("四项门槛全部失败", not summary["success"]["all_pass"] and not any(
    value for key, value in summary["success"].items() if key != "all_pass"
))
check("二次验证与基线修正披露", all(phrase in text for phrase in [
    "二次验证", "21次完整调仓", "初始净值1", "2026年10月19日", "不进入模拟盘",
]))

importance = pd.read_csv(DATA / "LightGBM因子重要性-2026-11-14.csv")
for row in importance.head(6).itertuples():
    expected = f"| {row.factor_cn} | {row.split} | {row.gain_pct:.2f}% |"
    check(f"重要性{row.factor_cn}", expected in text, expected)
check("前三项重要性合计", f"{importance.head(3)['gain_pct'].sum():.2f}%" in text)

comparison = pd.read_csv(DATA / "LightGBM与Lasso全对照-2026-11-14.csv", parse_dates=["date"])
lgbm_detail = pd.read_csv(DATA / "LightGBM横截面回测明细-2026-11-14.csv", parse_dates=["date"])
stress_detail = pd.read_csv(DATA / "LightGBM双倍成本明细-2026-11-14.csv", parse_dates=["date"])
for model, name in [("lightgbm_score", "lightgbm"), ("lasso_score", "lasso"), ("equal_weight", "equal_weight")]:
    part = comparison[comparison["model"] == model]
    for period in ["train", "validation", "review"]:
        actual = period_metrics(part[part["period"] == period])
        expected = summary["metrics"][name][period]
        for metric, value in actual.items():
            if isinstance(value, float) and np.isnan(value):
                check(f"CSV对账{name}/{period}/{metric}", expected[metric] is None)
            else:
                check(f"CSV对账{name}/{period}/{metric}", np.isclose(value, expected[metric]))
check("二次验证21次且剔除不完整末日", len(lgbm_detail[lgbm_detail["period"] == "review"]) == 21 and pd.Timestamp("2026-10-19") not in set(lgbm_detail["date"]))
check("压力成本独立且毛收益不变", np.allclose(lgbm_detail["gross"], stress_detail["gross"]) and np.allclose(stress_detail["cost"], lgbm_detail["cost"] * 2))

frozen = pd.read_csv(ROOT / "research/lasso-data/Lasso因子选择回测明细-2026-11-06.csv", parse_dates=["date"])
for model in ["lasso_score", "equal_weight"]:
    current = comparison[comparison["model"] == model].sort_values("date").reset_index(drop=True)
    original = frozen[frozen["model"] == model]
    original = original[original["date"].isin(set(current["date"]))].sort_values("date").reset_index(drop=True)
    for column in ["date", "period", "gross", "cost", "net", "ic", "holdings"]:
        if column == "ic":
            check(f"冻结基线{model}/{column}", np.allclose(current[column], original[column], equal_nan=True))
        else:
            check(f"冻结基线{model}/{column}", current[column].equals(original[column]))

image_paths = re.findall(r"!\[[^]]*\]\(([^)]+)\)", text)
missing = [path for path in image_paths if not (ARTICLE.parent / path).resolve().is_file()]
check("本地图片全部存在", bool(image_paths) and not missing, "、".join(missing))
check("封面非空", (ROOT / "articles/images/量化策略开发09-cover.png").stat().st_size > 0 if (ROOT / "articles/images/量化策略开发09-cover.png").exists() else False)
check("旧版LightGBM数字已清除", not any(value in text for value in ["253.7%", "37.6%", "13.7%", "0.1054", "58棵树", "54、39、177", "63.20%", "22.73%", "5.23%"]))
check("公开净值图只展示LightGBM与等权", "lightgbm-equity-public.png" in text and "LightGBM与全A等权净值对照" in text)
check("往期策略链接不指向已删除文章", all(term in text for term in ["量化策略开发01", "量化策略开发05", "量化策略开发07"]))
check("正文不依赖已删除Lasso前作", all(term not in text for term in ["Lasso", "第08篇", "量化策略开发08"]))
check("边界与免责声明完整", all(phrase in text for phrase in ["幸存者偏差", "最后可得价近似", "涨跌停", "训练标签看10日", "不构成任何投资建议"]))

failed = [item for item in checks if not item[1]]
for name, passed, detail in failed:
    print(f"FAIL {name}{'：' + detail if detail else ''}")
print(f"共 {len(checks)} 项，通过 {len(checks) - len(failed)} 项，失败 {len(failed)} 项。")
raise SystemExit(1 if failed else 0)
