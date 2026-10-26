"""当前 AI 决策缓存的行为测试，迁移自已退役的 ai_backtester 测试。"""

import json
from datetime import datetime

from core.ai_strategy_engine.cache import AICache, compute_cache_key


def make_context() -> dict:
    return {
        "symbol": "rb2505.SHFE",
        "market": {
            "current_price": 3000.0,
            "open": 2980.0,
            "high": 3010.0,
            "low": 2970.0,
            "volume": 12345,
        },
        "indicators": {"sma": 2950.0, "rsi": 55.0},
        "account": {"balance": 100000, "position": 0},
        "positions": [],
    }


def test_cache_key_depends_on_market_inputs_not_account_state() -> None:
    """相同市场输入应复用决策，账户和持仓变化不应制造新缓存键。"""
    context = make_context()
    changed_state = make_context()
    changed_state["account"] = {"balance": 90000, "position": 2}
    changed_state["positions"] = [{"symbol": "rb2505.SHFE", "volume": 2}]
    dt = datetime(2024, 1, 17, 9, 30)

    assert compute_cache_key(context, "default", dt) == compute_cache_key(
        changed_state, "default", dt
    )

    changed_market = make_context()
    changed_market["market"]["current_price"] = 3001.0
    assert compute_cache_key(context, "default", dt) != compute_cache_key(
        changed_market, "default", dt
    )


def test_cache_persists_and_reloads_decision(tmp_path) -> None:
    """缓存写入后，新实例仍应能从磁盘恢复同一决策。"""
    cache_path = tmp_path / "ai_cache.json"
    context = make_context()
    dt = datetime(2024, 1, 17, 9, 30)
    key = compute_cache_key(context, "default", dt)
    decision = {"action": "HOLD", "confidence": 0.8, "reason": "测试"}

    cache = AICache(str(cache_path))
    cache.put(key, "default", dt, decision)
    reloaded = AICache(str(cache_path))

    assert reloaded.size() == 1
    assert reloaded.get(key) == decision


def test_cache_loads_legacy_millisecond_timestamp(tmp_path) -> None:
    """旧缓存的毫秒时间戳仍能加载，避免迁移后历史缓存全部失效。"""
    cache_path = tmp_path / "legacy_cache.json"
    decision = {"action": "LONG", "confidence": 0.7}
    cache_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "key": "legacy-key",
                        "variant": "default",
                        "datetime": 1705449600000,
                        "decision": decision,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cache = AICache(str(cache_path))

    assert cache.get("legacy-key") == decision
