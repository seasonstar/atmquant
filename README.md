# ATMQuant - 开源AI量化交易框架

> 基于 vnpy 4.4 的开源 AI 量化交易框架：多周期图表、图表内交易与风控、AI 策略引擎与指标计算管线已纳入本仓库，便于二次开发与学习。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## 特性

- **多周期图表** - 双图/四图视图、周期切换与交互（扩展 ViewBox、光标管理等）
- **图表内交易与风控** - `TradingManager` / `PositionManager` / `RiskMonitor`：委托与持仓线可视化、止损止盈与价格预警、多合约按 `vt_symbol` 隔离状态（配合 `vnpy_charttrader` 等插件使用）
- **AI 分析与数据采集** - `AIAnalysisCoordinator`、市场分析提示词与 `market_data_collector`，便于对接多模型做盘面解读
- **AI 策略引擎** - `core/ai_strategy_engine/`：期货数据字典、上下文与提示词构建、决策解析/校验/执行、双层风控、品种筛选与评分、回测适配与缓存；参数集中在 `config/ai_*.py`
- **指标计算管线** - `core/indicators/calculators/` 与图表指标解耦，策略与回测可复用同一套计算逻辑
- **策略与回测** - 策略基类、`single_symbol_ai_strategy` 等示例路径；回测存储模型与参数管理（`core/utils/strategy_param_manager.py`、`core/models/backtest_storage_models.py`）
- **工程配套** - 日志与告警、JSON 修复与文本工具（`utils/`）、`requirements.txt` 与 `.env` 配置入口

详细模块说明见 `core/ai_strategy_engine/README.md`、`config/README.md`。

## 知识星球（进阶指标与深度内容）

本仓库已包含上述核心工程能力。若你希望系统跟进**更高阶的指标实现、独家策略与参数经验、系列文章配套的扩展资料**，欢迎加入知识星球（内容与开源代码互补，持续更新）：

- 高级指标专题与更多品种化实现（如 SuperTrend、ZLEMA、斐波那契入场带、挤压动量、SMC 相关等深度文章配套）
- 实战策略拆解、参数与风控思路（星球内沉淀版本）
- 与《量化指标解码》等专栏同步的扩展阅读与答疑场景

