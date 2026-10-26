# ATMTrader 策略开发指南

## 概述

本目录包含ATMTrader项目的自研量化策略。所有策略都基于vnpy框架开发，并集成了日志和告警系统。

## 目录结构

```
core/strategies/
├── __init__.py
├── base_strategy.py              # 基础策略类（推荐使用）
├── base_cta_strategy_v2.py       # V2版本基础策略类（旧版）
├── triple_ma_strategy.py         # 三均线策略示例
├── single_symbol_ai_strategy.py   # 单品种AI策略（统一AI引擎）
├── atm_strategy_for_ni_v2.py     # 镍期货专用策略V2
└── README.md                     # 本文件
```

## 基础策略类

### BaseCtaStrategy（推荐）

所有新策略都应继承自`BaseCtaStrategy`，它基于vnpy的`CtaTemplate`扩展，添加了以下核心功能：

- **自动交易时段识别**：根据品种代码自动识别市场类型（中国期货、美股、港股等）
- **交易时段感知的K线合成**：小时K线按照实际交易时段合成，而非简单的时钟小时
- **日志系统集成**：使用loguru自动记录策略运行日志
- **告警系统集成**：支持飞书、钉钉等实时告警通知
- **状态管理**：跟踪策略运行状态

### 使用方法

```python
from core.strategies.base_strategy import BaseCtaStrategy

class MyStrategy(BaseCtaStrategy):
    """我的策略"""

    # 策略参数
    fast_window = 10
    slow_window = 20

    # 策略变量
    fast_ma = 0.0
    slow_ma = 0.0

    parameters = ["fast_window", "slow_window"]
    variables = ["fast_ma", "slow_ma"]

    def on_init(self):
        """策略初始化"""
        super().on_init()
        self.logger.info(f"策略初始化: {self.strategy_name}")

    def on_start(self):
        """策略启动"""
        super().on_start()
        self.logger.info(f"策略启动: {self.strategy_name}")

    def on_bar(self, bar):
        """K线数据更新"""
        # 你的策略逻辑
        pass
```

### BaseCtaStrategyV2（旧版）

这是早期版本的基础策略类，包含更多内置功能（如数据库交易记录、复杂的时段判断等）。新策略建议使用`BaseCtaStrategy`，它更简洁且与vnpy生态更兼容。

## 内置策略

### 三均线策略 (TripleMaStrategy)

一个经典的多时间周期移动平均策略，继承自`BaseCtaStrategy`，支持以下特性：

#### 核心参数

- `short_window`: 短期均线周期 (默认: 7)
- `mid_window`: 中期均线周期 (默认: 55)
- `long_window`: 长期均线周期 (默认: 100)
- `ma_type`: 均线类型，支持"SMA"和"EMA" (默认: "SMA")

#### 多时间周期

- `signal_timeframe`: 信号时间周期 (默认: 5分钟)
- `trade_timeframe`: 交易时间周期 (默认: 5分钟)

#### 风险控制

- `stop_loss_pct`: 止损百分比 (默认: 2.0%)
- `take_profit_pct`: 止盈百分比 (默认: 4.0%)
- `trailing_stop_pct`: 跟踪止损百分比 (默认: 0.5%)

#### 交易信号

- **做多信号**: 短期MA向上穿过中期MA，且交叉点位于长期MA上方
- **做空信号**: 短期MA向下穿过中期MA，且交叉点位于长期MA下方

### 单品种AI策略 (SingleSymbolAIStrategy)

基于统一AI策略引擎的单品种交易策略，回测时通过 `BacktestAdapter` 复用决策与缓存能力。

### 镍期货专用策略V2 (ATMStrategyForNiV2)

针对镍期货品种优化的专用策略，包含特定的风险控制和交易逻辑。

## 策略开发指南

