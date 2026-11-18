#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nQQE 无头计算器。

许可证与第三方署名见项目根目录 NOTICE（MPL-2.0）。
RSI 使用 Wilder RMA，RSII/QQEF 使用首个有效 RSI 播种的 EMA。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Any, Iterable


RSI_PERIOD = 14
RSI_SMOOTHING = 5
WILDER_ALPHA = 1.0 / RSI_PERIOD
ATRRSI_MULTIPLIER = 4.236


@dataclass(frozen=True)
class NqqeState:
    """单根 nQQE 状态；无有效 RSI/QQEF 时使用 ``nan``。"""

    rsi: float = math.nan
    qqef: float = math.nan
    qqes: float = 0.0
    crossover: bool = False
    crossunder: bool = False
    trend: str = "neutral"
    ready: bool = False


def _nz(value: float) -> float:
    return 0.0 if math.isnan(value) else value


def calculate_qqes(
    qqef: float,
    previous_qqef: float,
    atrrsi: float,
    previous_qqes: float,
    atrrsi_multiplier: float = ATRRSI_MULTIPLIER,
) -> float:
    """按源码先后顺序执行 QUP、向上穿越、QDN、向下穿越及回落分支。"""

    previous = _nz(previous_qqes)
    qup = qqef + atrrsi_multiplier * atrrsi
    qdn = qqef - atrrsi_multiplier * atrrsi

    # Python 对 nan 的比较均为 False，与这些 旧版 比较分支一致。
    if qup < previous:
        return qup
    if qqef > previous and previous_qqef < previous:
        return qdn
    if qdn > previous:
        return qdn
    if qqef < previous and previous_qqef > previous:
        return qup
    return previous


def legacy_crossover(
    current_source: float,
    current_target: float,
    previous_source: float,
    previous_target: float,
) -> bool:
    """当前严格上穿且前值满足 ``<=``；任一所需值为 na 时不触发。"""

    if any(
        math.isnan(value)
        for value in (
            current_source,
            current_target,
            previous_source,
            previous_target,
        )
    ):
        return False
    return current_source > current_target and previous_source <= previous_target


def legacy_crossunder(
    current_source: float,
    current_target: float,
    previous_source: float,
    previous_target: float,
) -> bool:
    """当前严格下穿且前值满足 ``>=``；任一所需值为 na 时不触发。"""

    if any(
        math.isnan(value)
        for value in (
            current_source,
            current_target,
            previous_source,
            previous_target,
        )
    ):
        return False
    return current_source < current_target and previous_source >= previous_target


