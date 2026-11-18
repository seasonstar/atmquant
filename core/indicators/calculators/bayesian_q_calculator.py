#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bayesian BBSMA 与 nQQE 的单根事件组合计算器。

许可证与第三方署名见项目根目录 NOTICE（MPL-2.0）。
signals 只表达当根 -1/0/+1 事件；持仓延续与反手由后续策略负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .bayesian_bbsma_calculator import BayesianBbsmaCalculator, BayesianBbsmaState
from .nqqe_calculator import NqqeCalculator, NqqeState


MODEL_NAMES = (
    "bayes_legacy",
    "bayes_fixed",
    "nqqe",
    "bayes_q_legacy",
    "bayes_q_fixed",
    "sma_momentum",
)


@dataclass(frozen=True)
class BayesianQState:
    """同一根 K 线的 BBSMA、nQQE 原始状态与六模型事件。"""

    bayes: BayesianBbsmaState
    nqqe: NqqeState
    signals: dict[str, int]


def _event(long: bool, short: bool) -> int:
    if long:
        return 1
    if short:
        return -1
    return 0


def calculate_signals(
    close_price: float,
    bayes: BayesianBbsmaState,
    nqqe: NqqeState,
) -> dict[str, int]:
    """将两份当根状态映射为冻结的六模型事件，不保存任何仓位。"""

    nqqe_event = _event(nqqe.crossover, nqqe.crossunder)
    bayes_q_legacy = 0
    bayes_q_fixed = 0
    if bayes.ready:
        if nqqe_event == 1 and bayes.sigma_up_legacy > bayes.sigma_down_legacy:
            bayes_q_legacy = 1
        elif nqqe_event == -1 and bayes.sigma_down_legacy > bayes.sigma_up_legacy:
            bayes_q_legacy = -1

        if nqqe_event == 1 and bayes.sigma_up_fixed > bayes.sigma_down_fixed:
            bayes_q_fixed = 1
        elif nqqe_event == -1 and bayes.sigma_down_fixed > bayes.sigma_up_fixed:
            bayes_q_fixed = -1

    if close_price > bayes.sma:
        sma_momentum = 1
    elif close_price < bayes.sma:
        sma_momentum = -1
    else:
        sma_momentum = 0

    return {
        "bayes_legacy": _event(bayes.long_legacy, bayes.short_legacy),
        "bayes_fixed": _event(bayes.long_fixed, bayes.short_fixed),
        "nqqe": nqqe_event,
        "bayes_q_legacy": bayes_q_legacy,
        "bayes_q_fixed": bayes_q_fixed,
        "sma_momentum": sma_momentum,
    }


class BayesianQCalculator:
    """每根 K 线恰好更新一个 BBSMA 和一个 nQQE 计算器。"""

    def __init__(
        self,
        bb_period: int = 20,
        bb_stddev_mult: float = 2.5,
        bayes_lookback: int = 20,
        lower_threshold: float = 0.15,
        rsi_period: int = 14,
        rsi_smoothing: int = 5,
        atrrsi_multiplier: float = 4.236,
    ):
        bayes_kwargs = {
            "period": bb_period,
            "lookback": bayes_lookback,
            "stddev_mult": bb_stddev_mult,
            "lower_threshold": lower_threshold,
        }
        nqqe_kwargs = {
            "rsi_period": rsi_period,
            "rsi_smoothing": rsi_smoothing,
            "atrrsi_multiplier": atrrsi_multiplier,
        }
        # 默认路径保留原构造调用与数值行为；自定义参数必须进入实际递推。
        if (
            bb_period == 20 and bb_stddev_mult == 2.5 and bayes_lookback == 20
            and lower_threshold == 0.15
        ):
            self._bayes = BayesianBbsmaCalculator()
        else:
            self._bayes = BayesianBbsmaCalculator(**bayes_kwargs)
        if rsi_period == 14 and rsi_smoothing == 5 and atrrsi_multiplier == 4.236:
            self._nqqe = NqqeCalculator()
        else:
            self._nqqe = NqqeCalculator(**nqqe_kwargs)

    def update(self, bar: Any) -> BayesianQState:
        bayes = self._bayes.update(bar)
        nqqe = self._nqqe.update(bar)
        signals = calculate_signals(float(bar.close_price), bayes, nqqe)
        return BayesianQState(bayes=bayes, nqqe=nqqe, signals=signals)

    @classmethod
    def compute(
        cls,
        bars: Iterable[Any],
        *,
        bb_period: int = 20,
        bb_stddev_mult: float = 2.5,
        bayes_lookback: int = 20,
        lower_threshold: float = 0.15,
        rsi_period: int = 14,
        rsi_smoothing: int = 5,
        atrrsi_multiplier: float = 4.236,
    ) -> list[BayesianQState]:
        """新建组合计算器并逐根 update；类级离线入口与在线语义一致。"""

        calculator = cls(
            bb_period=bb_period,
            bb_stddev_mult=bb_stddev_mult,
            bayes_lookback=bayes_lookback,
            lower_threshold=lower_threshold,
            rsi_period=rsi_period,
            rsi_smoothing=rsi_smoothing,
            atrrsi_multiplier=atrrsi_multiplier,
        )
        return [calculator.update(bar) for bar in bars]


def compute(
    bars: Iterable[Any],
    *,
    bb_period: int = 20,
    bb_stddev_mult: float = 2.5,
    bayes_lookback: int = 20,
    lower_threshold: float = 0.15,
    rsi_period: int = 14,
    rsi_smoothing: int = 5,
    atrrsi_multiplier: float = 4.236,
) -> list[BayesianQState]:
    """保留模块级公开包装器，直接复用类级 compute。"""

    return BayesianQCalculator.compute(
        bars,
        bb_period=bb_period,
        bb_stddev_mult=bb_stddev_mult,
        bayes_lookback=bayes_lookback,
        lower_threshold=lower_threshold,
        rsi_period=rsi_period,
        rsi_smoothing=rsi_smoothing,
        atrrsi_multiplier=atrrsi_multiplier,
    )
