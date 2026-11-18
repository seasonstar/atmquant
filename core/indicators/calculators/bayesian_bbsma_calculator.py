#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bayesian BBSMA 无头计算器。

许可证与第三方署名见项目根目录 NOTICE（MPL-2.0）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class BayesianBbsmaState:
    """单根 K 线的双公式状态；未就绪的概率字段使用 ``nan``。"""

    sma: float = math.nan
    basis: float = math.nan
    upper: float = math.nan
    sigma_up_legacy: float = math.nan
    sigma_down_legacy: float = math.nan
    prime_legacy: float = math.nan
    sigma_up_fixed: float = math.nan
    sigma_down_fixed: float = math.nan
    prime_fixed: float = math.nan
    long_legacy: bool = False
    short_legacy: bool = False
    long_fixed: bool = False
    short_fixed: bool = False
    ready: bool = False


def legacy_nz(value: float | None, replacement: float = 0.0) -> float:
    """复刻 旧版 ``nz``：仅把 ``na``（Python 中为 None/nan）替换掉。"""

    if value is None or math.isnan(value):
        return replacement
    return value


def legacy_ratio(numerator: float, denominator: float) -> float:
    """执行 旧版 风格除法，零分母及 na 输入产生 ``nan`` 而非 Python 异常。"""

    if math.isnan(numerator) or math.isnan(denominator) or denominator == 0:
        return math.nan
    return numerator / denominator


def sigma_legacy(a: float, b: float, c: float) -> float:
    """保留 ``a*b*c/a*b*c + complement`` 的 旧版 左结合链与最终 ``nz``。"""

    complement = (1.0 - a) * (1.0 - b) * (1.0 - c)
    chain = legacy_ratio(a * b * c, a)
    chain = chain * b
    chain = chain * c
    return legacy_nz(chain + complement)


def sigma_fixed(a: float, b: float, c: float) -> float:
    """仅修正总分母：``product / (product + complement)``，最终应用 ``nz``。"""

    product = a * b * c
    complement = (1.0 - a) * (1.0 - b) * (1.0 - c)
    return legacy_nz(legacy_ratio(product, product + complement))


def prime_legacy(sigma_down: float, sigma_up: float) -> float:
    """保留 ``down*up/down*up + complement`` 的原始左结合链。"""

    complement = (1.0 - sigma_down) * (1.0 - sigma_up)
    chain = legacy_ratio(sigma_down * sigma_up, sigma_down)
    chain = chain * sigma_up
    return legacy_nz(chain + complement)


def prime_fixed(sigma_down: float, sigma_up: float) -> float:
    """仅修正 prime 的总分母括号，零总分母经 ``nz`` 归零。"""

    product = sigma_down * sigma_up
    complement = (1.0 - sigma_down) * (1.0 - sigma_up)
    return legacy_nz(legacy_ratio(product, product + complement))


