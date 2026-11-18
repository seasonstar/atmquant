#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分卡选股研究主脚本：因子面板 → 分箱WOE → 逻辑回归评分卡 → 横截面选股回测

研究设计（预登记，2026-11-05）：
- 股票池：全A（剔除ST/*ST/退市整理股、上市未满250个交易日、信号日无交易的股票）
- 因子（7个，全部量价，自包含）：mom20, mom60, vol20, turnover20, amp20, bias20, maxret20
- 标签：未来10个交易日收益 > 当日截面中位数 → 1，否则 0（类别天然均衡）
- 评分卡：训练段（2021-2023）每5个交易日抽样，等频5箱 → WOE → LogisticRegression
- 分数映射：PDO=20、基准分600@1:1（教科书评分卡公式，分数越高越好）
- 组合：每20个交易日调仓，T+1收盘成交，top20等权
- 成本：买边0.125%（佣金万2.5+滑点千0.1），卖边0.225%（加印花税千0.1保守口径）
- 分段：train 2021-2023 / validation 2024 / review 2025-01~2026-10
- 基准：全A等权组合（同池同成本）+ 沪深300指数（仅参考）
- 稳健性：top10/top30 仅作敏感性，不参与选参；复检段补双倍滑点压力测试
- 幸存者偏差声明：2021-2025退市股不在库内，结果偏乐观，解读时打折
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "research" / "scorecard-data"
RESULT_DATE = "2026-11-05"

# ---------------- 预登记参数 ----------------
LABEL_HORIZON = 10          # 标签：未来10日
REBALANCE_GAP = 20          # 调仓间隔：20个交易日
TOP_N = 20                  # 主配置持仓数
ROBUST_TOP_N = [10, 30]     # 敏感性
N_BINS = 5                  # 等频分箱数
TRAIN_SAMPLE_GAP = 5        # 训练抽样：每5个交易日
BUY_COST = 0.00125          # 买边成本
SELL_COST = 0.00225         # 卖边成本
MIN_LIST_DAYS = 250         # 上市最少交易日数（约1年）
MIN_HISTORY = 120           # 因子所需最少历史行数
BASE_SCORE, PDO = 600.0, 20.0

TRAIN_END = pd.Timestamp("2023-12-31")
VAL_END = pd.Timestamp("2024-12-31")
REVIEW_END = pd.Timestamp("2026-10-31")

FACTORS = ["mom20", "mom60", "vol20", "turnover20", "amp20", "bias20", "maxret20"]


def period_of(dt: pd.Timestamp) -> str:
    if dt <= TRAIN_END:
        return "train"
    if dt <= VAL_END:
        return "validation"
    return "review"


# ---------------- 数据加载与因子 ----------------

def load_panel() -> pd.DataFrame:
    panel = pd.read_parquet(DATA_DIR / "ashare_daily_2020plus.parquet")
    info = pd.read_csv(DATA_DIR / "ashare_info.csv", dtype={"symbol": str})
    # 剔除ST/*ST/退市整理股
    bad = info["name"].str.contains("ST|退", na=False)
    info = info[~bad]
    panel = panel[panel["symbol"].isin(set(info["symbol"]))]
    info["list_date"] = pd.to_datetime(info["list_date"])
    panel = panel.merge(info[["symbol", "list_date"]], on="symbol", how="left")
    panel = panel.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    return panel


def compute_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """按股票分组计算7个量价因子与前瞻收益标签"""
    g = panel.groupby("symbol", group_keys=False)

    def _per_stock(df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date")
        close = df["close"]
        # 数据库pct_change字段不可靠：约70万行价格实际变动但字段为0（已验证）
        # 收益一律用前复权收盘价自算
        ret = close.pct_change()
        df["mom20"] = close / close.shift(20) - 1
        df["mom60"] = close / close.shift(60) - 1
        df["vol20"] = ret.rolling(20).std()
        df["turnover20"] = df["turnover_rate"].rolling(20).mean()
        df["amp20"] = ((df["high"] - df["low"]) / close).rolling(20).mean()
        df["bias20"] = close / close.rolling(20).mean() - 1
        df["maxret20"] = ret.rolling(20).max()
        # 前瞻收益：标签用fwd10（T日收盘到T+10收盘）
        df[f"fwd{LABEL_HORIZON}"] = close.shift(-LABEL_HORIZON) / close - 1
        # 持仓收益：T+1收盘买入，持有至T+21收盘（该股的实际交易日序列，自动跳过停牌）
        hold = close.shift(-(REBALANCE_GAP + 1)) / close.shift(-1) - 1
        # 退市/长期停牌兜底：用最后可得收盘价结算
        fallback = close.iloc[-1] / close.shift(-1) - 1
        df["hold_ret"] = hold.fillna(fallback)
        df.loc[close.shift(-1).isna(), "hold_ret"] = np.nan  # 最后一日无法买入
        df["listed_days"] = np.arange(len(df))  # 已按日期排序的行号≈上市交易日数
        return df

    panel = g.apply(_per_stock)
    return panel.reset_index(drop=True)


# ---------------- 评分卡 ----------------

class ScoreCard:
    """教科书式评分卡：等频分箱 + WOE编码 + 逻辑回归 + PDO分数映射"""

    def __init__(self, n_bins: int = 5, base_score: float = 600, pdo: float = 20):
        self.n_bins = n_bins
        self.factor_scale = pdo / np.log(2)
        self.base_score = base_score
        self.bin_tables_ = {}
        self.coef_ = None
        self.intercept_ = None

    def _bin_woe(self, x: pd.Series, y: pd.Series, name: str):
        qs = np.quantile(x.dropna(), np.linspace(0, 1, self.n_bins + 1))
        qs[0], qs[-1] = -np.inf, np.inf
        qs = np.unique(qs)
        bins = pd.cut(x, qs)
        tbl = pd.DataFrame({"bin": bins, "y": y}).groupby("bin", observed=True)["y"]
        stat = tbl.agg(["count", "sum"])
        good, bad = stat["sum"], stat["count"] - stat["sum"]
        good_pct = (good + 0.5) / (good.sum() + 0.5)
        bad_pct = (bad + 0.5) / (bad.sum() + 0.5)
        woe = np.log(good_pct / bad_pct)
        iv = float(((good_pct - bad_pct) * woe).sum())
        edges = qs
        self.bin_tables_[name] = {
            "edges": edges, "woe": woe.values, "iv": iv,
            "counts": stat["count"].values, "good_rate": (good / stat["count"]).values,
        }
        binned = pd.cut(x, edges)
        codes = binned.cat.codes.clip(0, len(woe) - 1)
        return pd.Series(woe.values[codes], index=x.index)

    def fit(self, X: pd.DataFrame, y: pd.Series):
        from sklearn.linear_model import LogisticRegression
        W = pd.DataFrame({f: self._bin_woe(X[f], y, f) for f in X.columns})
        lr = LogisticRegression(max_iter=1000)
        lr.fit(W.fillna(0), y)
        self.coef_ = dict(zip(X.columns, lr.coef_[0]))
        self.intercept_ = float(lr.intercept_[0])
        return self

    def _woe_transform(self, X: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for f in X.columns:
            tbl = self.bin_tables_[f]
            codes = pd.cut(X[f], tbl["edges"]).cat.codes
            codes = codes.where(codes >= 0, other=np.nan)
            woe_map = pd.Series(tbl["woe"])
            out[f] = codes.map(woe_map)
        return pd.DataFrame(out)

    def score(self, X: pd.DataFrame) -> pd.Series:
        """总分 = 600 + factor*ln(good/bad)，PDO=20：每高20分好赔率高一倍，越高越强"""
        W = self._woe_transform(X).fillna(0)
        log_odds = self.intercept_ + sum(W[f] * self.coef_[f] for f in W.columns)
        return self.base_score + self.factor_scale * log_odds

    def score_detail(self, x_row: pd.Series) -> pd.DataFrame:
        """单股票打分明细（教学展示用）"""
        W = self._woe_transform(pd.DataFrame([x_row])).iloc[0].fillna(0)
        rows = []
        for f in FACTORS:
            tbl = self.bin_tables_[f]
            edges = tbl["edges"]
            code = pd.cut(pd.Series([x_row[f]]), edges).cat.codes[0]
            points = self.factor_scale * self.coef_[f] * W[f]
            rows.append({
                "factor": f, "value": x_row[f],
                "bin": int(code) if code >= 0 else -1,
                "woe": W[f], "coef": self.coef_[f], "points": points,
            })
        return pd.DataFrame(rows)


# ---------------- 回测 ----------------

def run_backtest(daily: pd.DataFrame, card: ScoreCard, top_n: int,
                 cost_mult: float = 1.0) -> pd.DataFrame:
    """全区间滚动回测：信号日T打分，T+1收盘成交，持有20个交易日后调仓（向量化）"""
    by_date = dict(tuple(daily.groupby("trade_date")))
    trades = []
    for dt in sorted(daily.loc[daily["is_rebal"], "trade_date"].unique()):
        snap = by_date.get(dt)
        if snap is None:
            continue
        snap = snap.dropna(subset=FACTORS + ["hold_ret"])
        if len(snap) < top_n * 3:
            continue
        scores = card.score(snap[FACTORS])
        pick = snap.loc[scores.nlargest(top_n).index]
        gross = float(pick["hold_ret"].mean())
        cost = (SELL_COST + BUY_COST) * cost_mult  # 单边全换手：卖旧买新
        ic_snap = snap.dropna(subset=[f"fwd{LABEL_HORIZON}"])
        trades.append({
            "date": dt, "period": period_of(dt), "n": len(pick),
            "gross": gross, "net": gross - cost,
            "ic": pd.Series(scores[ic_snap.index]).corr(
                ic_snap[f"fwd{LABEL_HORIZON}"], method="spearman"),
        })
    return pd.DataFrame(trades)


def run_equal_weight_baseline(daily: pd.DataFrame, cost_mult: float = 1.0) -> pd.DataFrame:
    """全A等权基准：同池、同调仓节奏、同成本（换手按5%近似）"""
    by_date = dict(tuple(daily.groupby("trade_date")))
    trades = []
    for dt in sorted(daily.loc[daily["is_rebal"], "trade_date"].unique()):
        snap = by_date.get(dt)
        if snap is None:
            continue
        snap = snap.dropna(subset=["hold_ret"])
        if len(snap) < 100:
            continue
        gross = float(snap["hold_ret"].mean())
        cost = (SELL_COST + BUY_COST) * 0.05 * cost_mult
        trades.append({"date": dt, "period": period_of(dt), "gross": gross, "net": gross - cost})
    return pd.DataFrame(trades)


def period_metrics(df: pd.DataFrame, ret_col: str = "net") -> dict:
    if df.empty:
        return {}
    nav = (1 + df[ret_col]).cumprod()
    total = nav.iloc[-1] - 1
    days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
    ann = (1 + total) ** (365 / max(days, 1)) - 1
    dd = (nav / nav.cummax() - 1).min()
    sharpe = df[ret_col].mean() / df[ret_col].std() * np.sqrt(12) if df[ret_col].std() > 0 else 0
    return {
        "区间收益": f"{total:.2%}", "年化": f"{ann:.2%}", "最大回撤": f"{dd:.2%}",
        "夏普(年化)": f"{sharpe:.2f}", "调仓次数": len(df),
        "平均IC": f"{df['ic'].mean():.4f}" if "ic" in df else "-",
    }


def main():
    print("加载面板...")
    panel = load_panel()
    print(f"面板 {panel.shape}，股票 {panel['symbol'].nunique()} 只")

    print("计算因子...")
    panel = compute_factors(panel)

    # 调仓日标记：2021年起每20个交易日（用全市场交易日历）
    cal = sorted(panel.loc[panel["trade_date"] >= "2021-01-01", "trade_date"].unique())
    rebal_set = set(cal[::REBALANCE_GAP])
    panel["is_rebal"] = panel["trade_date"].isin(rebal_set)

    # 股票池过滤：上市满250个交易日 + 因子非空
    panel["in_universe"] = (panel["listed_days"] >= MIN_LIST_DAYS) & panel[FACTORS].notna().all(axis=1)
    daily = panel[panel["in_universe"]].copy()
    print(f"入池行数 {len(daily)}，调仓日 {len(rebal_set)} 个")

    # ---------------- 训练评分卡 ----------------
    print("训练评分卡...")
    train_mask = (daily["trade_date"] <= TRAIN_END)
    cal_train = sorted(daily.loc[train_mask, "trade_date"].unique())[::TRAIN_SAMPLE_GAP]
    train_df = daily[train_mask & daily["trade_date"].isin(cal_train)].copy()
    med = train_df.groupby("trade_date")[f"fwd{LABEL_HORIZON}"].transform("median")
    train_df["y"] = (train_df[f"fwd{LABEL_HORIZON}"] > med).astype(int)
    train_df = train_df.dropna(subset=[f"fwd{LABEL_HORIZON}"])
    print(f"训练样本 {len(train_df)}，正例占比 {train_df['y'].mean():.3f}")

    card = ScoreCard(n_bins=N_BINS, base_score=BASE_SCORE, pdo=PDO)
    card.fit(train_df[FACTORS], train_df["y"])

    print("\n因子IV与系数：")
    for f in FACTORS:
        print(f"  {f:12s} IV={card.bin_tables_[f]['iv']:.4f}  coef={card.coef_[f]:+.4f}")

    # ---------------- 回测 ----------------
    print("\n主配置回测 top20...")
    bt = run_backtest(daily, card, TOP_N)
    print("敏感性回测 top10/top30...")
    bt10 = run_backtest(daily, card, 10)
    bt30 = run_backtest(daily, card, 30)
    print("全A等权基准...")
    ew = run_equal_weight_baseline(daily)
    print("双倍滑点压力测试（复检段）...")
    bt_stress = run_backtest(daily, card, TOP_N, cost_mult=2.0)

    # ---------------- 报告 ----------------
    lines = ["# 评分卡选股回测报告", f"> 生成：{RESULT_DATE}，预登记参数见脚本头部。", ""]
    lines.append("## 因子体检（训练段 2021-2023）")
    lines.append("| 因子 | IV | 逻辑回归系数 |")
    lines.append("|---|---:|---:|")
    for f in FACTORS:
        lines.append(f"| {f} | {card.bin_tables_[f]['iv']:.4f} | {card.coef_[f]:+.4f} |")

    for name, df in [("评分卡top20", bt), ("top10(敏感性)", bt10),
                     ("top30(敏感性)", bt30), ("全A等权基准", ew)]:
        lines.append(f"\n## {name}")
        lines.append("| 分段 | 区间收益 | 年化 | 最大回撤 | 夏普 | 平均IC | 次数 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for p in ["train", "validation", "review"]:
            m = period_metrics(df[df["period"] == p])
            if m:
                lines.append(
                    f"| {p} | {m['区间收益']} | {m['年化']} | {m['最大回撤']} "
                    f"| {m['夏普(年化)']} | {m.get('平均IC', '-')} | {m['调仓次数']} |"
                )

    m_stress = period_metrics(bt_stress[bt_stress["period"] == "review"])
    lines.append(f"\n## 双倍滑点压力测试（复检段 top20）")
    lines.append(f"- {m_stress}")

    # 保存明细
    bt.to_csv(DATA_DIR / f"评分卡选股回测明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    ew.to_csv(DATA_DIR / f"全A等权基准明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    params = {
        "label_horizon": LABEL_HORIZON, "rebalance_gap": REBALANCE_GAP, "top_n": TOP_N,
        "n_bins": N_BINS, "train_sample_gap": TRAIN_SAMPLE_GAP,
        "buy_cost": BUY_COST, "sell_cost": SELL_COST,
        "factors": FACTORS,
        "iv": {f: card.bin_tables_[f]["iv"] for f in FACTORS},
        "coef": card.coef_, "intercept": card.intercept_,
    }
    with open(DATA_DIR / f"评分卡选股核心参数-{RESULT_DATE}.json", "w", encoding="utf-8") as fp:
        json.dump(params, fp, ensure_ascii=False, indent=2, default=str)

    # 分箱表明细（供图表脚本画WOE单调性）
    bin_dump = {}
    for f in FACTORS:
        tbl = card.bin_tables_[f]
        bin_dump[f] = {
            "edges": [float(e) for e in tbl["edges"]],
            "woe": [float(w) for w in tbl["woe"]],
            "good_rate": [float(g) for g in tbl["good_rate"]],
            "counts": [int(c) for c in tbl["counts"]],
            "iv": tbl["iv"],
        }
    with open(DATA_DIR / f"评分卡分箱表-{RESULT_DATE}.json", "w", encoding="utf-8") as fp:
        json.dump(bin_dump, fp, ensure_ascii=False, indent=2)

    report = "\n".join(lines)
    (DATA_DIR.parent / f"评分卡选股回测报告-{RESULT_DATE}.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n报告与明细已保存至 {DATA_DIR.parent}")

    # 打分明细示例（最近一个调仓日分数最高的股票）
    last_dt = max(d for d in rebal_set if d <= REVIEW_END)
    snap = daily[daily["trade_date"] == last_dt].dropna(subset=FACTORS)
    scores = card.score(snap[FACTORS])
    top1 = snap.loc[scores.idxmax()]
    detail = card.score_detail(top1[FACTORS])
    detail.to_csv(DATA_DIR / f"打分明细示例-{top1['symbol']}-{RESULT_DATE}.csv",
                  index=False, encoding="utf-8-sig")
    print(f"\n打分明细示例：{top1['symbol']} @ {last_dt.date()}，总分 {scores.max():.1f}")
    print(detail.to_string(index=False))


if __name__ == "__main__":
    main()
