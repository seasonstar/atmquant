"""现役脚本与当前引擎接口的兼容性检查。"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from vnpy_ctastrategy.backtesting import BacktestingEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_script(filename: str):
    """加载未被 __main__ 入口保护的脚本；本地付费脚本缺失时跳过。"""
    path = PROJECT_ROOT / "scripts" / filename
    if not path.exists():
        pytest.skip(f"本地可选脚本不存在：{filename}")

    module_name = f"_script_contract_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "filename",
    [
        "run_ai_backtest.py",
        "backtest_3ma_strategy.py",
        "optimize_3ma_strategy.py",
        "show_new_symbols.py",
    ],
)
def test_script_importable_with_current_modules(filename: str) -> None:
    """脚本引用的项目模块和引擎入口必须真实存在。"""
    load_script(filename)


def test_triple_ma_script_matches_current_defaults() -> None:
    """三均线 smoke 脚本不能再因旧默认参数而误报失败。"""
    module = load_script("test_3ma_strategy.py")

    assert module.test_strategy_parameters() is True


def test_show_new_symbols_reads_active_months(monkeypatch, capsys) -> None:
    """新增品种展示必须能读取当前 FUTURES_INFO 的 active_months 字段。"""
    module = load_script("show_new_symbols.py")
    info = {
        "name": "测试品种",
        "exchange": SimpleNamespace(value="SHFE"),
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.1,
        "rate": 0.0001,
        "slippage": 0.2,
        "active_months": [1, 5, 10],
    }
    monkeypatch.setattr(module, "get_futures_info", lambda symbol: info)
    monkeypatch.setattr(module, "get_priority_contracts", lambda symbol: ["T9999.SHFE"])

    module.show_new_symbols()

    assert "交易月份: [1, 5, 10]" in capsys.readouterr().out


def test_optimization_script_uses_current_optimization_api(monkeypatch) -> None:
    """优化脚本必须构造 OptimizationSetting，而不是传字典和 target_name。"""
    module = load_script("optimize_3ma_strategy.py")
    monkeypatch.setattr(
        "vnpy_ctastrategy.backtesting.run_bf_optimization",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(BacktestingEngine, "show_chart", lambda self: None)

    module.run_optimization()


def test_ai_backtest_runs_with_current_strategy_offline(monkeypatch) -> None:
    """AI 回测应使用现役策略，并在空数据替代数据库时完成完整调用链。"""
    module = load_script("run_ai_backtest.py")

    class OfflineEngine(BacktestingEngine):
        events = []

        def add_strategy(self, strategy_class, setting: dict) -> None:
            unsupported = set(setting).difference(strategy_class.parameters)
            if unsupported:
                raise AssertionError(f"策略未声明这些参数：{sorted(unsupported)}")
            super().add_strategy(strategy_class, setting)

        def load_data(self) -> None:
            self.events.append("load_data")
            self.history_data = []

        def load_bar(self, *args, **kwargs) -> list:
            return []

        def run_backtesting(self) -> None:
            self.events.append("run_backtesting")
            super().run_backtesting()

    OfflineEngine.events = []
    monkeypatch.setattr(module, "BacktestingEngine", OfflineEngine)

    result_df, statistics = module.run_backtest(api_key="")

    assert result_df.empty
    assert isinstance(statistics, dict)
    assert OfflineEngine.events == ["load_data", "run_backtesting"]
