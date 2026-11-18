"""量化指标解码22的图表功能、结构与案例数字对账。"""

from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path

import pandas as pd

from bayesian_q_parameter_research import PARAM_SETS


ROOT = Path(__file__).resolve().parent.parent
ARTICLE = ROOT / "articles/量化指标解码22｜贝叶斯概率振荡器 - 指标计算与图表实现.md"
H1_DATA = ROOT / "research/bayesian-q-data"
M15_DATA = ROOT / "research/bayesian-q-parameter-data"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(text: str, snippet: str) -> None:
    if snippet not in text:
        raise AssertionError(f"文章缺少或写错关键内容: {snippet}")


def main() -> None:
    text = ARTICLE.read_text(encoding="utf-8")
    h1 = load_json(H1_DATA / "analysis_summary.json")
    m15 = load_json(M15_DATA / "analysis_summary.json")
    winners = load_json(H1_DATA / "winner_case_summary.json")
    roots = pd.read_csv(H1_DATA / "winner_case_roots.csv")

    validation = h1["validation"]
    assert validation["total_roots"] == 85
    assert validation["inventory_roots"] == 49
    assert validation["inventory_failed_roots"] == 36
    assert validation["detail_rows"] == validation["expected_detail_rows"] == 1764
    assert h1["decision"]["decision"] == "STOP"
    assert m15["counts"]["detail_rows_1tick"] == 1764
    assert m15["selection_period"] == "validation"
    assert m15["review_used_for_selection"] is False
    assert m15["selected"]["bayes_q_fixed"]["param_set"] == "fast"

    assert winners["universe_roots"] == 49
    assert winners["selected_winning_roots"] == 18
    assert winners["excluded_roots"] == 31
    assert winners["closed_round_trips"] == 15
    assert winners["winning_round_trips"] == 15
    assert winners["win_rate_pct"] == 100.0
    assert winners["profit_factor"] is None

    require(text, "为什么设计这组图表指标")
    require(text, "三个面板各自负责什么")
    require(text, "红色是 Up，绿色是 Down")
    require(text, "pg2701.DCE")
    assert "a2701.DCE" not in text
    require(text, "增强版指标为会员专享功能")
    assert "付费会员专享" not in text
    require(text, "先从49个有效合约中筛出复检净盈亏为正的18个品种")
    require(text, "其余31个品种不纳入这部分案例统计")
    require(text, "100%，15/15")
    require(text, f"{winners['median_root_sharpe']:.3f}")
    require(text, f"{winners['median_root_return_pct']:.2f}%")
    require(text, f"{winners['median_root_max_drawdown_pct']:.2f}%")
    require(text, f"{winners['total_root_net_pnl']:.2f}元")
    require(text, f"{winners['closed_trade_net_pnl']:.2f}元")
    require(text, "15笔闭合交易全部盈利")
    require(text, "这个样本很小，不能据此推断未来的胜率")
    require(text, "盈利品种子样本案例")
    require(text, "全样本策略没有进入模拟盘候选")

    for vt_symbol in ("pg2701.DCE", "PL701.CZCE", "bz2701.DCE", "pp2701.DCE"):
        row = roots[roots["vt_symbol"] == vt_symbol].iloc[0]
        require(text, vt_symbol)
        require(text, f"{row['total_return_pct']:.2f}%")
        require(text, f"{row['sharpe_ratio']:.3f}")
        require(text, f"{row['max_drawdown_pct']:.2f}%")

    expected_fast = {
        "bb_period": 14,
        "bayes_lookback": 14,
        "lower_threshold": 0.15,
        "rsi_period": 10,
        "rsi_smoothing": 3,
        "atrrsi_multiplier": 4.236,
    }
    for key, value in expected_fast.items():
        assert PARAM_SETS["fast"][key] == value

    for snippet in (
        "bayesian_bbsma",
        "nqqe",
        "bayesian_q",
        "左侧一根",
        "显示锚点",
        "signal_minutes",
        "背景只表示 sigma 的相对方向",
        "不构成任何投资建议",
        "research/贝叶斯BBSMA-nQQE回测报告-2026-11-12.md",
        "https://github.com/seasonstar/atmquant",
    ):
        require(text, snippet)

    for snippet in (
        "量化策略开发系列",
        "以AI量化为生系列",
        "量化指标解码系列",
        "下一篇讲 VWAP 深度解码",
    ):
        require(text, snippet)
    article_links = re.findall(r"\]\((https://mp\.weixin\.qq\.com/s/[^)]+)\)", text)
    assert len(article_links) == 9, f"三个系列应各有三个链接，实际共 {len(article_links)} 个"
    assert "下一篇回到 ATR" not in text

    lowered = text.casefold()
    forbidden = (
        "p" + "ine",
        "trading" + "view",
        "formula" + "_mode",
        "原始" + "公式",
        "公式" + "模式",
    )
    for word in forbidden:
        assert word.casefold() not in lowered, f"文章仍含来源或公式模式表述: {word}"

    images = re.findall(r"!\[[^]]*\]\(([^)]+)\)", text)
    assert len(images) == 5, f"预期封面、真实图表、配置、案例图和星球图，实际 {len(images)}"
    for image in images:
        image_path = (ARTICLE.parent / image).resolve()
        assert image_path.is_file() and image_path.stat().st_size > 0, image_path

    expected_hashes = {
        "bayesian-q-live-chart.png": "edda985b19335d87c9367718cb4e96a8f86ce2a973c841e718c8416bb77fff26",
        "bayesian-q-config.png": "2998ca81794e673b4c7db072ce708231a48357c619e81adac6946e08e7997678",
    }
    for name, expected in expected_hashes.items():
        actual = hashlib.sha256((ARTICLE.parent / "images" / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} 已被覆盖，不是用户指定附件"

    report_path = ARTICLE.parent / "../research/贝叶斯BBSMA-nQQE回测报告-2026-11-12.md"
    assert report_path.resolve().is_file()
    assert text.count("```") % 2 == 0
    assert "https://mp.weixin.qq.com/)" not in text
    print(json.dumps({
        "article": str(ARTICLE),
        "status": "PASS",
        "images": len(images),
        "winner_roots": winners["selected_winning_roots"],
        "win_rate_pct": winners["win_rate_pct"],
        "median_sharpe": winners["median_root_sharpe"],
        "median_return_pct": winners["median_root_return_pct"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