class NqqeCalculator:
    """逐根保存 RSI 涨跌 RMA、EMA、WWMA、ATRRSI 与 QQE 前值。"""

    def __init__(
        self,
        rsi_period: int = RSI_PERIOD,
        rsi_smoothing: int = RSI_SMOOTHING,
        atrrsi_multiplier: float = ATRRSI_MULTIPLIER,
    ):
        if rsi_period < 1 or rsi_smoothing < 1:
            raise ValueError("rsi_period and rsi_smoothing must be positive")
        if not math.isfinite(atrrsi_multiplier) or atrrsi_multiplier <= 0:
            raise ValueError("atrrsi_multiplier must be positive and finite")
        self.rsi_period = int(rsi_period)
        self.rsi_smoothing = int(rsi_smoothing)
        self.atrrsi_multiplier = float(atrrsi_multiplier)
        self.wilder_alpha = 1.0 / self.rsi_period
        self._previous_close: float | None = None
        self._changes: deque[tuple[float, float]] = deque(maxlen=self.rsi_period)
        self._average_gain: float | None = None
        self._average_loss: float | None = None
        self._qqef = math.nan
        self._wwma = math.nan
        self._atrrsi = math.nan
        self._qqes = 0.0

    def _update_rsi(self, close: float) -> float:
        previous_close = self._previous_close
        self._previous_close = close
        if previous_close is None:
            return math.nan

        change = close - previous_close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        if self._average_gain is None or self._average_loss is None:
            self._changes.append((gain, loss))
            if len(self._changes) < self.rsi_period:
                return math.nan
            self._average_gain = math.fsum(item[0] for item in self._changes) / self.rsi_period
            self._average_loss = math.fsum(item[1] for item in self._changes) / self.rsi_period
        else:
            self._average_gain = (
                self.wilder_alpha * gain + (1.0 - self.wilder_alpha) * self._average_gain
            )
            self._average_loss = (
                self.wilder_alpha * loss + (1.0 - self.wilder_alpha) * self._average_loss
            )

        if self._average_loss == 0.0:
            if self._average_gain == 0.0:
                return math.nan
            return 100.0
        relative_strength = self._average_gain / self._average_loss
        return 100.0 - 100.0 / (1.0 + relative_strength)

    def update(self, bar: Any) -> NqqeState:
        """追加一根已完成 K 线，并返回当根不可变状态。"""

        close = float(bar.close_price)
        previous_qqef = self._qqef
        previous_qqes = self._qqes
        rsi = self._update_rsi(close)

        if math.isnan(rsi):
            qqef = math.nan
        elif math.isnan(previous_qqef):
            qqef = rsi
        else:
            alpha = 2.0 / (self.rsi_smoothing + 1.0)
            qqef = alpha * rsi + (1.0 - alpha) * previous_qqef

        if math.isnan(qqef) or math.isnan(previous_qqef):
            true_range = math.nan
        else:
            true_range = abs(qqef - previous_qqef)

        if math.isnan(true_range):
            wwma = math.nan
        else:
            wwma = (
                self.wilder_alpha * true_range
                + (1.0 - self.wilder_alpha) * _nz(self._wwma)
            )

        if math.isnan(wwma):
            atrrsi = math.nan
        else:
            atrrsi = (
                self.wilder_alpha * wwma
                + (1.0 - self.wilder_alpha) * _nz(self._atrrsi)
            )

        qqes = calculate_qqes(
            qqef, previous_qqef, atrrsi, previous_qqes, self.atrrsi_multiplier
        )
        crossover = legacy_crossover(qqef, qqes, previous_qqef, previous_qqes)
        crossunder = legacy_crossunder(qqef, qqes, previous_qqef, previous_qqes)
        if math.isnan(qqef) or 40.0 <= qqef <= 60.0:
            trend = "neutral"
        elif qqef > 60.0:
            trend = "up"
        else:
            trend = "down"

        self._qqef = qqef
        self._wwma = wwma
        self._atrrsi = atrrsi
        self._qqes = qqes
        return NqqeState(
            rsi=rsi,
            qqef=qqef,
            qqes=qqes,
            crossover=crossover,
            crossunder=crossunder,
            trend=trend,
            ready=not (
                math.isnan(rsi) or math.isnan(qqef) or math.isnan(atrrsi)
            ),
        )

    @classmethod
    def compute(
        cls,
        bars: Iterable[Any],
        *,
        rsi_period: int = RSI_PERIOD,
        rsi_smoothing: int = RSI_SMOOTHING,
        atrrsi_multiplier: float = ATRRSI_MULTIPLIER,
    ) -> list[NqqeState]:
        """新建计算器并逐根 update；类级离线入口与在线语义一致。"""

        calculator = cls(
            rsi_period=rsi_period,
            rsi_smoothing=rsi_smoothing,
            atrrsi_multiplier=atrrsi_multiplier,
        )
        return [calculator.update(bar) for bar in bars]


def compute(
    bars: Iterable[Any],
    *,
    rsi_period: int = RSI_PERIOD,
    rsi_smoothing: int = RSI_SMOOTHING,
    atrrsi_multiplier: float = ATRRSI_MULTIPLIER,
) -> list[NqqeState]:
    """保留模块级公开包装器，直接复用类级 compute。"""

    return NqqeCalculator.compute(
        bars,
        rsi_period=rsi_period,
        rsi_smoothing=rsi_smoothing,
        atrrsi_multiplier=atrrsi_multiplier,
    )