class BayesianBbsmaCalculator:
    """逐根消费 BarData，维护价格、比较事件窗口及前一状态。"""

    def __init__(
        self,
        period: int = 20,
        lookback: int = 20,
        stddev_mult: float = 2.5,
        lower_threshold: float = 0.15,
    ):
        if period < 1 or lookback < 1:
            raise ValueError("period and lookback must be positive")

        self.period = period
        self.lookback = lookback
        self.stddev_mult = stddev_mult
        self.lower_threshold = lower_threshold

        self._closes: deque[float] = deque(maxlen=period)
        # 每根依次为 upper/basis/SMA 的 up/down 六个事件；basis 与 SMA 不去重。
        self._events: deque[tuple[int, int, int, int, int, int]] = deque(
            maxlen=lookback
        )
        self._previous_state: BayesianBbsmaState | None = None

    def update(self, bar: Any) -> BayesianBbsmaState:
        """追加一根已完成 K 线，并返回当根不可变状态。"""

        close = float(bar.close_price)
        self._closes.append(close)

        sma = math.nan
        upper = math.nan
        if len(self._closes) == self.period:
            sma = math.fsum(self._closes) / self.period
            variance = (
                math.fsum((value - sma) ** 2 for value in self._closes)
                / self.period
            )
            upper = sma + self.stddev_mult * math.sqrt(variance)

            # tista 源码的 ternary 序列：严格大于/小于，相等时两个事件均为 0。
            self._events.append(
                (
                    int(close > upper),
                    int(close < upper),
                    int(close > sma),
                    int(close < sma),
                    int(close > sma),
                    int(close < sma),
                )
            )

        ready = len(self._events) == self.lookback
        if not ready:
            state = BayesianBbsmaState(sma=sma, basis=sma, upper=upper)
            self._previous_state = state
            return state

        counts = [sum(event[index] for event in self._events) for index in range(6)]
        upper_up, upper_down, basis_up, basis_down, sma_up, sma_down = counts

        # 源码先求各轨道上下滚动比例，再归一化为 P(up)/P(down)；相等会使分母变小。
        prob_up_upper = legacy_ratio(upper_up, upper_up + upper_down)
        prob_up_basis = legacy_ratio(basis_up, basis_up + basis_down)
        prob_up_sma = legacy_ratio(sma_up, sma_up + sma_down)
        prob_down_upper = legacy_ratio(upper_down, upper_up + upper_down)
        prob_down_basis = legacy_ratio(basis_down, basis_up + basis_down)
        prob_down_sma = legacy_ratio(sma_down, sma_up + sma_down)

        # 保持源码方向：sigmaProbsDown 使用 probUp*，sigmaProbsUp 使用 probDown*。
        sigma_down_legacy = sigma_legacy(prob_up_upper, prob_up_basis, prob_up_sma)
        sigma_up_legacy = sigma_legacy(
            prob_down_upper, prob_down_basis, prob_down_sma
        )
        sigma_down_fixed = sigma_fixed(prob_up_upper, prob_up_basis, prob_up_sma)
        sigma_up_fixed = sigma_fixed(
            prob_down_upper, prob_down_basis, prob_down_sma
        )
        prime_legacy_value = prime_legacy(sigma_down_legacy, sigma_up_legacy)
        prime_fixed_value = prime_fixed(sigma_down_fixed, sigma_up_fixed)

        previous = self._previous_state
        if previous is None:
            prev_prime_legacy = prev_prime_fixed = math.nan
            prev_sigma_up_legacy = prev_sigma_up_fixed = math.nan
            prev_sigma_down_legacy = prev_sigma_down_fixed = math.nan
        else:
            prev_prime_legacy = previous.prime_legacy
            prev_prime_fixed = previous.prime_fixed
            prev_sigma_up_legacy = previous.sigma_up_legacy
            prev_sigma_up_fixed = previous.sigma_up_fixed
            prev_sigma_down_legacy = previous.sigma_down_legacy
            prev_sigma_down_fixed = previous.sigma_down_fixed

        long_legacy = (
            prime_legacy_value > self.lower_threshold and prev_prime_legacy == 0
        ) or (sigma_up_legacy < 1 and prev_sigma_up_legacy == 1)
        short_legacy = (
            prime_legacy_value == 0 and prev_prime_legacy > self.lower_threshold
        ) or (sigma_down_legacy < 1 and prev_sigma_down_legacy == 1)
        long_fixed = (
            prime_fixed_value > self.lower_threshold and prev_prime_fixed == 0
        ) or (sigma_up_fixed < 1 and prev_sigma_up_fixed == 1)
        short_fixed = (
            prime_fixed_value == 0 and prev_prime_fixed > self.lower_threshold
        ) or (sigma_down_fixed < 1 and prev_sigma_down_fixed == 1)

        state = BayesianBbsmaState(
            sma=sma,
            basis=sma,
            upper=upper,
            sigma_up_legacy=sigma_up_legacy,
            sigma_down_legacy=sigma_down_legacy,
            prime_legacy=prime_legacy_value,
            sigma_up_fixed=sigma_up_fixed,
            sigma_down_fixed=sigma_down_fixed,
            prime_fixed=prime_fixed_value,
            long_legacy=long_legacy,
            short_legacy=short_legacy,
            long_fixed=long_fixed,
            short_fixed=short_fixed,
            ready=True,
        )
        self._previous_state = state
        return state


def compute(
    bars: Iterable[Any],
    *,
    period: int = 20,
    lookback: int = 20,
    stddev_mult: float = 2.5,
    lower_threshold: float = 0.15,
) -> list[BayesianBbsmaState]:
    """新建逐根计算器并顺序消费 bars；批量路径不包含另一套公式。"""

    calculator = BayesianBbsmaCalculator(
        period=period,
        lookback=lookback,
        stddev_mult=stddev_mult,
        lower_threshold=lower_threshold,
    )
    return [calculator.update(bar) for bar in bars]
