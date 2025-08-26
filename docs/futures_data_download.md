# 期货数据下载使用指南

## 概述

本系统提供了完整的期货数据下载和管理功能，支持多品种、多合约类型的数据下载，具有智能合约管理、定时下载、数据验证等特性。

## 快速开始

### 1. 安装依赖

```bash
# 安装天勤SDK
pip install tqsdk

# 安装数据库驱动（SQLite）
pip install vnpy_sqlite
```

### 2. 配置数据源

在`.env`文件中配置天勤账户：

```bash
# 天勤数据源配置
DATAFEED_NAME=tqsdk
DATAFEED_USERNAME=your_phone_number
DATAFEED_PASSWORD=your_password
```

### 3. 测试系统

```bash
# 测试配置和基本功能
python scripts/test_download.py

# 查看支持的品种
python scripts/download_futures_data.py --list-symbols

# 查看当前配置
python scripts/download_futures_data.py --show-config
```

## 使用方法

### 命令行下载

```bash
# 下载所有配置的品种（优先合约）
python scripts/download_futures_data.py

# 下载指定品种
python scripts/download_futures_data.py --symbols rb hc cu

# 设置下载模式和天数
python scripts/download_futures_data.py --mode priority --days 7

# 全量下载所有合约
python scripts/download_futures_data.py --mode all --days 30
```

### 数据验证

```bash
# 验证数据质量
python scripts/verify_data.py

# 验证指定品种
python scripts/verify_data.py --symbols rb hc

# 生成验证报告
python scripts/verify_data.py --report data_quality_report.txt
```

### Python API使用

```python
from core.data.downloader import FuturesDataDownloader
from datetime import datetime, timedelta

# 创建下载器
downloader = FuturesDataDownloader()

# 初始化
downloader.init_database()
downloader.init_tqsdk()

# 下载单个合约
success = downloader.download_contract_data(
    "rb9999.SHFE",
    start_date=datetime.now() - timedelta(days=7),
    end_date=datetime.now()
)

# 下载品种所有优先合约
results = downloader.download_symbol_data("rb", priority_only=True)

# 关闭连接
downloader.close()
```

## 配置说明

### 下载配置文件

配置文件位置：`config/download_config.json`

```json
{
  "enabled_symbols": ["rb", "hc", "cu", "al", "zn"],
  "download_mode": "priority",
  "data_range_days": 30,
  "update_mode": "incremental",
  "batch_size": 5,
  "retry_times": 3,
  "retry_delay": 60
}
```

**配置项说明**：

- `enabled_symbols`: 启用下载的品种列表
- `download_mode`: 下载模式
  - `priority`: 只下载优先合约（推荐）
  - `all`: 下载所有相关合约
- `data_range_days`: 数据范围天数
- `update_mode`: 更新模式
  - `incremental`: 增量更新（推荐）
  - `full`: 全量更新
- `batch_size`: 批量下载的品种数量
- `retry_times`: 失败重试次数
- `retry_delay`: 重试间隔（秒）

### 期货品种配置

品种配置文件：`config/futures_config.py`

包含各期货品种的基本参数：
- 合约乘数
- 最小变动价位
- 保证金比例
- 交易月份
- 活跃合约数量

## 合约类型说明

### 1. 具体月份合约
- 格式：`rb2510.SHFE`（螺纹钢2025年10月合约）
- 特点：真实可交易合约，有到期日
- 用途：实盘交易、短期策略

### 2. 主连合约
- 格式：`rb9999.SHFE`
- 特点：主力合约的连续拼接，数据连续
- 用途：长期回测、趋势分析

### 3. 加权合约
- 格式：`rb8888.SHFE`
- 特点：按成交量加权的价格
- 用途：回测验证、风险评估

## 定时任务设置

### Linux Cron

```bash
# 编辑crontab
crontab -e

# 每天早上9点下载数据
0 9 * * * cd /path/to/atmquant && python scripts/download_futures_data.py

# 每小时增量更新
0 * * * * cd /path/to/atmquant && python scripts/download_futures_data.py --update-mode incremental --days 1
```

### Python定时任务

```python
import schedule
import time

def run_download():
    os.system("python scripts/download_futures_data.py")

# 每天9点执行
schedule.every().day.at("09:00").do(run_download)

while True:
    schedule.run_pending()
    time.sleep(60)
```

## 数据质量监控

### 自动验证

系统会自动进行以下检查：
- 数据完整性检查
- 价格合理性验证
- 数据间隔检测
- 异常波动识别

### 手动验证

```bash
# 生成数据质量报告
python scripts/verify_data.py --report quality_report.txt

# 检查特定品种
python scripts/verify_data.py --symbols rb hc --days 7
```

## 常见问题

### 1. 天勤SDK登录失败

**问题**：用户名或密码错误

**解决**：
- 确认用户名为手机号
- 检查密码是否正确
- 确认账户状态正常

### 2. 数据下载失败

**问题**：网络超时或合约不存在

**解决**：
- 检查网络连接
- 确认合约代码格式正确
- 检查合约是否已上市

### 3. 数据库连接失败

**问题**：数据库连接错误

**解决**：
- 检查数据库服务状态
- 验证连接配置
- 确认数据库权限

## 最佳实践

### 1. 下载策略

- **新手**：从1-2个品种开始，只下载主连合约
- **进阶**：增加品种数量，下载优先合约
- **专业**：全品种覆盖，包含所有活跃合约

### 2. 数据管理

- 定期验证数据质量
- 建立数据备份机制
- 监控存储空间使用
- 清理过期数据

### 3. 性能优化

- 合理设置批量大小
- 避免高峰期下载
- 使用增量更新模式
- 监控系统资源使用

## 技术支持

如有问题，请：
1. 查看日志文件
2. 运行测试脚本诊断
3. 检查配置文件
4. 联系技术支持

---

更多详细信息请参考系列文章：《以AI量化为生：5.期货数据定时下载与合约管理》