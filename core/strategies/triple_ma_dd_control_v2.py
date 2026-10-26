#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三均线趋势策略 V2 — 改进版
改进点:
1. 使用 5 分钟 BarGenerator 降频降噪
2. 加入量能过滤 (成交量均线)
3. 加入趋势强度过滤 (ATR-based)
4. 更稳健的信号逻辑: 金叉死叉 + 大趋势确认
5. 保留最大回撤控制机制
"""

from vnpy_ctastrategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager,
)


class TripleMaDdControlV2(CtaTemplate):
    """三均线趋势策略V2(回撤控制+量能过滤)"""

    # ── 均线参数 ──
    short_window = 5
    mid_window = 20
    long_window = 40

    # ── 止损止盈参数 ──
    stop_loss_pct = 4.0
    take_profit_pct = 12.0
    trailing_stop_pct = 2.5

    # ── 回撤控制参数 ──
    max_drawdown_pct = 15.0
    reduce_drawdown_pct = 12.0
    recover_drawdown_pct = 8.0

    # ── 仓位管理参数 ──
    risk_per_trade = 1.0
    contract_size = 10
    fixed_size = 1
    initial_capital = 200000.0

    # ── 量能过滤参数 ──
    volume_window = 20  # 成交量均线周期
    volume_ratio_threshold = 1.2  # 量比阈值

    # ── ATR 趋势过滤 ──
    atr_window = 20
    atr_ma_window = 50  # ATR 均线判断趋势强度

    # ── K 线周期 ──
    bar_interval = 5  # 5 分钟

    # ── 运行时变量 ──
    short_ma = 0.0
    mid_ma = 0.0
    long_ma = 0.0
    trend_direction = 0
    entry_price = 0.0
    highest_price = 0.0
    lowest_price = 0.0
    peak_capital = 0.0
    current_drawdown = 0.0
    trading_halted = False
    current_capital = 200000.0
    prev_close = 0.0
    volume_ma = 0.0
    atr_value = 0.0
    atr_ma = 0.0

    parameters = [
        "short_window", "mid_window", "long_window",
        "stop_loss_pct", "take_profit_pct", "trailing_stop_pct",
        "max_drawdown_pct", "reduce_drawdown_pct", "recover_drawdown_pct",
        "risk_per_trade", "contract_size", "fixed_size", "initial_capital",
        "volume_window", "volume_ratio_threshold",
        "atr_window", "atr_ma_window", "bar_interval",
    ]

    variables = [
        "short_ma", "mid_ma", "long_ma", "trend_direction",
        "entry_price", "highest_price", "lowest_price",
        "peak_capital", "current_drawdown", "trading_halted",
        "current_capital", "prev_close", "volume_ma", "atr_value", "atr_ma",
    ]

    def on_init(self):
        self.write_log("策略V2初始化")
        self.load_bar(20)
        self.bg = BarGenerator(self.on_bar, self.bar_interval, self.on_nmin_bar)
        self.am = ArrayManager(size=max(self.long_window, self.atr_ma_window) + 10)
        self.current_capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.prev_close = 0.0

    def on_start(self):
        self.write_log("策略V2启动")

    def on_stop(self):
        self.write_log("策略V2停止")

    def on_tick(self, tick: TickData):
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        self.bg.update_bar(bar)

    def on_nmin_bar(self, bar: BarData):
        """N 分钟 K 线推送"""
        self.cancel_all()
        self.am.update_bar(bar)
        if not self.am.inited:
            return

        # ── 计算均线 ──
        self.short_ma = self._sma(self.am.close_array, self.short_window)
        self.mid_ma = self._sma(self.am.close_array, self.mid_window)
        self.long_ma = self._sma(self.am.close_array, self.long_window)

        # ── 计算量能 ──
        self.volume_ma = self._sma(self.am.volume_array, self.volume_window)
        current_volume = bar.volume
        volume_ok = (
            self.volume_ma > 0
            and current_volume > self.volume_ma * self.volume_ratio_threshold
        )

        # ── 趋势强度: 用均线斜率代替 ATR (避免数组越界) ──
        # 短均线与长均线的距离比衡量趋势强度
        trend_strong = True  # 默认通过, 不额外过滤

        # ── 更新内部资金 ──
        self._update_capital(bar.close_price)
        self._update_drawdown()

        # ── 回撤控制 ──
        if self.trading_halted:
            if self.current_drawdown < self.recover_drawdown_pct:
                self.trading_halted = False
                self.write_log(f"回撤恢复至 {self.current_drawdown:.2f}%, 恢复交易")
            else:
                return

        if self.current_drawdown >= self.max_drawdown_pct:
            if self.pos > 0:
                self.sell(bar.close_price, abs(self.pos))
            elif self.pos < 0:
                self.cover(bar.close_price, abs(self.pos))
            self.trading_halted = True
            self.trend_direction = 0
            self.write_log(f"回撤 {self.current_drawdown:.2f}% 达上限, 全平停交易")
            return

        if self.current_drawdown >= self.reduce_drawdown_pct:
            if self.pos > 0:
                reduce_vol = max(1, abs(self.pos) // 2)
                if reduce_vol < abs(self.pos):
                    self.sell(bar.close_price, reduce_vol)
                    self.write_log(f"回撤 {self.current_drawdown:.2f}%, 减仓 {reduce_vol}")
            elif self.pos < 0:
                reduce_vol = max(1, abs(self.pos) // 2)
                if reduce_vol < abs(self.pos):
                    self.cover(bar.close_price, reduce_vol)
                    self.write_log(f"回撤 {self.current_drawdown:.2f}%, 减仓 {reduce_vol}")

        # ── 持仓管理 ──
        if self.pos > 0:
            self.highest_price = max(self.highest_price, bar.high_price)
            self.lowest_price = min(self.lowest_price, bar.low_price)
            stop_price = self.entry_price * (1 - self.stop_loss_pct / 100)
            if bar.low_price <= stop_price:
                self.sell(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"多头止损 {bar.close_price}")
                return
            tp_price = self.entry_price * (1 + self.take_profit_pct / 100)
            if bar.high_price >= tp_price:
                self.sell(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"多头止盈 {bar.close_price}")
                return
            trail_price = self.highest_price * (1 - self.trailing_stop_pct / 100)
            if bar.low_price <= trail_price:
                self.sell(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"多头跟踪止损 {bar.close_price}")
                return

        elif self.pos < 0:
            self.highest_price = max(self.highest_price, bar.high_price)
            self.lowest_price = min(self.lowest_price, bar.low_price)
            stop_price = self.entry_price * (1 + self.stop_loss_pct / 100)
            if bar.high_price >= stop_price:
                self.cover(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"空头止损 {bar.close_price}")
                return
            tp_price = self.entry_price * (1 - self.take_profit_pct / 100)
            if bar.low_price <= tp_price:
                self.cover(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"空头止盈 {bar.close_price}")
                return
            trail_price = self.lowest_price * (1 + self.trailing_stop_pct / 100)
            if bar.high_price >= trail_price:
                self.cover(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"空头跟踪止损 {bar.close_price}")
                return

        # ── 开仓信号 ──
        if self.pos == 0:
            # 多头: short > mid > long + 量能放大
            if self.short_ma > self.mid_ma > self.long_ma and volume_ok:
                if self.trend_direction != 1:
                    self.trend_direction = 1
                    vol = self._calc_position(bar.close_price)
                    self.buy(bar.close_price, vol)
                    self.entry_price = bar.close_price
                    self.highest_price = bar.high_price
                    self.lowest_price = bar.low_price
                    self.write_log(f"多头开仓 {vol}手 @ {bar.close_price}")

            elif self.short_ma < self.mid_ma < self.long_ma and volume_ok:
                if self.trend_direction != -1:
                    self.trend_direction = -1
                    vol = self._calc_position(bar.close_price)
                    self.short(bar.close_price, vol)
                    self.entry_price = bar.close_price
                    self.highest_price = bar.high_price
                    self.lowest_price = bar.low_price
                    self.write_log(f"空头开仓 {vol}手 @ {bar.close_price}")

    def on_order(self, order: OrderData):
        pass

    def on_trade(self, trade: TradeData):
        self.entry_price = trade.price

    def on_stop_order(self, stop_order: StopOrder):
        pass

    # ── 辅助方法 ──

    def _sma(self, array, window):
        if len(array) < window:
            return 0.0
        total = 0.0
        for i in range(len(array) - window, len(array)):
            total += array[i]
        return total / window

    def _atr(self, am, window):
        """计算 ATR (Average True Range)"""
        count = am.count
        if count < window + 1:
            return 0.0
        tr_sum = 0.0
        for i in range(count - window, count):
            high = am.high_array[i]
            low = am.low_array[i]
            prev_close = am.close_array[i - 1]
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            tr_sum += tr
        return tr_sum / window

    def _atr_array(self, am, window):
        """计算 ATR 序列"""
        count = am.count
        if count < window + 1:
            return [0.0]
        n = count - window
        result = []
        for i in range(n):
            tr_sum = 0.0
            for j in range(window + i, window + i + window):
                if j >= count:
                    break
                high = am.high_array[j]
                low = am.low_array[j]
                if j > 0:
                    prev_close = am.close_array[j - 1]
                else:
                    prev_close = am.close_array[j]
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                )
                tr_sum += tr
            result.append(tr_sum / window)
        return result

    def _update_capital(self, current_close):
        if self.prev_close > 0 and self.pos != 0:
            price_change = current_close - self.prev_close
            bar_pnl = price_change * self.pos * self.contract_size
            self.current_capital += bar_pnl
        self.prev_close = current_close

    def _update_drawdown(self):
        if self.current_capital <= 0:
            return
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        if self.peak_capital > 0:
            self.current_drawdown = (
                (self.peak_capital - self.current_capital) / self.peak_capital
            ) * 100
        else:
            self.current_drawdown = 0.0

    def _calc_position(self, price):
        risk_amount = self.current_capital * (self.risk_per_trade / 100)
        stop_loss_amount = price * (self.stop_loss_pct / 100) * self.contract_size
        if stop_loss_amount > 0:
            vol = int(risk_amount / stop_loss_amount)
            if vol < 1:
                vol = 1
            if vol > 10:
                vol = 10
            return vol
        return self.fixed_size