### 1. 创建新策略

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
我的策略
"""

from .base_strategy import BaseCtaStrategy

class MyStrategy(BaseCtaStrategy):
    """我的策略"""

    # 策略作者
    author = "Your Name"

    # 策略参数
    fast_window = 10
    slow_window = 20

    # 策略变量
    fast_ma = 0.0
    slow_ma = 0.0

    parameters = ["fast_window", "slow_window"]
    variables = ["fast_ma", "slow_ma"]

    def on_init(self):
        """策略初始化"""
        super().on_init()
        self.logger.info(f"策略初始化: {self.strategy_name}")
        # 加载历史数据
        self.load_bar(10)

    def on_start(self):
        """策略启动"""
        super().on_start()
        self.logger.info(f"策略启动: {self.strategy_name}")

    def on_bar(self, bar):
        """K线数据更新"""
        # 更新K线到ArrayManager
        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        # 计算指标
        self.fast_ma = am.sma(self.fast_window)
        self.slow_ma = am.sma(self.slow_window)

        # 交易逻辑
        if self.pos == 0:
            if self.fast_ma > self.slow_ma:
                self.buy(bar.close_price, 1)
        elif self.pos > 0:
            if self.fast_ma < self.slow_ma:
                self.sell(bar.close_price, abs(self.pos))
```

### 2. 交易时段配置

`BaseCtaStrategy`会自动识别品种的交易时段。如需自定义，可以重写`trading_session`属性：

```python
from config.trading_sessions_config import TradingSession, MarketType
from datetime import time

class MyStrategy(BaseCtaStrategy):
    """自定义交易时段的策略"""

    # 重写交易时段
    trading_session = TradingSession(
        market_type=MarketType.CHINA_FUTURES,
        day_start=time(9, 0),
        day_end=time(15, 0),
        night_start=time(21, 0),
        night_end=time(2, 30)
    )
```

### 3. 策略回测

使用vnpy的回测引擎进行策略回测：

```python
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy.trader.constant import Interval
from datetime import datetime

# 创建回测引擎
engine = BacktestingEngine()

# 设置回测参数
engine.set_parameters(
    vt_symbol="rb2505.SHFE",
    interval=Interval.MINUTE,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    rate=0.0001,
    slippage=0.2,
    size=10,
    pricetick=1,
    capital=1_000_000,
)

# 添加策略
engine.add_strategy(MyStrategy, {})

# 加载数据
engine.load_data()

# 运行回测
engine.run_backtesting()

# 计算统计指标
df = engine.calculate_result()
engine.calculate_statistics()

# 显示图表
engine.show_chart()
```

### 4. 实盘部署

在ATMTrader主程序中：
1. 启动主程序：`python main.py`
2. 进入CTA策略模块
3. 添加策略，选择你的策略类
4. 配置参数和交易品种
5. 初始化并启动策略

## 最佳实践

### 1. 代码规范

- 遵循PEP 8代码规范
- 使用类型注解提高代码可读性
- 添加详细的中文注释说明业务逻辑
- 保持函数和类的单一职责
- 策略文件头部添加清晰的文档字符串

### 2. 参数设计

- 参数名应清晰表达其用途（如`fast_window`而非`param1`）
- 提供合理的默认值，基于历史回测结果
- 将所有可调参数添加到`parameters`列表，支持参数优化
- 避免参数过多导致过拟合（建议不超过5-7个核心参数）
- 使用类型注解标注参数类型

### 3. 风险控制

- **必须实现止损机制**：每笔交易都应设置止损价
- **控制仓位大小**：根据账户资金和风险承受能力动态调整
- **避免过度交易**：设置交易频率限制，避免高频交易
- **监控策略表现**：定期检查策略收益率、最大回撤等指标
- **使用跟踪止损**：保护已有利润，让盈利奔跑

### 4. 日志和监控

- 使用`self.logger`记录关键操作（开仓、平仓、止损触发等）
- 监控策略状态变化（初始化、启动、停止）
- 通过`alert_manager`发送重要告警（大额亏损、异常情况）
- 定期检查日志文件，发现潜在问题
- 记录策略参数变更历史

### 5. 交易时段处理

- 利用`BaseCtaStrategy`的自动交易时段识别功能
- 小时K线会按照实际交易时段合成，无需手动处理
- 如需自定义交易时段，重写`trading_session`属性
- 注意夜盘跨日问题，使用策略提供的时段判断方法

## 故障排除

### 常见问题

1. **策略加载失败**
   - 检查策略文件语法是否正确（运行`python -m py_compile your_strategy.py`）
   - 确认继承自`BaseCtaStrategy`而非`CtaTemplate`
   - 检查`parameters`和`variables`列表是否正确定义
   - 查看日志文件：`logs/strategy_运行日期.log`

2. **参数设置错误**
   - 确保参数类型正确（整数、浮点数、字符串等）
   - 检查参数范围是否合理（如周期不能为负数）
   - 验证默认值是否在合理范围内
   - 参数名必须在`parameters`列表中声明

3. **交易信号异常**
   - 检查数据质量：使用`am.inited`确保数据充足
   - 验证指标计算：打印中间结果检查计算逻辑
   - 调试信号逻辑：使用日志记录每次信号触发的条件
   - 注意浮点数比较：使用`abs(a - b) < 0.0001`而非`a == b`

4. **K线合成问题**
   - 小时K线自动按交易时段合成，无需手动处理
   - 如果K线数据异常，检查`trading_session`配置
   - 使用`self.logger.debug()`记录K线合成过程

5. **性能问题**
   - 避免在`on_tick()`中进行复杂计算
   - 使用`ArrayManager`缓存历史数据
   - 减少不必要的日志输出
   - 优化指标计算逻辑，避免重复计算

### 调试技巧

1. **使用日志系统**（推荐）
   ```python
   # 不同级别的日志
   self.logger.debug("详细调试信息")
   self.logger.info("一般信息")
   self.logger.warning("警告信息")
   self.logger.error("错误信息")

   # 记录变量值
   self.logger.info(f"当前持仓: {self.pos}, 均线: {self.fast_ma:.2f}")
   ```

2. **使用断点调试**
   ```python
   # 在关键位置设置断点
   import pdb; pdb.set_trace()

   # 或使用IDE的断点功能（推荐）
   ```

3. **回测模式下的调试**
   ```python
   # 在on_bar中打印关键信息
   if self.trading:  # 只在实盘模式打印
       self.logger.info(f"Bar时间: {bar.datetime}, 价格: {bar.close_price}")
   ```

4. **使用vnpy的write_log**
   ```python
   # 输出到vnpy主界面日志窗口
   self.write_log(f"策略状态: {self.strategy_status}")
   ```

## 进阶主题

### 1. 多周期策略

利用不同周期K线进行趋势判断和交易执行：

```python
class MultiPeriodStrategy(BaseCtaStrategy):
    """多周期策略示例"""

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        # 创建多周期K线生成器
        self.bg5 = BarGenerator(self.on_bar, 5, self.on_5min_bar)
        self.bg15 = BarGenerator(self.on_bar, 15, self.on_15min_bar)

    def on_bar(self, bar):
        """1分钟K线"""
        self.bg5.update_bar(bar)
        self.bg15.update_bar(bar)

    def on_5min_bar(self, bar):
        """5分钟K线 - 用于交易执行"""
        pass

    def on_15min_bar(self, bar):
        """15分钟K线 - 用于趋势判断"""
        pass
```

### 2. 组合指标策略

结合多个技术指标提高信号可靠性：

```python
def on_bar(self, bar):
    """组合多个指标"""
    am = self.am
    am.update_bar(bar)
    if not am.inited:
        return

    # 计算多个指标
    ma_fast = am.sma(10)
    ma_slow = am.sma(20)
    rsi = am.rsi(14)
    macd, signal, hist = am.macd(12, 26, 9)

    # 组合信号
    long_signal = (ma_fast > ma_slow) and (rsi < 70) and (macd > signal)
    short_signal = (ma_fast < ma_slow) and (rsi > 30) and (macd < signal)
```

### 3. 动态仓位管理

根据市场波动率和账户风险动态调整仓位：

```python
def calculate_position_size(self, bar):
    """动态计算仓位大小"""
    # 获取ATR（平均真实波幅）
    atr = self.am.atr(14)

    # 风险金额（账户的1%）
    risk_amount = self.capital * 0.01

    # 止损距离（2倍ATR）
    stop_distance = atr * 2

    # 计算仓位
    position_size = int(risk_amount / stop_distance)

    return position_size
```

## 相关资源

### 文档

- [vnpy官方文档](https://www.vnpy.com/docs/cn/index.html)
- [ATMTrader项目文档](../README.md)
- [配置管理指南](../../config/README.md)
- [图表系统文档](../charts/README.md)

### 示例代码

- `triple_ma_strategy.py` - 三均线策略完整实现
- `single_symbol_ai_strategy.py` - 单品种AI策略实现
- `scripts/` - 回测和优化脚本

### 学习资源

- **《以AI量化为生》系列文章** - 微信公众号"量策堂"
- **《量化指标解码》系列** - 技术指标深度解析
- **知识星球：量策堂·AI算法指标策略** - 付费会员专享内容

## 贡献指南

欢迎贡献新策略或改进现有策略：

1. Fork项目到你的GitHub账号
2. 创建功能分支：`git checkout -b feature/my-strategy`
3. 编写策略代码，遵循代码规范
4. 添加必要的文档和注释
5. 提交代码：`git commit -m "feat: 添加XXX策略"`
6. 推送到远程：`git push origin feature/my-strategy`
7. 创建Pull Request

## 许可证

本项目采用MIT许可证，详见LICENSE文件。

## 联系方式

如有问题或建议，欢迎通过以下方式联系：

- **GitHub Issues**: [提交问题](https://github.com/seasonstar/atmquant/issues)
- **微信公众号**: 量策堂（搜索"量策堂"）
- **知识星球**: 量策堂·AI算法指标策略

---

*本文档持续更新中，最后更新时间：2026-01-22*