👉 加入知识星球：[量策堂·AI算法指标策略](https://t.zsxq.com/Y2m2V)

![](https://files.mdnice.com/user/125063/1ec3cb46-a645-430d-8715-fce52cf84e87.jpg)

---

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置设置

```bash
# 复制配置文件
cp .env.example .env

# 编辑配置文件，填入你的CTP账户信息
vim .env

# 启动程序（自动加载配置）
python main.py
```

## 项目结构

```
atmquant/                          # 项目根目录
├── 📁 core/                        # 核心业务模块
│   ├── 📁 ai_strategy_engine/      # AI 策略引擎（schema/上下文/提示词/决策/风控/选品/回测适配）
│   ├── 📁 charts/                  # 图表组件
│   │   ├── components/             # 光标、可扩展 ViewBox 等
│   │   ├── managers/               # 交易、持仓、风控、AI 分析协调
│   │   ├── prompts/                # 市场分析类提示词
│   │   ├── utils/                  # 行情采集等
│   │   ├── enhanced_chart_widget.py
│   │   ├── dual_chart_widget.py
│   │   └── quad_chart_widget.py
│   ├── 📁 indicators/              # 技术指标（含 calculators/ 计算子包）
│   ├── 📁 models/                  # 领域模型（含回测存储模型）
│   ├── 📁 utils/                   # 如 strategy_param_manager
│   ├── 📁 data/                    # 数据处理
│   ├── 📁 logging/                 # 日志与告警
│   └── 📁 strategies/              # 策略基类与示例策略
├── 📁 config/                      # 配置（settings、告警、AI/回测/指标集中配置、strategy_params）
├── 📁 vnpy_spreadtrading/          # 价差交易模块（可选）
├── 📁 vnpy_tqsdk/                  # 天勤数据源（可选）
├── 📁 scripts/                     # 运行脚本
├── 📁 backtests/                   # 回测相关
├── 📁 utils/                       # 通用工具（json_repair、文本等）
├── 📁 tests/                       # 测试
├── 📁 docs/                        # 文档
├── 📁 examples/                    # 示例
├── 📁 articles/                    # 公众号文章（若本地存在，默认不纳入版本库）
├── 📁 logs/                        # 日志输出目录
├── 📁 vnpy/                        # VeighNa 框架
├── 📄 main.py                      # 主入口（CTP、CTA、回测、ChartTrader 等）
├── 📄 requirements.txt
└── 📄 README.md
```

实时 K 线图表入口依赖 vnpy 生态中的 **ChartTrader** 等应用（见 `main.py` 加载项），与本仓库 `core/charts` 增强组件配合使用。

## 📚 系列文章

### 以AI量化为生系列（交易系统开发）

从零开始搭建完整的量化交易系统，涵盖环境配置、数据管理、策略开发、回测优化、图表可视化等全流程。

1. **[以AI量化为生：普通人如何从无到有稳步构建交易系统](https://mp.weixin.qq.com/s/vHL2ZNoqe65dGn9qEQzLgQ)**
   - 量化交易入门指南
   - 系统架构设计思路
   - 学习路径规划

2. **[以AI量化为生：2.手把手搭建专业量化开发环境](https://mp.weixin.qq.com/s/AFFntmIN6rAFmlk03aIzoA)**
   - Python环境配置
   - vnpy框架安装
   - 开发工具设置

3. **[以AI量化为生：3.vnpy插件安装与配置指南](https://mp.weixin.qq.com/s/0LQ0CLgvKuTMccVPP99WfQ)**
   - vnpy插件生态介绍
   - 核心插件安装配置
   - 常见问题解决

4. **[以AI量化为生：4.vnpy配置管理与系统集成](https://mp.weixin.qq.com/s/XjDe1nD1tDXyJwQweeGCSA)**
   - 轻量级配置管理方案
   - 数据库配置
   - 数据源接入
   - 邮件通知设置

5. **[以AI量化为生：5.期货数据定时下载与合约管理](https://mp.weixin.qq.com/s/r6ravF0YqtbvLcnXToX1Ug)**
   - 期货合约类型详解
   - 智能合约管理系统
   - 定时数据下载实现
   - 数据质量监控

6. **[以AI量化为生：6.日志系统与告警机制设计](https://mp.weixin.qq.com/s/90iZrNuY6qSZ5ZIP4q0nyQ)**
   - 基于loguru的高性能异步日志系统
   - 飞书、钉钉告警机器人配置

7. **[以AI量化为生：7.编写自己的第一个量化策略](https://mp.weixin.qq.com/s/lhTv5r7W5pM5O3osZq0vGA)**
   - vnpy策略开发基础教学
   - 经典策略分析与学习
   - 3MA多时间周期策略实现
   - 动态止盈止损机制设计

8. **[以AI量化为生：8.回测框架优化与重要指标增强](https://mp.weixin.qq.com/s/8Lin92Dm_yG1ZtAHfCb3uA)**
   - vnpy回测框架深度解析
   - 增强型回测指标实现
   - 交易对分析与统计算法
   - 智能评级系统设计

9. **[以AI量化为生：9.回测框架再优化与参数导出功能实现](https://mp.weixin.qq.com/s/iMEmoRekqAf-I3MS9mr0dQ)**
   - 参数回测结果导出功能
   - 滚动夏普比率图表实现

10. **[以AI量化为生：10.回测界面大改版与用户体验全面提升](https://mp.weixin.qq.com/s/9EbD1Qh-ux1mU1gYOt2vOA)**
    - 界面布局重新设计
    - 核心指标卡片式展示
    - 完整指标分组与图表集成
    - 成交记录、委托记录、每日盈亏等优化展示

11. **[以AI量化为生：11.增强版K线图表系统开发实战](https://mp.weixin.qq.com/s/dC1jXfPDsDXumvyOSQQcOw)**
    - 增强版K线图表系统架构设计
    - 主图技术指标实现（布林带、SMA、EMA）
    - 副图技术指标实现（MACD、RSI、DMI、成交量）
    - 交互控制功能（复选框控制、参数配置、拖拽扩展）
    - 与回测系统无缝集成

12. **[以AI量化为生：12.多周期图表开发实战](https://mp.weixin.qq.com/s/FQ85NgQC0h3KLLK3qD00Ew)**
    - 多时间框架分析需求分析
    - 周期切换面板设计与实现
    - K线数据聚合算法开发
    - 技术指标自动更新机制

13. **[以AI量化为生：13.交易时段小时K线合成实战](https://mp.weixin.qq.com/s/3UvbbWDhvZJactgAPtqH7w)**
    - 交易时段K线合成问题分析
    - 小时K线按实际交易时段合成
    - BarGenerator核心修改实现
    - 全球12个金融市场配置

14. **[以AI量化为生：14.多周期交易买卖点连线智能匹配实战](https://mp.weixin.qq.com/s/B35sV1A8klZ3UIO_E9VtYg)**
    - 多周期自适应显示与回调机制
    - 智能时间匹配（三层级匹配策略）

15. **[以AI量化为生：15.双图与四图视图开发实战](https://mp.weixin.qq.com/s/KXNfCfWwu6RExcHzQZHw_w)**
    - 双图并排对比分析（15分钟 vs 1小时）
    - 四图2x2网格全景视图（5分钟、15分钟、1小时、日线）
    - 多图表时间轴智能同步
    - 分段控制器风格视图切换

16. **[以AI量化为生：16.图表交互优化 - X轴延伸与专注模式](https://mp.weixin.qq.com/s/-Ig1eTi-iHtg47iyH704tg)**
    - X轴向右延伸功能（鼠标拖拽/键盘导航）
    - 重写vnpy基类方法突破边界限制
    - 双击专注模式（主图全屏/副图隔离）
    - 智能状态管理与可见性恢复

17. **[以AI量化为生：17.系统架构优化 - 指标模块化与动态加载](https://mp.weixin.qq.com/s/lfv93wu409ZqwKwQ4xTzQg)**
    - 目录重构：分离图表和指标
    - 动态指标加载机制
    - 扩展指标配置系统
    - macOS崩溃问题修复

18. **[以AI量化为生：18.实时K线图表系统开发](https://mp.weixin.qq.com/s/aGo0nPybv8PtYDILBX7Efg)**
    - ChartWizard集成EnhancedChartWidget
    - 实时价格线显示
    - 光标x轴标签修复
    - 图表组件化重构（CursorManager、ExtendableViewBox）

19. **[以AI量化为生：19.半小时K线合成与多周期系统优化](https://mp.weixin.qq.com/s/kcBdo5Skjz1niRrj5RBRHQ)**
    - 半小时K线特殊时段划分（跨休市合成）
    - 图表系统3分钟和30分钟周期支持
    - 日线聚合夜盘处理优化

20. **[以AI量化为生：20.实时图表交易系统开发](https://mp.weixin.qq.com/s/zyLFkpmma1vu6kO4xt9gaQ)**
    - 多合约Tab管理与图表切换
    - 交易面板设计与下单功能实现
    - 持仓管理与可视化（持仓线、委托线）
    - 风控面板与止损止盈机制
    - 价格预警与快捷键支持

21. **[以AI量化为生：21.交易图表AI分析功能集成](https://mp.weixin.qq.com/s/aPRnBtarPTK4XPncQvkxcg)**
    - AI分析协调器架构设计
    - 多模型AI分析集成（Claude/GPT）
    - 实时指标数据采集系统
    - AI分析面板UI实现
    - 信号解读与多周期分析

22. **[以AI量化为生：22.指标计算引擎重构 - 让策略直接复用图表指标](https://mp.weixin.qq.com/s/OslVwmpUgyAggeFhAFHjiw)**
    - UI耦合问题：指标计算与渲染逻辑混在一起
    - HeadlessCalculator抽象基类设计
    - IndicatorManager统一管理多个计算器
    - 策略中直接使用：零Qt依赖，支持回测/实盘/无UI环境

23. **[以AI量化为生：23.打造AI全驱动量化策略引擎](https://mp.weixin.qq.com/s/_QfvEdyZnJKhAWaMi98vUQ)**
    - AI策略引擎三层架构设计（策略层/适配层/提示词层）
    - 数据字典与提示词工程
    - 多维度市场分析（多周期共振+SMC聪明钱概念）
    - 七种操作类型的决策全流程
    - 思维链提取与JSON修复
    - 双层风控体系（硬限制+软限制）

24. **[以AI量化为生：24.回测结果存储与策略参数管理](https://mp.weixin.qq.com/s/nIEAYOQutAUJKy8C5Dnj6w)**
    - 回测成交与AI决策双表存储架构（MySQL ORM模型）
    - 按品种分区的JSON参数管理（StrategyParamManager）
    - 参数自动加载机制与优先级设计
    - 合约号自动归一化与旧格式迁移

25. **[以AI量化为生：25.vnpy 4.4升级实战 - 魔改版框架如何安全跟进上游](https://mp.weixin.qq.com/s/dcbkFPtnBbmsvUJc0jIHeA)**
    - 通知系统重构：send_email → send_notification（EmailEngine + WechatEngine 微信推送）
    - CTP拒单状态修复：报单被拒映射为 Status.REJECTED，策略可感知拒单
    - 价差成交数量精度修复：decimal_divide 精确除法 + 按腿最小变动数量取整
    - 魔改版框架安全升级三步法：盘家底 → 逐文件合并 → 全量验证

---

### 量化指标解码系列（技术指标研究）

《量化指标解码》是《以AI量化为生》的姊妹篇，专注于技术指标的深度研究与智能化改造。从经典指标到前沿指标，从原理剖析到实战应用，打造最全面、最前沿的量化指标库。

1. **[量化指标解码01：让指标开口说话！K线图表给技术指标装上AI大脑](https://mp.weixin.qq.com/s/nvF7VT25RXgHzSnVRfBEcQ)**
   - 智能解读的四层架构设计（基础信息、市场状态、信号识别、操作指导）
   - RSI指标智能解读完整实现
   - 区间分析、动量变化、关键位突破、钝化检测、背离信号
   - 为后续指标深度解码奠定基础

2. **[量化指标解码02：RSI深度解码 - 从超买超卖到背离钝化的全面分析](https://mp.weixin.qq.com/s/n1i676s4ZSvJCDdLX7C2sQ)**
   - RSI的计算原理和公式详解
   - 代码实现：TA-Lib计算与ATMQuant集成
   - 经典用法：超买超卖、背离（顶背离/底背离）、钝化
   - 三个实战策略：超买超卖策略、RSI+均线组合、背离策略

3. **[量化指标解码03：布林带的开口收口策略与市场波动性分析](https://mp.weixin.qq.com/s/VGOcKwW4FRSHf3gYMa7fFw)**
   - 布林带的原理：从标准差到波动率通道
   - 经典形态：收口(Squeeze)、开口(Expansion)、上下轨突破、中轨突破
   - 智能解读：价格位置、宽度变化、宽度比率、突破分析
   - 三个实战策略：均值回归策略(震荡市)、趋势突破策略(趋势市)、自适应策略(全市场)

4. **[量化指标解码04：MACD深度解码 - 零轴、背离与多周期共振策略](https://mp.weixin.qq.com/s/kzw_VUbjVWwj3RRxS1NeBQ)**
   - MACD的原理：从EMA到趋势动能
   - 经典用法：金叉死叉、零轴突破、MACD柱变化、DIFF与DEA距离
   - 高级用法：MACD背离（顶背离/底背离）、多周期共振
   - 智能解读：零轴位置、金叉死叉、MACD柱、背离检测

5. **[量化指标解码05：DMI深度解码 - 趋势强度判断的终极武器](https://mp.weixin.qq.com/s/placeholder-dmi)**
   - DMI的原理：从方向到强度
   - PDI和MDI：方向判断（对比、交叉、绝对位置）
   - ADX：趋势强度的核心（阈值判断、变化趋势、ADX与ADXR对比、拐点）
   - 经典组合：多头组合、空头组合、震荡组合

6. **[量化指标解码06：均线｜最简单的指标，最赚钱的策略](https://mp.weixin.qq.com/s/LoiclOU3V_JDTR55WzKYFQ)**
   - SMA与EMA的本质区别（稳定vs敏感）
   - SMA实战：支撑阻力、排列、散度、黄金/死亡交叉
   - EMA实战：动态支撑阻力、早期交叉信号、收敛预警、趋势强度
   - 多均线系统：三均线系统、葛兰碧法则、均线粘合与突破

7. **[量化指标解码07：会看成交量，你就成功了一半](https://mp.weixin.qq.com/s/ALjmwXM0CIu7qgTjX2XDgQ)**
   - 成交量尖峰识别：识别2倍以上异常放量
   - 买卖量智能分解：基于收盘价位置估算买卖力量
   - 量价关系分析：放量上涨、缩量上涨、放量下跌、缩量下跌
   - 增强版成交量指标（会员专享）

8. **[量化指标解码08：SuperTrend超级趋势指标深度解码](https://mp.weixin.qq.com/s/FslARKEL2OwVX2blCvtdnA)**
   - SuperTrend指标原理与计算方法
   - 趋势识别与信号生成机制
   - 参数优化与实战应用
   - 与其他指标的组合策略

9. **[量化指标解码09：ZLEMA零延迟趋势 - 比EMA快一步的秘密](https://mp.weixin.qq.com/s/iiVz_7JPwSxmLXez33m96g)**
   - ZLEMA的延迟补偿机制
   - ZLEMA vs EMA：反应速度对比与滞后性分析
   - 零延迟EMA的计算原理与代码实现
   - 实战应用：趋势捕捉、突破确认、多周期共振

10. **[量化指标解码10：斐波那契入场带 - 不追涨不踏空的4层入场系统](https://mp.weixin.qq.com/s/YW9PHZ-MRKw6TeG5wp1MIA)**
    - 双重EMA基础线：平滑趋势判断
    - 斐波那契多层带状：0.618、1.0、1.618、2.618倍波动率
    - 三类交易信号：入场信号、反弹信号、止盈信号
    - 趋势跟踪+均值回归混合系统：多周期配合与成交量过滤

11. **[量化指标解码11：挤压动量 - 捕捉低波动后的爆发行情](https://mp.weixin.qq.com/s/LjVdLktbQttrfS-R0eNiRA)**
    - 布林带与肯特纳通道对比：识别市场挤压与释放状态
    - 三种状态标记：金色菱形（挤压）、灰色十字（释放）、蓝色十字（中性）
    - 线性回归动量计算：精准捕捉突破方向和强度变化
    - 智能背离检测：价格与动量背离的自动识别与标记

12. **[量化指标解码12：聪明钱突破通道 - 用波动率解码主力资金突破时机](https://mp.weixin.qq.com/s/Uv3HCR-gBN6FbgRsdOiFpQ)**
    - 波动率归一化：不同品种的统一比较基准
    - 通道自动检测：upper与lower交叉识别整理阶段
    - 突破信号生成：强势收盘检测过滤假突破
    - 量能仪表辅助：实时买卖压力可视化分析

13. **[量化指标解码13：WaveTrend波浪趋势 - 震荡行情的超买超卖捕手](https://mp.weixin.qq.com/s/J2kZLrdpMlg4L6Og1rhS5g)**
    - 双重EMA平滑：HLC3 → ESA → CI → WT1/WT2交叉信号
    - 超买超卖区域：四层阈值判断（极度超买/超买/超卖/极度超卖）
    - 强势信号识别：超买超卖区域的交叉信号成功率更高
    - 智能背离检测：价格与指标背离的自动识别与菱形标记

14. **[量化指标解码14：Supertrended RSI - RSI与趋势跟踪的完美融合](https://mp.weixin.qq.com/s/t1CmDPUXH5r7LgBqvZOr7A)**
    - RSI+Supertrend融合：在RSI值上计算Supertrend，提供动态支撑阻力
    - 四种信号类型：超买超卖反转 + 趋势突破确认，过滤逆势假信号
    - 多重平滑支持：可选HMA平滑RSI，6种MA类型辅助判断趋势
    - 自适应波动率：基于RSI自身波动计算ATR，动态调整信号敏感度

15. **[量化指标解码15：Adaptive MACD Deluxe - 会自己调参的智能MACD](https://mp.weixin.qq.com/s/bvory4baaQTdKPnHpkMatA)**
    - R²相关性的自适应机制：根据市场状态动态调整MACD灵敏度
    - Heiken Ashi平滑蜡烛图：把MACD值转成蜡烛图，看趋势更直观
    - 6种信号平滑选择：EMA、SMA、WMA、VWMA、SMMA、Heiken Ashi
    - 区域穿越交易信号：极度超买超卖区域的强烈反转信号识别

16. **[量化指标解码16：SMC聪明钱概念之订单块](https://mp.weixin.qq.com/s/E7bKW3bjs0klDmb5yEUuhA)**
    - Smart Money Concept（SMC）核心思想：跟随机构资金而非散户资金
    - 6种Order Block类型：Demand/Supply的Main ChoCh、Sub ChoCh、BoS
    - 优先级体系：Main ChoCh > Sub ChoCh > BoS
    - 实战应用：回踩/反弹入场策略、风险收益比计算、失效判断

17. **[量化指标解码17：SMC聪明钱概念之公允价值缺口](https://mp.weixin.qq.com/s/gruDeLv5o6A1IWJB4SYF5g)**
    - Fair Value Gap（FVG）本质：价格快速波动留下的未充分成交区域
    - FVG形成机制：机构大单推动价格时中间价位来不及成交
    - 三种主要用法：入场区域参考、趋势强度确认、与Order Block协同
    - 过滤器设计：缺口大小过滤、时间过滤、与Order Block距离过滤

18. **[量化指标解码18：SMC市场结构与流动性](https://mp.weixin.qq.com/s/XEX1E1nUnR4WN4WVGrx9hQ)**
    - Break of Structure（BoS）：价格突破同方向结构点，趋势延续信号
    - Change of Character（ChoCh）：价格突破反方向结构点，趋势反转信号
    - Major vs Minor结构：Major定方向，Minor找时机
    - 流动性扫荡：双顶双底、三顶三底等经典形态背后的机构操作逻辑

19. **[量化指标解码19：K线形态识别 - 价格行为不会说谎](https://mp.weixin.qq.com/s/F2Pa-zLc7Axub9Zj__b-6A)**
    - Price Action核心思想：价格包含一切信息，形态反映市场意图
    - 单K形态识别：锤子线、射击之星、吞没形态、十字星等
    - 多K组合形态：晨星暮星、三白兵三黑鸦、孕线等
    - 反转信号与持续信号分类，结合趋势和支撑阻力综合判断

20. **[量化指标解码20：谐波形态识别 - 用斐波那契找到精准反转点](https://mp.weixin.qq.com/s/4VzYURqpDeSVRh_1A8EGAw)**
    - 谐波形态核心思想：价格运动遵循斐波那契比率关系
    - 四类形态结构：XABCD五点、OXABCD六点、ABCD四点、三推形态
    - 11种经典形态：Gartley、Butterfly、Bat、Crab、Shark、Cypher等
    - ZigZag转向点识别 + 斐波那契比率匹配双重验证

---

### 量化策略开发系列（策略实战开发）

《量化策略开发》系列涵盖传统技术指标策略和AI驱动策略的实战开发。从经典均值回归、趋势跟踪等量化策略，到AI全权决策的前沿探索，系统分享策略设计、回测验证与参数优化的完整流程。

1. **[量化策略开发01：我让AI全权做交易决策：从提示词设计到决策执行](https://mp.weixin.qq.com/s/yY95qcyoTXvzOFYjQcDpHw)**
    - 传统策略的困境：写不完的if/else
    - 从"写规则"到"写提示词"的思维转变
    - 系统提示词三层架构：角色定义、交易模式、输出格式
    - 用户提示词：市场数据、技术指标、持仓信息
    - AI响应解析：思维链提取、JSON修复、验证兜底

2. **[量化策略开发02：海龟三重EMA趋势策略 - 从设计思路到回测验证](https://mp.weixin.qq.com/s/xB0_bTsrU7OzmwqdKAFfQw)**
    - 三重EMA排列逻辑：单条→双条→三条的递进设计
    - 多入场模式：严格、宽松和ADX过滤三种模式对比
    - 止损止盈设计：ATR倍数动态止损、移动止损、EMA排列破坏出场
    - 7个品种回测验证与实战经验分享

3. **[量化策略开发03：均值回归信号捕捉 - EMA+RSI+ATR三维共振交易系统](https://mp.weixin.qq.com/s/Nl9Oqr7nsSWlnNGM9qJBGA)**
    - 均值回归本质分析与三维共振信号系统设计
    - EMA趋势方向 + RSI超买超卖 + ATR波动率过滤的三维确认
    - 冷却期机制防止过度交易
    - 多周期支持：15分钟、30分钟、1小时实战配置

---

## 开发规范

### 代码风格
- 使用Python 3.10+
- 遵循PEP 8代码规范
- 使用类型注解
- 添加详细的中文注释

### 提交规范
- feat: 新功能
- fix: 修复bug
- docs: 文档更新
- style: 代码格式调整
- refactor: 代码重构
- test: 测试相关
- chore: 构建过程或辅助工具的变动

## 贡献

欢迎提交 Issue 和 Pull Request。

如果这个项目对你有帮助，欢迎 Star 支持。

## 许可证

MIT License

## 相关链接

- **GitHub**: https://github.com/seasonstar/atmquant
- **Gitee**: https://gitee.com/seasonstar/atmquant
- **公众号**: 堂主的ATMQuant
- **知识星球**: 量策堂·AI算法指标策略

---

**本项目是《以AI量化为生》和《量化指标解码》系列教程的配套代码。** 当前仓库已同步公开原付费版中的核心系统能力（AI 策略引擎、图表交易与风控管理器、指标计算管线、集中化 AI 配置等），便于对照文章动手实验；星球侧侧重高阶指标、策略沉淀与持续更新的深度内容。

若想系统学习量化交易开发，可关注公众号获取教程更新。
