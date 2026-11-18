"""量化策略开发12：发布前静态质检，不运行或修改回测。"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTICLE = ROOT / "articles/量化策略开发12：最坏5%的行情，该下多大仓位？ - 分位数回归动态仓位实验.md"
text = ARTICLE.read_text(encoding="utf-8")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
checks: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    checks.append((name, bool(condition), detail))


emoji = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
check("零 emoji", not emoji.search(text))
banned = ["让我们来探讨", "综上所述", "通过以上分析可以得出", "值得注意的是", "如图所示", "基于上述原因", "本文将介绍"]
check("无禁用机器腔", not [phrase for phrase in banned if phrase in text], "、".join(phrase for phrase in banned if phrase in text))
blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
block_lengths = [len(block.rstrip().splitlines()) for block in blocks]
check("代码块不超过 20 行", all(length <= 20 for length in block_lengths), str(block_lengths))
check("系列开头格式", "> 本文是《量化策略开发》系列的第12篇。" in text)
check("负结果明确保留", all(phrase in text for phrase in ["直接判负", "不进入模拟盘", "不继续围绕复检段调参", "二次验证"]))

footer_markers = ["本文基于 ATMQuant", "本文内容仅供学习交流", "### 加入「量策堂·AI算法指标策略」", "### 往期文章回顾", "**相关标签**"]
positions = [text.find(marker) for marker in footer_markers]
check("页脚完整且顺序正确", all(pos >= 0 for pos in positions) and positions == sorted(positions))

review = text.split("### 往期文章回顾", 1)[1]
series = ["量化策略开发系列", "以AI量化为生系列", "量化指标解码系列"]
series_positions = [review.find(f"**{name}**") for name in series]
check("往期系列顺序正确", all(pos >= 0 for pos in series_positions) and series_positions == sorted(series_positions))
readme_urls = set(re.findall(r"https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+", readme))
for index, name in enumerate(series):
    start = series_positions[index]
    end = series_positions[index + 1] if index + 1 < len(series) else len(review)
    section = review[start:end]
    links = re.findall(r"^- \[[^]]+\]\((https://mp\.weixin\.qq\.com/s/[^)]+)\)$", section, re.M)
    check(f"{name}恰好三篇", len(links) == 3, str(len(links)))
    check(f"{name}链接来自 README", bool(links) and set(links) <= readme_urls)
check("往期均为无序列表", not re.search(r"^\d+\. \[", review, re.M))

image_paths = re.findall(r"!\[[^]]*\]\(([^)]+)\)", text)
missing_images = [path for path in image_paths if not (ARTICLE.parent / path).resolve().is_file()]
check("本地图片全部存在", bool(image_paths) and not missing_images, "、".join(missing_images))
check("封面文件非空", (ROOT / "articles/images/量化策略开发12-cover.png").stat().st_size > 0)

experience = text.split("## 实战经验与避坑指南", 1)[1].split("## 写在最后", 1)[0]
plain_experience = re.sub(r"[\s*#>`_-]", "", experience)
check("实战经验不超过 150 字", len(plain_experience) <= 150, str(len(plain_experience)))
check("实战经验最多四点", len(re.findall(r"^\*\*", experience, re.M)) <= 4)

with (ROOT / "research/分位数风险仓位核心结论-2026-11-12.json").open(encoding="utf-8") as handle:
    conclusions = json.load(handle)
regular = conclusions["strategy_gate_regular_cost"]
double = conclusions["strategy_gate_double_slippage"]
check("常规成本门槛判负且数字一致", not regular["passed"] and regular["drawdown_improved"] == 5 and regular["sharpe_improved"] == 3 and "扩大了8.10%" in text)
check("双倍成本门槛判负且数字一致", not double["passed"] and double["drawdown_improved"] == 5 and "扩大10.36%" in text)
check("风险预测相对胜场一致", conclusions["risk_review"] == {"caviar_beats_historical": 4, "caviar_beats_ewma": 11} and "11个品种上比EWMA" in text and "只在4个品种上赢过历史分位数" in text)
check("96 组信号一致性有记录", conclusions["signal_checks"] == conclusions["signal_check_total"] == 96)

with (ROOT / "research/分位数风险仓位分段汇总-2026-11-12.csv").open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))
review_rows = {(row["cost_scenario"], row["model"]): row for row in rows if row["period"] == "review"}
from decimal import Decimal, ROUND_HALF_UP


def rounded3(value: str) -> str:
    """先去除浮点序列化噪声，再按常用四舍五入保留三位。"""
    snapped = Decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return format(snapped.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), ".3f")


labels = {"fixed": "固定2手", "atr": "ATR", "historical": "历史分位数", "ewma": "EWMA", "caviar": "CAViaR-AS"}
for model, label in labels.items():
    row = review_rows[("1", model)]
    regenerated = f"| {label} | {rounded3(row['return_median'])}% | {rounded3(row['drawdown_median'])}% | {rounded3(row['sharpe_median'])} | {row['positive_count']}/12 | {rounded3(row['turnover_median'])} |"
    check(f"常规成本 {model} 表格数字", regenerated in text, regenerated)
for model in ["fixed", "caviar"]:
    row = review_rows[("2", model)]
    for value in [f"{rounded3(row['return_median'])}%", f"{rounded3(row['drawdown_median'])}%", rounded3(row['sharpe_median'])]:
        check(f"双倍成本 {model} {value}", value in text)

failed = [item for item in checks if not item[1]]
for name, passed, detail in checks:
    print(f"{'PASS' if passed else 'FAIL'} {name}{'：' + detail if detail else ''}")
print(f"\n共 {len(checks)} 项，通过 {len(checks) - len(failed)} 项，失败 {len(failed)} 项。")
raise SystemExit(1 if failed else 0)
