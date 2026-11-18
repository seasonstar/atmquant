"""生成盈利品种子样本案例，明确筛选口径并保留全样本边界。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.batch_backtest_bayesian_q import get_research_period


DATA_DIR = ROOT / "research/bayesian-q-data"


def select_winner_rows(
    detail: pd.DataFrame,
    model: str,
    period: str,
    cost: int,
) -> pd.DataFrame:
    """只选择指定模型、区间和成本下净盈亏为正的品种。"""

    scoped = detail[
        (detail["model"] == model)
        & (detail["period"] == period)
        & (detail["slippage_ticks"] == cost)
    ]
    winners = scoped[scoped["total_net_pnl"] > 0].copy()
    return winners.sort_values("total_net_pnl", ascending=False).reset_index(drop=True)


def round_trip_pnls(
    frame: pd.DataFrame,
    *,
    size: float,
    fixed_fee: float,
    rate: float,
) -> pd.Series:
    """按实际成交价格计算已闭合往返交易净盈亏，未平仓部分不计。"""

    pnls = []
    open_trade = None
    for row in frame.itertuples(index=False):
        if row.offset == "开":
            if open_trade is not None:
                raise ValueError("上一笔开仓尚未闭合又出现新开仓")
            open_trade = row
            continue
        if row.offset != "平" or open_trade is None:
            continue
        direction = 1.0 if open_trade.direction == "多" else -1.0
        gross = direction * (row.price - open_trade.price) * size * open_trade.volume
        fees = rate * size * open_trade.volume * (open_trade.price + row.price)
        fees += 2 * fixed_fee * open_trade.volume
        pnls.append(gross - fees)
        open_trade = None
    return pd.Series(pnls, dtype=float)


def analyze_winners(
    detail: pd.DataFrame,
    data_dir: Path,
    model: str,
    period: str,
    cost: int,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    winners = select_winner_rows(detail, model, period, cost)
    if winners.empty:
        raise ValueError("当前筛选没有盈利品种，无法生成子样本案例")

    root_rows = []
    round_trips = []
    for winner in winners.itertuples(index=False):
        vt_symbol = winner.vt_symbol
        file_name = f"trades_{vt_symbol.replace('.', '_')}_{model}_slippage{cost}.csv"
        trade_path = data_dir / file_name
        if not trade_path.is_file():
            raise FileNotFoundError(trade_path)
        trades = pd.read_csv(trade_path)
        trade_dates = pd.to_datetime(trades["datetime"], errors="coerce").dt.date
        scoped = trades[trade_dates.map(get_research_period) == period].copy()
        pnls = round_trip_pnls(
            scoped,
            size=float(winner.size),
            fixed_fee=float(winner.fixed_fee),
            rate=float(winner.rate),
        )
        wins = int((pnls > 0).sum())
        root_rows.append({
            "root": winner.root,
            "vt_symbol": vt_symbol,
            "total_net_pnl": float(winner.total_net_pnl),
            "total_return_pct": float(winner.total_return),
            "sharpe_ratio": float(winner.sharpe_ratio),
            "max_drawdown_pct": float(winner.max_ddpercent),
            "closed_round_trips": len(pnls),
            "winning_round_trips": wins,
            "win_rate_pct": wins / len(pnls) * 100 if len(pnls) else np.nan,
            "closed_trade_net_pnl": float(pnls.sum()),
        })
        for pnl in pnls:
            round_trips.append({"root": winner.root, "vt_symbol": vt_symbol, "net_pnl": float(pnl)})

    roots = pd.DataFrame(root_rows)
    trips = pd.DataFrame(round_trips)
    gains = trips.loc[trips["net_pnl"] > 0, "net_pnl"].sum()
    losses = -trips.loc[trips["net_pnl"] < 0, "net_pnl"].sum()
    sharpe = roots["sharpe_ratio"].dropna()
    universe_roots = int(detail[
        (detail["model"] == model)
        & (detail["period"] == period)
        & (detail["slippage_ticks"] == cost)
    ]["root"].nunique())
    summary = {
        "model": model,
        "period": period,
        "slippage_ticks": cost,
        "universe_roots": universe_roots,
        "selected_winning_roots": len(roots),
        "excluded_roots": universe_roots - len(roots),
        "selection_rule": "total_net_pnl > 0；仅盈利子样本，不代表全品种策略成功",
        "median_root_net_pnl": float(roots["total_net_pnl"].median()),
        "total_root_net_pnl": float(roots["total_net_pnl"].sum()),
        "median_root_return_pct": float(roots["total_return_pct"].median()),
        "median_root_sharpe": float(sharpe.median()),
        "positive_sharpe_roots": int((sharpe > 0).sum()),
        "median_root_max_drawdown_pct": float(roots["max_drawdown_pct"].median()),
        "closed_round_trips": len(trips),
        "winning_round_trips": int((trips["net_pnl"] > 0).sum()),
        "win_rate_pct": float((trips["net_pnl"] > 0).mean() * 100),
        "profit_factor": float(gains / losses) if losses > 0 else None,
        "average_closed_trade_pnl": float(trips["net_pnl"].mean()),
        "closed_trade_net_pnl": float(trips["net_pnl"].sum()),
        "full_sample_report": "research/贝叶斯BBSMA-nQQE回测报告-2026-11-12.md",
        "trade_pnl_note": "胜率与盈亏比仅统计已闭合往返交易；实际成交价已含滑点，费用按双边比例费与固定费扣除。",
    }
    return summary, roots, trips


def plot_winner_case(summary: dict, roots: pd.DataFrame, path: Path) -> None:
    ordered = roots.sort_values("total_net_pnl")
    x = np.arange(len(ordered))
    fig, axes = plt.subplots(1, 3, figsize=(19, 7))
    axes[0].bar(x, ordered["total_net_pnl"], color="#dc4646")
    axes[0].set_title("Net PnL by profitable root")
    axes[0].set_ylabel("CNY")
    axes[1].bar(x, ordered["sharpe_ratio"], color="#dc4646")
    axes[1].set_title("Sharpe by profitable root")
    axes[2].axis("off")
    lines = [
        f"Selected winners: {summary['selected_winning_roots']}/{summary['universe_roots']} roots",
        f"Closed-trade win rate: {summary['win_rate_pct']:.2f}%",
        "Profit factor: " + (
            f"{summary['profit_factor']:.3f}"
            if summary["profit_factor"] is not None
            else "N/A (no losing round trips)"
        ),
        f"Median root Sharpe: {summary['median_root_sharpe']:.3f}",
        f"Median root return: {summary['median_root_return_pct']:.2f}%",
        f"Median max drawdown: {summary['median_root_max_drawdown_pct']:.2f}%",
        f"Closed round trips: {summary['closed_round_trips']}",
        "",
        "Profitable subset only. Not a full-universe success result.",
    ]
    axes[2].text(
        0.0,
        0.98,
        "\n".join(lines),
        va="top",
        fontsize=12,
        linespacing=1.55,
    )
    for axis in axes[:2]:
        axis.set_xticks(x, ordered["root"], rotation=55, ha="right")
        axis.axhline(0, color="black", linewidth=0.7)
        axis.grid(alpha=0.22, axis="y")
    fig.suptitle(
        f"Bayesian Q winners case | {summary['period']} | {summary['slippage_ticks']} tick",
        fontsize=15,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--model", default="bayes_q_fixed")
    parser.add_argument("--period", default="review")
    parser.add_argument("--cost", type=int, default=1)
    parser.add_argument(
        "--image-path",
        type=Path,
        default=ROOT / "articles/images/bayesian-q-winner-case.png",
    )
    args = parser.parse_args()
    detail = pd.read_csv(args.data_dir / "batch_detail.csv")
    summary, roots, trips = analyze_winners(detail, args.data_dir, args.model, args.period, args.cost)
    roots.to_csv(args.data_dir / "winner_case_roots.csv", index=False)
    trips.to_csv(args.data_dir / "winner_case_trades.csv", index=False)
    (args.data_dir / "winner_case_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    plot_winner_case(summary, roots, args.image_path)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
