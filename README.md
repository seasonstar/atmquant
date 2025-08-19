# ATMQuant - AI量化交易系统

基于vnpy 4.1框架的AI量化交易系统，专注于AI量化投资、指标信号可视化与策略研发。

## 项目特点

- 📊 **定制化图表**: 基于vnpy的专业量化图表系统
- 🏗️ **模块化架构**: 清晰的业务模块划分，易于扩展和维护
- 📈 **策略开发**: 丰富的交易策略，可定制化策略开发与参数优化
- � **教学导向***: 完整的文档和示例，适合学习和教学
- 🎯 **实战导向**: 面向实盘交易的完整解决方案

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python3 -m venv vnpy_env
source vnpy_env/bin/activate  # Linux/macOS
# 或
vnpy_env\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置设置

```bash
# 复制配置文件
cp .env.example .env

# 编辑配置文件，填入你的CTP账户信息
vim .env
```

### 3. 运行测试

```bash
# 测试环境配置
python test_vnpy.py

# 运行主程序
python main.py
```

## 项目结构

```
atmquant/                          # 项目根目录
├── 📁 core/                        # 核心业务模块
│   ├── 📁 charts/                  # 图表相关(定制化图表)
│   ├── 📁 data/                    # 数据处理核心
│   └── 📁 strategies/              # 策略相关
├── 📁 config/                      # 统一配置管理
├── 📁 scripts/                     # 运行脚本
├── 📁 backtests/                   # 回测相关
├── 📁 utils/                       # 工具模块
├── 📁 tests/                       # 测试文件
│   ├── unit/                       # 单元测试
│   ├── integration/                # 集成测试
│   └── backtest/                   # 回测测试
├── 📁 docs/                        # 文档目录
├── 📁 articles/                    # 公众号文章
├── 📁 logs/                        # 日志文件
├── 📁 vnpy/                        # VeighNa框架
├── 📄 main.py                      # 主入口文件
├── 📄 requirements.txt             # 依赖包
└── 📄 README.md                    # 项目说明
```

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

## 许可证

MIT License

## 联系方式

- 公众号：堂主的ATMQuant
- GitHub：https://github.com/seasonstar/atmquant
