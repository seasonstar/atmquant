# AI策略引擎模块

## 概述

AI策略引擎是ATMTrader的核心AI决策模块，为中国期货交易提供完整的AI决策能力。

## 核心特性

- **数据字典系统**：定义所有AI需要理解的市场数据字段
- **思维链提取**：支持多种格式（<thinking>、<reasoning>、特殊标记）
- **JSON自动修复**：修复中文引号、括号等编码问题
- **七种操作类型**：LONG/SHORT/CLOSE/HOLD/ADD_LONG/ADD_SHORT/REDUCE
- **双重风控机制**：硬限制（代码强制）+ 软限制（AI引导）
- **品种选择系统**：从活跃合约池中选择合适的交易品种
- **品种评分排序**：综合流动性、波动率、趋势强度评分

## 模块结构

```
core/ai_strategy_engine/
├── __init__.py                 # 模块初始化
├── engine.py                   # AI策略引擎核心
├── schema/                     # 数据字典系统
│   ├── __init__.py
│   └── futures_schema.py      # 中国期货数据字典
├── decision/                   # 决策处理模块
│   ├── __init__.py
│   ├── parser.py              # 增强响应解析器
│   ├── executor.py            # 决策执行器
│   └── validator.py           # 决策验证器
├── risk/                       # 风险管理模块
│   ├── __init__.py
│   ├── manager.py             # 风险管理器
│   ├── position_sizer.py      # 仓位计算器
│   └── limits.py              # 风险限制定义
├── selection/                  # 品种选择模块
│   ├── __init__.py
│   ├── selector.py            # 品种选择器
│   └── ranking.py             # 品种评分器
└── prompts/                    # 提示词管理模块
    ├── __init__.py
    └── builder.py             # 提示词构建器
```

## 配置文件

AI策略引擎使用集中式配置管理，所有参数都可以通过配置文件自定义：

### 配置文件列表

| 配置文件 | 说明 |
|---------|------|
| [config/ai_strategy_config.py](../../config/ai_strategy_config.py) | 风险限制、交易模式、AI配置、仓位计算等 |
| [config/ai_prompt_components.py](../../config/ai_prompt_components.py) | 提示词组件、技术指标阈值、数据处理参数 |
| [config/ai_indicators_config.py](../../config/ai_indicators_config.py) | 技术指标参数（EMA、MACD、RSI等） |

### 自定义配置

#### 1. 修改风险限制

```python
# config/ai_strategy_config.py
RISK_LIMITS = {
    "hard_limits": {
        "max_positions": 3,          # 最大持仓品种数
        "max_position_value": 0.3,   # 单品种最大仓位
        "min_confidence": 0.5,       # 最小置信度
        "max_daily_loss": 0.05,      # 日最大亏损
    },
    # ...
}
```

#### 2. 修改交易模式

```python
# config/ai_strategy_config.py
TRADING_MODES = {
    "conservative": {
        "position_size_range": (0.1, 0.2),
        "min_confidence": 0.7,
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.05,
        # ...
    },
    # ...
}
```

#### 3. 修改提示词组件

```python
# config/ai_prompt_components.py
PROMPT_COMPONENTS = {
    "role_definition": """# 角色定义
你是一个专业的中国期货量化交易AI助手...
""",
    # ...
}
```

#### 4. 修改技术指标阈值

```python
# config/ai_prompt_components.py
INDICATOR_THRESHOLDS = {
    "ema_diff_threshold": 0.2,      # EMA差异阈值
    "rsi_overbought": 70,           # RSI超买阈值
    "rsi_oversold": 30,             # RSI超卖阈值
    # ...
}
```

## 快速开始

### 单品种AI策略

```python
from core.strategies.single_symbol_ai_strategy import SingleSymbolAIStrategy

# 在回测引擎或CTA引擎的策略配置中使用
strategy_setting = {
    "ai_model": "deepseek-chat",
    "api_key": "your-api-key",
    "primary_timeframe": "1h",
    "secondary_timeframe": "15m",
    "decision_interval": 1,
    "trading_mode": "conservative",
    "max_position_size": 0.3,
    "enable_cache": True,
}
```

回测模式下，策略通过 `BacktestAdapter` 复用统一AI引擎并启用决策缓存；`BacktestAdapter` 是策略内部协作者，不是独立的回测入口。

### 核心引擎使用

```python
from core.ai_strategy_engine.engine import AIStrategyEngine, AIStrategyConfig

# 创建配置
config = AIStrategyConfig(
    ai_model="gpt-3.5-turbo",
    api_key="your-api-key",
    max_position_size=0.3,
    trading_mode="conservative",  # 通过trading_mode设置min_confidence
)

# 创建引擎
engine = AIStrategyEngine(config)

# 执行决策周期
result = engine.run_cycle(strategy, current_bar)

if result.success:
    print(f"AI决策: {result.decision.action}")
    print(f"思维链: {result.reasoning}")
```

## 数据字典系统

数据字典定义了所有AI需要理解的市场数据字段，确保AI正确理解中国期货数据格式。

