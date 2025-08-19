# 测试说明

## 测试文件结构

```
tests/
├── conftest.py              # pytest配置文件
├── test_vnpy.py            # vnpy环境测试
├── test_plugins.py         # 插件安装测试
├── test_ctp_connection.py  # CTP连接测试
├── unit/                   # 单元测试
├── integration/            # 集成测试
└── backtest/              # 回测测试
```

## 运行测试

### 方法1：直接运行单个测试
```bash
# 从项目根目录运行
python tests/test_vnpy.py
python tests/test_plugins.py
python tests/test_ctp_connection.py
```

### 方法2：使用测试运行脚本
```bash
# 运行所有测试
python run_tests.py
```

### 方法3：使用pytest（推荐）
```bash
# 安装pytest
pip install pytest pytest-cov

# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_vnpy.py -v

# 运行带覆盖率的测试
pytest --cov=core --cov=utils tests/
```

## 测试说明

- **test_vnpy.py**: 验证vnpy核心环境是否正确安装
- **test_plugins.py**: 验证vnpy插件是否正确安装
- **test_ctp_connection.py**: 测试CTP接口连接（需要配置）

## 注意事项

1. 所有测试文件都已经配置了正确的Python路径
2. 从项目根目录运行测试，不要在tests目录内运行
3. CTP连接测试需要先配置SimNow账户信息
4. 如果遇到导入错误，检查虚拟环境是否激活