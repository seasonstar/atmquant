"""
三均线趋势跟踪策略 — 带最大回撤控制

改进点:
1. 最大回撤控制: 12% 减仓 50%, 15% 全部平仓停止, 回撤恢复到 8% 以下恢复交易
2. 仓位管理: 基于风险百分比计算仓位 (risk_per_trade = 1%)
3. 参数优化: short=10, mid=30, long=60, stop_loss=2%, take_profit=6%, trailing=1.5%
4. 内部资金跟踪: 逐bar跟踪权益, 不依赖外部引擎接口
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


class TripleMaDdControl(CtaTemplate):
    """三均线趋势策略(带最大回撤控制)"""

    # ── 均线参数 ──
    short_window = 10
    mid_window = 30
    long_window = 60

    # ── 止损止盈参数 ──
    stop_loss_pct = 2.0       # 止损百分比
    take_profit_pct = 6.0     # 止盈百分比
    trailing_stop_pct = 1.5   # 跟踪止损百分比

    # ── 回撤控制参数 ──
    max_drawdown_pct = 15.0     # 最大回撤阈值(全部平仓+停止交易)
    reduce_drawdown_pct = 12.0  # 减仓阈值(减仓50%)
    recover_drawdown_pct = 8.0  # 恢复交易阈值

    # ── 仓位管理参数 ──
    risk_per_trade = 1.0       # 每笔交易风险百分比
    contract_size = 10         # 合约乘数(螺纹钢10吨/手)
    fixed_size = 1             # 默认固定手数(fallback)
    initial_capital = 200000.0  # 初始资金

    # ── 运行时变量 ──
    short_ma = 0.0
    mid_ma = 0.0
    long_ma = 0.0
    trend_direction = 0        # 1=多, -1=空, 0=无
    entry_price = 0.0
    highest_price = 0.0
    lowest_price = 0.0

    # ── 回撤控制变量 ──
    peak_capital = 0.0
    current_drawdown = 0.0
    trading_halted = False
    current_capital = 200000.0
    prev_close = 0.0           # 上一根bar收盘价

    parameters = [
        "short_window",
        "mid_window",
        "long_window",
        "stop_loss_pct",
        "take_profit_pct",
        "trailing_stop_pct",
        "max_drawdown_pct",
        "reduce_drawdown_pct",
        "recover_drawdown_pct",
        "risk_per_trade",
        "contract_size",
        "fixed_size",
        "initial_capital",
    ]

    variables = [
        "short_ma",
        "mid_ma",
        "long_ma",
        "trend_direction",
        "entry_price",
        "highest_price",
        "lowest_price",
        "peak_capital",
        "current_drawdown",
        "trading_halted",
        "current_capital",
        "prev_close",
    ]

    def on_init(self):
        """策略初始化"""
        self.write_log("策略初始化")
        self.load_bar(20)
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=self.long_window + 10)
        self.current_capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.prev_close = 0.0

    def on_start(self):
        """策略启动"""
        self.write_log("策略启动")

    def on_stop(self):
        """策略停止"""
        self.write_log("策略停止")

    def on_tick(self, tick: TickData):
        """Tick推送"""
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        """Bar推送"""
        self.cancel_all()
        self.am.update_bar(bar)
        if not self.am.inited:
            return

        # ── 计算均线(纯Python) ──
        self.short_ma = self._sma(self.am.close_array, self.short_window)
        self.mid_ma = self._sma(self.am.close_array, self.mid_window)
        self.long_ma = self._sma(self.am.close_array, self.long_window)

        # ── 更新内部资金(逐bar跟踪持仓盈亏) ──
        self._update_capital(bar.close_price)
        self._update_drawdown()

        # ── 回撤控制逻辑 ──
        if self.trading_halted:
            if self.current_drawdown < self.recover_drawdown_pct:
                self.trading_halted = False
                self.write_log(
                    f"回撤恢复至 {self.current_drawdown:.2f}%, 恢复交易"
                )
            else:
                return

        # 回撤达到最大阈值: 全部平仓并停止交易
        if self.current_drawdown >= self.max_drawdown_pct:
            if self.pos > 0:
                self.sell(bar.close_price, abs(self.pos))
                self.write_log(
                    f"回撤 {self.current_drawdown:.2f}% 达到上限, 全部平仓"
                )
            elif self.pos < 0:
                self.cover(bar.close_price, abs(self.pos))
                self.write_log(
                    f"回撤 {self.current_drawdown:.2f}% 达到上限, 全部平仓"
                )
            self.trading_halted = True
            self.trend_direction = 0
            return

        # 回撤达到减仓阈值: 减仓50%
        if self.current_drawdown >= self.reduce_drawdown_pct:
            if self.pos > 0:
                reduce_vol = max(1, abs(self.pos) // 2)
                if reduce_vol < abs(self.pos):
                    self.sell(bar.close_price, reduce_vol)
                    self.write_log(
                        f"回撤 {self.current_drawdown:.2f}%, 减仓 {reduce_vol} 手"
                    )
            elif self.pos < 0:
                reduce_vol = max(1, abs(self.pos) // 2)
                if reduce_vol < abs(self.pos):
                    self.cover(bar.close_price, reduce_vol)
                    self.write_log(
                        f"回撤 {self.current_drawdown:.2f}%, 减仓 {reduce_vol} 手"
                    )

        # ── 持仓管理: 止损/止盈/跟踪止损 ──
        if self.pos > 0:
            self.highest_price = max(self.highest_price, bar.high_price)
            self.lowest_price = min(self.lowest_price, bar.low_price)

            stop_price = self.entry_price * (1 - self.stop_loss_pct / 100)
            if bar.low_price <= stop_price:
                self.sell(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"多头止损, 价格 {bar.close_price}")
                return

            take_profit_price = self.entry_price * (
                1 + self.take_profit_pct / 100
            )
            if bar.high_price >= take_profit_price:
                self.sell(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"多头止盈, 价格 {bar.close_price}")
                return

            trailing_stop_price = self.highest_price * (
                1 - self.trailing_stop_pct / 100
            )
            if bar.low_price <= trailing_stop_price:
                self.sell(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"多头跟踪止损, 价格 {bar.close_price}")
                return

        elif self.pos < 0:
            self.highest_price = max(self.highest_price, bar.high_price)
            self.lowest_price = min(self.lowest_price, bar.low_price)

            stop_price = self.entry_price * (1 + self.stop_loss_pct / 100)
            if bar.high_price >= stop_price:
                self.cover(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"空头止损, 价格 {bar.close_price}")
                return

            take_profit_price = self.entry_price * (
                1 - self.take_profit_pct / 100
            )
            if bar.low_price <= take_profit_price:
                self.cover(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"空头止盈, 价格 {bar.close_price}")
                return

            trailing_stop_price = self.lowest_price * (
                1 + self.trailing_stop_pct / 100
            )
            if bar.high_price >= trailing_stop_price:
                self.cover(bar.close_price, abs(self.pos))
                self.trend_direction = 0
                self.write_log(f"空头跟踪止损, 价格 {bar.close_price}")
                return

        # ── 趋势判断与开仓信号 ──
        if self.pos == 0:
            # 多头排列: short > mid > long
            if self.short_ma > self.mid_ma > self.long_ma:
                if self.trend_direction != 1:
                    self.trend_direction = 1
                    vol = self._calc_position(bar.close_price)
                    self.buy(bar.close_price, vol)
                    self.entry_price = bar.close_price
                    self.highest_price = bar.high_price
                    self.lowest_price = bar.low_price
                    self.write_log(
                        f"多头开仓 {vol} 手, 价格 {bar.close_price}"
                    )

            # 空头排列: short < mid < long
            elif self.short_ma < self.mid_ma < self.long_ma:
                if self.trend_direction != -1:
                    self.trend_direction = -1
                    vol = self._calc_position(bar.close_price)
                    self.short(bar.close_price, vol)
                    self.entry_price = bar.close_price
                    self.highest_price = bar.high_price
                    self.lowest_price = bar.low_price
                    self.write_log(
                        f"空头开仓 {vol} 手, 价格 {bar.close_price}"
                    )

    def on_order(self, order: OrderData):
        """委托推送"""
        pass

    def on_trade(self, trade: TradeData):
        """成交推送"""
        self.entry_price = trade.price

    def on_stop_order(self, stop_order: StopOrder):
        """停止单推送"""
        pass

    # ── 辅助方法 ──

    def _sma(self, array, window):
        """纯Python计算简单移动平均"""
        if len(array) < window:
            return 0.0
        total = 0.0
        for i in range(len(array) - window, len(array)):
            total += array[i]
        return total / window

    def _update_capital(self, current_close):
        """
        逐bar更新内部资金
        通过持仓与价格变化计算盈亏
        """
        if self.prev_close > 0 and self.pos != 0:
            price_change = current_close - self.prev_close
            bar_pnl = price_change * self.pos * self.contract_size
            self.current_capital += bar_pnl

        self.prev_close = current_close

    def _update_drawdown(self):
        """更新资金曲线峰值与当前回撤"""
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
        """
        基于风险百分比计算仓位
        仓位 = (capital * risk_per_trade%) / (stop_loss_pct% * contract_size * price)
        """
        risk_amount = self.current_capital * (self.risk_per_trade / 100)
        stop_loss_amount = (
            price * (self.stop_loss_pct / 100) * self.contract_size
        )
        if stop_loss_amount > 0:
            vol = int(risk_amount / stop_loss_amount)
            if vol < 1:
                vol = 1
            if vol > 10:
                vol = 10
            return vol
        return self.fixed_size
