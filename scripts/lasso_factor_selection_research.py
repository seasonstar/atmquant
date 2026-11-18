#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lasso 因子选择研究：31 个量价因子 → 横截面标准化 → OLS/Lasso → top20 月调仓

研究设计（预登记，2026-11-06）：
- 数据：复用第07篇全A面板，剔除ST/*ST/退市整理股；信号日上市约满一年
- 因子：31个，仅使用T日及此前OHLCV/成交额/换手率，不用数据库pct_change
- 标签：T日收盘至T+10日收盘收益；训练时逐日1%/99%缩尾并做截面z-score
- 特征：逐日1%/99%缩尾并做截面z-score，不随机shuffle，不引入未来数据
- 模型：全因子OLS基线 vs LassoCV；alpha网格40个，训练段5折扩张窗口CV
- 训练：2021-2023，每5个交易日抽样；剔除末尾10个标签越界交易日；验证2024；复检2025-01至2026-10
- 冻结：Lasso仅由训练段选alpha并拟合一次；CV折间同样清除标签重叠；验证、复检完全不参与选参
- 组合：每20个交易日调仓，T日信号、T+1收盘成交，top20等权，保守按全换手计费
- 成本：买边0.125%，卖边0.225%；复检段另做双倍成本压力测试
- 对照：全因子OLS、全A等权；top20唯一主配置，不扫描持仓数和参数
- 偏差：数据库缺2021-2025退市股，结果有幸存者偏差，只能按偏乐观口径解读
"""

import json
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LassoCV, LinearRegression
from sklearn.model_selection import TimeSeriesSplit

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "research" / "scorecard-data"
DATA_DIR = PROJECT_ROOT / "research" / "lasso-data"
IMAGE_DIR = PROJECT_ROOT / "articles" / "images"
RESULT_DATE = "2026-11-06"

LABEL_HORIZON = 10
REBALANCE_GAP = 20
TOP_N = 20
TRAIN_SAMPLE_GAP = 5
BUY_COST = 0.00125
SELL_COST = 0.00225
MIN_LIST_ROWS = 250
TRAIN_END = pd.Timestamp("2023-12-31")
VAL_END = pd.Timestamp("2024-12-31")
REVIEW_END = pd.Timestamp("2026-10-31")
ALPHAS = np.logspace(-5, -1, 40)

MOMENTUM = ["mom5", "mom10", "mom20", "mom60", "mom120"]
VOLATILITY = [
    "vol5", "vol10", "vol20", "vol60", "downside20", "maxret20",
    "minret20", "skew20", "kurt20", "amp5", "amp20", "atr20",
]
LIQUIDITY = [
    "turnover5", "turnover20", "turnover60", "turnover_std20",
    "volume_ratio5_20", "amihud20",
]
PRICE_POSITION = [
    "bias5", "bias10", "bias20", "bias60", "pos20", "pos60",
    "ma5_20", "ma20_60",
]
FACTORS = MOMENTUM + VOLATILITY + LIQUIDITY + PRICE_POSITION
assert len(FACTORS) == 31

FACTOR_CN = {
    "mom5": "5日动量", "mom10": "10日动量", "mom20": "20日动量",
    "mom60": "60日动量", "mom120": "120日动量",
    "vol5": "5日波动率", "vol10": "10日波动率", "vol20": "20日波动率",
    "vol60": "60日波动率", "downside20": "20日下行波动",
    "maxret20": "20日最大单日涨幅", "minret20": "20日最大单日跌幅",
    "skew20": "20日收益偏度", "kurt20": "20日收益峰度",
    "amp5": "5日振幅", "amp20": "20日振幅", "atr20": "20日ATR占比",
    "turnover5": "5日换手率", "turnover20": "20日换手率",
    "turnover60": "60日换手率", "turnover_std20": "20日换手波动",
    "volume_ratio5_20": "5/20日成交量比", "amihud20": "20日Amihud非流动性",
    "bias5": "5日乖离率", "bias10": "10日乖离率", "bias20": "20日乖离率",
    "bias60": "60日乖离率", "pos20": "20日价格位置", "pos60": "60日价格位置",
    "ma5_20": "5/20日均线比", "ma20_60": "20/60日均线比",
}


def period_of(dt: pd.Timestamp) -> str:
    if dt <= TRAIN_END:
        return "train"
    if dt <= VAL_END:
        return "validation"
    return "review"


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_parquet(SOURCE_DIR / "ashare_daily_2020plus.parquet")
    info = pd.read_csv(SOURCE_DIR / "ashare_info.csv", dtype={"symbol": str})
    info = info[~info["name"].str.contains("ST|退", na=False)].copy()
    panel = panel[panel["symbol"].isin(set(info["symbol"]))].copy()
    panel = panel.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    return panel, info


def build_sample(panel: pd.DataFrame) -> pd.DataFrame:
    """逐股计算31因子，只保留训练抽样日或调仓日，避免保存八百万行宽表。"""
    calendar = sorted(panel.loc[
        (panel["trade_date"] >= "2021-01-01") & (panel["trade_date"] <= REVIEW_END),
        "trade_date",
    ].unique())
    rebal_dates = set(calendar[::REBALANCE_GAP])
    train_calendar = sorted(d for d in calendar if d <= TRAIN_END)
    train_dates = set(train_calendar[::TRAIN_SAMPLE_GAP])
    keep_dates = rebal_dates | train_dates

    def _per_stock(df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        close = df["close"].where(df["close"] > 0)
        ret = close.pct_change().replace([np.inf, -np.inf], np.nan)
        prev_close = close.shift(1)
        ma = {n: close.rolling(n).mean() for n in [5, 10, 20, 60]}

        for n in [5, 10, 20, 60, 120]:
            df[f"mom{n}"] = close / close.shift(n) - 1
        for n in [5, 10, 20, 60]:
            df[f"vol{n}"] = ret.rolling(n).std()
        df["downside20"] = ret.clip(upper=0).rolling(20).std()
        df["maxret20"] = ret.rolling(20).max()
        df["minret20"] = ret.rolling(20).min()
        df["skew20"] = ret.rolling(20).skew()
        df["kurt20"] = ret.rolling(20).kurt()
        amp = (df["high"] - df["low"]) / close
        df["amp5"] = amp.rolling(5).mean()
        df["amp20"] = amp.rolling(20).mean()
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        df["atr20"] = tr.rolling(20).mean() / close

        for n in [5, 20, 60]:
            df[f"turnover{n}"] = df["turnover_rate"].rolling(n).mean()
        df["turnover_std20"] = df["turnover_rate"].rolling(20).std()
        df["volume_ratio5_20"] = (
            df["volume"].rolling(5).mean() / df["volume"].rolling(20).mean() - 1
        )
        df["amihud20"] = (
            ret.abs() / (df["amount"] / 1e8).where(df["amount"] > 0)
        ).rolling(20).mean()

        for n in [5, 10, 20, 60]:
            df[f"bias{n}"] = close / ma[n] - 1
        for n in [20, 60]:
            low_n = df["low"].rolling(n).min()
            high_n = df["high"].rolling(n).max()
            df[f"pos{n}"] = (close - low_n) / (high_n - low_n).where(high_n > low_n)
        df["ma5_20"] = ma[5] / ma[20] - 1
        df["ma20_60"] = ma[20] / ma[60] - 1

        df[f"fwd{LABEL_HORIZON}"] = close.shift(-LABEL_HORIZON) / close - 1
        hold = close.shift(-(REBALANCE_GAP + 1)) / close.shift(-1) - 1
        fallback = close.iloc[-1] / close.shift(-1) - 1
        df["hold_ret"] = hold.fillna(fallback)
        df.loc[close.shift(-1).isna(), "hold_ret"] = np.nan
        df["listed_rows"] = np.arange(len(df))
        df["is_rebal"] = df["trade_date"].isin(rebal_dates)
        keep = df["trade_date"].isin(keep_dates) & (df["listed_rows"] >= MIN_LIST_ROWS)
        return df.loc[keep]

    sample = panel.groupby("symbol", group_keys=False).apply(_per_stock)
    sample = sample.reset_index(drop=True)
    sample = sample.replace([np.inf, -np.inf], np.nan)
    return sample


def cs_zscore(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """逐日缩尾后标准化；只用当日截面，无未来信息。"""
    out = frame.copy()
    for col in columns:
        grouped = out.groupby("trade_date")[col]
        lo = grouped.transform(lambda s: s.quantile(0.01))
        hi = grouped.transform(lambda s: s.quantile(0.99))
        clipped = out[col].clip(lo, hi)
        mean = clipped.groupby(out["trade_date"]).transform("mean")
        std = clipped.groupby(out["trade_date"]).transform("std")
        out[col] = ((clipped - mean) / std.replace(0, np.nan)).fillna(0.0)
    return out


def make_date_cv(train_df: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    """5折扩张窗口；每折训练尾部清除10日标签重叠区，折边界按完整日期切分。"""
    dates = np.array(sorted(train_df["trade_date"].unique()))
    codes = pd.Categorical(train_df["trade_date"], categories=dates).codes
    indices = np.arange(len(train_df))
    purge_steps = int(np.ceil(LABEL_HORIZON / TRAIN_SAMPLE_GAP))
    splits = []
    for tr_date_idx, va_date_idx in TimeSeriesSplit(n_splits=5).split(dates):
        tr_date_idx = tr_date_idx[:-purge_steps]
        tr_mask = np.isin(codes, tr_date_idx)
        va_mask = np.isin(codes, va_date_idx)
        splits.append((indices[tr_mask], indices[va_mask]))
    return splits


def run_backtest(daily: pd.DataFrame, score_col: str, cost_mult: float = 1.0) -> pd.DataFrame:
    trades = []
    for dt, snap in daily[daily["is_rebal"]].groupby("trade_date"):
        snap = snap.dropna(subset=["hold_ret"])
        if len(snap) < TOP_N * 3:
            continue
        pick = snap.nlargest(TOP_N, score_col)
        gross = float(pick["hold_ret"].mean())
        cost = (SELL_COST + BUY_COST) * cost_mult
        ic_snap = snap.dropna(subset=[f"fwd{LABEL_HORIZON}"])
        trades.append({
            "date": dt,
            "period": period_of(dt),
            "model": score_col,
            "gross": gross,
            "cost": cost,
            "net": gross - cost,
            "ic": snap.loc[ic_snap.index, score_col].corr(
                ic_snap[f"fwd{LABEL_HORIZON}"], method="spearman"
            ),
            "holdings": ",".join(pick["symbol"].astype(str)),
        })
    return pd.DataFrame(trades)


def run_equal_weight(daily: pd.DataFrame, cost_mult: float = 1.0) -> pd.DataFrame:
    trades = []
    for dt, snap in daily[daily["is_rebal"]].groupby("trade_date"):
        snap = snap.dropna(subset=["hold_ret"])
        if len(snap) < 100:
            continue
        gross = float(snap["hold_ret"].mean())
        cost = (SELL_COST + BUY_COST) * 0.05 * cost_mult
        trades.append({
            "date": dt, "period": period_of(dt), "model": "equal_weight",
            "gross": gross, "cost": cost, "net": gross - cost, "ic": np.nan,
            "holdings": "",
        })
    return pd.DataFrame(trades)


def period_metrics(df: pd.DataFrame, ret_col: str = "net") -> dict:
    if df.empty:
        return {}
    df = df.sort_values("date")
    nav = (1 + df[ret_col]).cumprod()
    nav_with_initial = pd.concat([pd.Series([1.0]), nav], ignore_index=True)
    total = nav.iloc[-1] - 1
    days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
    ann = (1 + total) ** (365 / max(days, 1)) - 1
    dd = (nav_with_initial / nav_with_initial.cummax() - 1).min()
    sharpe = df[ret_col].mean() / df[ret_col].std() * np.sqrt(12) if df[ret_col].std() > 0 else 0
    return {
        "total": float(total), "annual": float(ann), "max_drawdown": float(dd),
        "sharpe": float(sharpe), "rebalances": int(len(df)),
        "mean_ic": float(df["ic"].mean()), "gross_total": float((1 + df["gross"]).prod() - 1),
        "cost_sum": float(df["cost"].sum()),
    }


def configure_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "Heiti SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def save_figures(coef: pd.DataFrame, all_bt: pd.DataFrame) -> None:
    configure_chinese_font()
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    selected = coef[coef["lasso"].abs() > 1e-8].sort_values("lasso")
    fig, ax = plt.subplots(figsize=(10, max(4, len(selected) * 0.42)))
    labels = [FACTOR_CN[f] for f in selected["factor"]]
    colors = ["#C65D3B" if v < 0 else "#287D6D" for v in selected["lasso"]]
    ax.barh(labels, selected["lasso"], color=colors)
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_title("Lasso 最终保留因子与系数")
    ax.set_xlabel("标准化系数")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / "lasso-coefficients.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    review = all_bt[all_bt["period"] == "review"]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model, label, color in [
        ("ols_score", "全因子 OLS", "#777777"),
        ("lasso_score", "Lasso", "#C65D3B"),
        ("equal_weight", "全A等权", "#287D6D"),
    ]:
        part = review[review["model"] == model].sort_values("date")
        nav = (1 + part["net"]).cumprod()
        ax.plot(part["date"], nav, label=label, linewidth=2, color=color)
    ax.axhline(1, color="#999999", linewidth=0.8)
    ax.set_title("复检段净值（2025-01 至 2026-10，含成本）")
    ax.set_ylabel("净值")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / "lasso-equity.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("加载全A面板...")
    panel, info = load_panel()
    print(f"面板 {panel.shape}，股票 {panel['symbol'].nunique()} 只；因子数 {len(FACTORS)}")
    market_train_dates = sorted(panel.loc[
        (panel["trade_date"] >= "2021-01-01") & (panel["trade_date"] <= TRAIN_END),
        "trade_date",
    ].unique())
    purge_start = market_train_dates[-LABEL_HORIZON]
    print(f"训练标签边界清除：剔除 {pd.Timestamp(purge_start).date()} 及之后的训练信号日")

    print("计算31因子并抽取训练/调仓截面...")
    sample = build_sample(panel)
    del panel
    sample = sample.dropna(subset=FACTORS, how="any").copy()
    print(f"有效截面样本 {len(sample)}，调仓日 {sample.loc[sample['is_rebal'], 'trade_date'].nunique()} 个")

    print("逐日横截面缩尾与标准化...")
    sample = cs_zscore(sample, FACTORS)
    train = sample[sample["trade_date"] < purge_start].copy()
    # 每5日抽样与调仓日同源（20是5的整数倍）；末尾10个交易日因标签跨入2024而剔除。
    train = train.dropna(subset=[f"fwd{LABEL_HORIZON}"]).copy()
    train = cs_zscore(train, [f"fwd{LABEL_HORIZON}"])
    train = train.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    X = train[FACTORS].to_numpy(dtype=np.float64)
    y = train[f"fwd{LABEL_HORIZON}"].to_numpy(dtype=np.float64)
    print(f"训练样本 {X.shape}，日期 {train['trade_date'].nunique()} 个")

    print("拟合全因子OLS基线...")
    ols = LinearRegression(fit_intercept=False)
    ols.fit(X, y)

    print("LassoCV：训练段5折扩张窗口...")
    cv = make_date_cv(train)
    lasso = LassoCV(
        alphas=ALPHAS, cv=cv, fit_intercept=False, max_iter=5000,
        tol=1e-4, selection="cyclic",
    )
    lasso.fit(X, y)
    print(f"冻结 alpha={lasso.alpha_:.8f}，非零因子 {np.sum(np.abs(lasso.coef_) > 1e-8)}/31")

    print("生成OLS/Lasso样本外分数...")
    inference = sample[sample["is_rebal"]].copy().reset_index(drop=True)
    inference["ols_score"] = ols.predict(inference[FACTORS].to_numpy(dtype=np.float64))
    inference["lasso_score"] = lasso.predict(inference[FACTORS].to_numpy(dtype=np.float64))

    bt_ols = run_backtest(inference, "ols_score")
    bt_lasso = run_backtest(inference, "lasso_score")
    bt_ew = run_equal_weight(inference)
    bt_stress = run_backtest(inference, "lasso_score", cost_mult=2.0)
    all_bt = pd.concat([bt_ols, bt_lasso, bt_ew], ignore_index=True)

    coef = pd.DataFrame({
        "factor": FACTORS,
        "factor_cn": [FACTOR_CN[f] for f in FACTORS],
        "ols": ols.coef_,
        "lasso": lasso.coef_,
    })
    coef["abs_lasso"] = coef["lasso"].abs()
    coef = coef.sort_values("abs_lasso", ascending=False).drop(columns="abs_lasso")

    summary = {
        "date": RESULT_DATE,
        "pre_registration": {
            "factors": FACTORS, "alphas": ALPHAS.tolist(), "cv": "train-only 5-fold expanding date splits",
            "label_horizon": LABEL_HORIZON, "rebalance_gap": REBALANCE_GAP, "top_n": TOP_N,
            "buy_cost": BUY_COST, "sell_cost": SELL_COST,
        },
        "train_rows": int(len(train)), "train_dates": int(train["trade_date"].nunique()),
        "alpha": float(lasso.alpha_), "nonzero": int(np.sum(np.abs(lasso.coef_) > 1e-8)),
        "metrics": {},
        "stress_review_lasso": period_metrics(bt_stress[bt_stress["period"] == "review"]),
        "survivorship_bias": "2021-2025退市股缺失，结果偏乐观",
    }
    for model, df in [("ols", bt_ols), ("lasso", bt_lasso), ("equal_weight", bt_ew)]:
        summary["metrics"][model] = {
            p: period_metrics(df[df["period"] == p]) for p in ["train", "validation", "review"]
        }

    coef.to_csv(DATA_DIR / f"Lasso因子系数-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    all_bt.to_csv(DATA_DIR / f"Lasso因子选择回测明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    bt_stress.to_csv(DATA_DIR / f"Lasso双倍成本压力明细-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({
        "alpha": lasso.alphas_, "cv_mse": lasso.mse_path_.mean(axis=1),
    }).to_csv(DATA_DIR / f"LassoCV路径-{RESULT_DATE}.csv", index=False, encoding="utf-8-sig")
    with open(DATA_DIR / f"Lasso因子选择核心结果-{RESULT_DATE}.json", "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)

    lines = [
        "# Lasso 因子选择回测报告",
        f"> 生成：{RESULT_DATE}；预登记参数见脚本头部。",
        "> 数据与第07篇相同，2021-2025退市股缺失，存在幸存者偏差；复检段只读。",
        "",
        "## 训练与选参",
        f"- 训练样本：{len(train)} 行，{train['trade_date'].nunique()} 个交易日，31个量价因子。",
        f"- LassoCV 冻结 alpha：{lasso.alpha_:.8f}。",
        f"- 非零因子：{np.sum(np.abs(lasso.coef_) > 1e-8)}/31；OLS保留全部31个。",
        "",
        "## 因子系数（按Lasso绝对值排序）",
        "| 因子 | OLS | Lasso |",
        "|---|---:|---:|",
    ]
    for row in coef.itertuples():
        lines.append(f"| {row.factor_cn} | {row.ols:+.6f} | {row.lasso:+.6f} |")
    lines += [
        "",
        "## 主配置：top20月调仓，含成本",
        "| 模型 | 分段 | 区间收益 | 年化 | 最大回撤 | 夏普 | 平均IC | 毛利累计 | 成本简单合计 | 次数 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, label in [("ols", "全因子OLS"), ("lasso", "Lasso"), ("equal_weight", "全A等权")]:
        for p in ["train", "validation", "review"]:
            m = summary["metrics"][model][p]
            lines.append(
                f"| {label} | {p} | {m['total']:.2%} | {m['annual']:.2%} | "
                f"{m['max_drawdown']:.2%} | {m['sharpe']:.2f} | {m['mean_ic']:.4f} | "
                f"{m['gross_total']:.2%} | {m['cost_sum']:.2%} | {m['rebalances']} |"
            )
    stress = summary["stress_review_lasso"]
    lines += [
        "",
        "## Lasso复检段双倍成本压力测试",
        f"- 区间收益 {stress['total']:.2%}，最大回撤 {stress['max_drawdown']:.2%}，夏普 {stress['sharpe']:.2f}。",
        "",
        "## 纪律说明",
        "- 未扫描持仓数、因子组合或回看复检段调参；OLS与Lasso共用同一训练样本、股票池、成本和调仓日。",
        "- 月调仓保守按全换手扣费，与第07篇口径一致；这不同于按真实持仓交集计算换手。",
        "- 本结果不构成收益承诺，也不自动进入模拟盘。",
    ]
    report = "\n".join(lines)
    (DATA_DIR.parent / f"Lasso因子选择回测报告-{RESULT_DATE}.md").write_text(report, encoding="utf-8")
    save_figures(coef, all_bt)
    print("\n" + report)
    print(f"\n已保存：{DATA_DIR}；图表：{IMAGE_DIR}")


if __name__ == "__main__":
    main()
