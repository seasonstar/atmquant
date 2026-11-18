"""Pure portfolio-construction helpers for the frozen-Lasso experiment."""

import pandas as pd

BUY_COST = 0.00125
SELL_COST = 0.00225


def select_buffered_holdings(
    scores: pd.Series,
    amounts: pd.Series,
    previous: set[str],
    holdings_n: int = 50,
    exit_rank: int = 100,
    liquidity_pct: float = 0.0,
) -> list[str]:
    """Retain eligible old holdings inside exit_rank, then fill by score rank."""
    frame = pd.DataFrame({"score": scores, "amount": amounts}).dropna()
    if liquidity_pct > 0 and not frame.empty:
        threshold = frame["amount"].quantile(liquidity_pct)
        frame = frame[frame["amount"] >= threshold]
    frame = frame.sort_values("score", ascending=False)
    ranked = frame.index.astype(str).tolist()
    rank_of = {symbol: rank for rank, symbol in enumerate(ranked, start=1)}
    retained = [s for s in ranked if s in previous and rank_of[s] <= exit_rank]
    retained = retained[:holdings_n]
    chosen = set(retained)
    for symbol in ranked:
        if len(retained) >= holdings_n:
            break
        if symbol not in chosen:
            retained.append(symbol)
            chosen.add(symbol)
    return sorted(retained, key=rank_of.get)


def equal_weights(holdings: list[str], exposure: float = 1.0) -> dict[str, float]:
    """Return fractional equity weights; unallocated exposure stays in cash."""
    if not holdings or exposure <= 0:
        return {}
    weight = min(max(exposure, 0.0), 1.0) / len(holdings)
    return {symbol: weight for symbol in holdings}


def compute_turnover_cost(
    previous_weights: dict[str, float],
    target_weights: dict[str, float],
    buy_cost: float = BUY_COST,
    sell_cost: float = SELL_COST,
) -> tuple[float, float, float]:
    """Compute one-way buy/sell turnover and asymmetric trading cost."""
    symbols = set(previous_weights) | set(target_weights)
    buy = sum(max(target_weights.get(s, 0.0) - previous_weights.get(s, 0.0), 0.0) for s in symbols)
    sell = sum(max(previous_weights.get(s, 0.0) - target_weights.get(s, 0.0), 0.0) for s in symbols)
    cost = buy * buy_cost + sell * sell_cost
    return buy, sell, cost


import numpy as np


def historical_exposure(
    returns_by_symbol: dict[str, pd.Series],
    holdings: list[str],
    signal_date: pd.Timestamp,
    target_vol: float = 0.12,
    lookback: int = 60,
    min_obs: int = 40,
    previous_exposure: float = 1.0,
) -> tuple[float, int, float]:
    """Estimate target-holding volatility using only data through signal_date."""
    if not holdings:
        return 0.0, 0, float("nan")
    series = [returns_by_symbol[s].rename(s) for s in holdings if s in returns_by_symbol]
    if not series:
        return previous_exposure, 0, float("nan")
    panel = pd.concat(series, axis=1).sort_index()
    panel = panel.loc[panel.index <= signal_date].tail(lookback)
    portfolio_returns = panel.mean(axis=1, skipna=True).dropna()
    count = len(portfolio_returns)
    if count < min_obs:
        return previous_exposure, count, float("nan")
    annual_vol = float(portfolio_returns.std(ddof=1) * np.sqrt(252))
    if not np.isfinite(annual_vol) or annual_vol <= 0:
        return previous_exposure, count, float("nan")
    exposure = min(1.0, target_vol / annual_vol)
    return float(exposure), count, annual_vol


from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioConfig:
    name: str
    holdings_n: int
    exit_rank: int
    liquidity_pct: float = 0.0
    vol_target: float | None = None


def run_portfolio_backtest(
    daily: pd.DataFrame,
    returns_by_symbol: dict[str, pd.Series],
    config: PortfolioConfig,
    buy_cost: float = BUY_COST,
    sell_cost: float = SELL_COST,
) -> pd.DataFrame:
    """Run B-E style backtests with actual target-weight turnover."""
    records = []
    previous_weights: dict[str, float] = {}
    previous_exposure = 1.0
    for dt, snap in daily[daily["is_rebal"]].groupby("trade_date", sort=True):
        snap = snap.dropna(subset=["lasso_score", "hold_ret", "amount"])
        if snap.empty:
            continue
        scores = snap.set_index("symbol")["lasso_score"]
        amounts = snap.set_index("symbol")["amount"]
        holdings = select_buffered_holdings(
            scores, amounts, set(previous_weights), config.holdings_n,
            config.exit_rank, config.liquidity_pct,
        )
        exposure = 1.0
        vol_obs = 0
        annual_vol = float("nan")
        if config.vol_target is not None:
            exposure, vol_obs, annual_vol = historical_exposure(
                returns_by_symbol, holdings, dt, config.vol_target,
                previous_exposure=previous_exposure,
            )
        target_weights = equal_weights(holdings, exposure)
        buy, sell, cost = compute_turnover_cost(
            previous_weights, target_weights, buy_cost, sell_cost,
        )
        hold_ret = snap.set_index("symbol")["hold_ret"]
        gross = exposure * float(hold_ret.reindex(holdings).mean()) if holdings else 0.0
        records.append({
            "date": dt, "model": config.name, "holdings": ",".join(holdings),
            "gross": gross, "net": gross - cost, "buy": buy, "sell": sell,
            "cost": cost, "exposure": exposure, "vol_obs": vol_obs,
            "annual_vol": annual_vol,
        })
        previous_weights = target_weights
        previous_exposure = exposure
    result = pd.DataFrame(records)
    if not result.empty:
        result["period"] = result["date"].map(
            lambda d: "train" if d <= pd.Timestamp("2023-12-31")
            else "validation" if d <= pd.Timestamp("2024-12-31") else "review"
        )
    return result