### 支持的字段类别

| 类别 | 说明 | 示例字段 |
|------|------|---------|
| PRICE_FIELDS | 价格数据 | open, high, low, close, volume |
| INDICATOR_FIELDS | 技术指标 | sma, ema, macd, rsi, atr |
| ACCOUNT_FIELDS | 账户信息 | balance, available, total_pnl |
| POSITION_FIELDS | 持仓信息 | symbol, direction, size, entry_price |

### 使用示例

```python
from core.ai_strategy_engine.schema.futures_schema import futures_schema

# 获取完整Schema
schema = futures_schema.get_full_schema()

# 获取特定类别
price_fields = futures_schema.get_schema_definition("PRICE")

# 在系统提示词中使用
system_prompt = f"""
{schema}

# 风险控制要求
...
"""
```

## 决策流程

```
1. 构建交易上下文 (ContextBuilder)
   ↓
2. 生成系统提示词 (PromptBuilder + Schema)
   ↓
3. 生成用户提示词 (PromptBuilder + Context)
   ↓
4. 调用AI模型 (AIClientFactory)
   ↓
5. 解析AI响应 (EnhancedDecisionParser)
   - 提取思维链
   - 修复JSON编码
   - 验证决策格式
   ↓
6. 验证决策 (DecisionValidator)
   - 硬限制检查
   - 软限制检查
   - 清算风险检测
   ↓
7. 执行决策 (DecisionExecutor)
   - 转换为vnpy订单
   - 更新策略状态
   - 记录决策历史
```

## 风险管理

### 硬限制（代码强制执行）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_positions | 3 | 最大持仓品种数 |
| max_position_value | 0.3 | 单品种最大仓位比例（30%） |
| max_leverage | 1.5 | 最大杠杆倍数 |
| min_confidence | 0.5 | 最小置信度 |
| max_daily_loss | 0.05 | 最大日亏损比例（5%） |

### 软限制（AI引导）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| target_reward_ratio | 2.0 | 目标盈亏比（2:1） |
| max_correlation | 0.8 | 最大品种相关性 |

### 风险检查示例

```python
from core.ai_strategy_engine.risk.manager import RiskManager

risk_manager = RiskManager()

# 验证决策
validation = risk_manager.validate(
    decision={
        "action": "LONG",
        "position_size": 0.3,
        "confidence": 0.75,
    },
    account_balance=100000,
    available_margin=100000,
    current_positions=2,
)

if validation.is_valid:
    print("决策符合风险要求")
else:
    print(f"错误: {validation.errors}")
    print(f"警告: {validation.warnings}")
```

## 品种选择系统

品种选择器自动从活跃合约池中选择合适的交易品种。

### 品种类别

- **黑色系**：螺纹钢(rb)、热卷(hc)、铁矿石(i)、焦炭(j)、焦煤(jm)
- **化工系**：PTA(ta)、甲醇(ma)、玻璃(fg)、纯碱(sa)、橡胶(ru)
- **有色金属**：铜(cu)、铝(al)、锌(zn)、铅(pb)、镍(ni)、锡(sn)
- **农产品**：豆粕(m)、豆油(y)、玉米(c)、棕榈油(p)、棉花(cf)
- **能源化工**：原油(sc)、燃料油(fu)

### 使用示例

```python
from core.ai_strategy_engine.selection.selector import SymbolSelector
from core.ai_strategy_engine.selection.ranking import SymbolRanker

selector = SymbolSelector()
ranker = SymbolRanker()

# 获取候选品种
candidates = selector.get_candidate_symbols(
    current_time=datetime.now(),
    max_candidates=5
)

# 对品种评分排序
ranked = ranker.rank(candidates, datetime.now())
```

## 配置说明

### AI模型配置

支持通过环境变量或直接传入配置：

```bash
# .env文件
DEEPSEEK_API_KEY=your-api-key
CLAUDE_API_KEY=your-api-key
GEMINI_API_KEY=your-api-key
```

### 策略参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| ai_model | str | "gpt-3.5-turbo" | AI模型名称 |
| api_key | str | "" | API密钥 |
| decision_interval | int | 5 | 决策间隔（K线数） |
| max_position_size | float | 0.3 | 最大仓位比例 |
| min_confidence | float | 0.5 | 最小置信度 |
| stop_loss_pct | float | 0.02 | 止损百分比 |
| take_profit_pct | float | 0.05 | 止盈百分比 |

## 注意事项

1. **API密钥管理**：不要将API密钥硬编码在代码中，使用环境变量或配置文件
2. **交易时段**：策略会自动识别品种的交易时段，无需手动配置
3. **风险控制**：始终设置止损止盈，避免单笔亏损过大
4. **AI响应解析**：系统会自动修复常见的JSON格式问题
5. **多品种交易**：注意不同品种的相关性，避免过度集中

## 相关文档

- [AI回测适配器](backtest_adapter.py)
- [AI缓存](cache.py)
- [AI客户端](../ai_clients/README.md)
- [策略基类](../strategies/base_strategy.py)
- [配置管理](../../config/)
