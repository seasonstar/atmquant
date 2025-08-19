# -*- coding: utf-8 -*-
"""
pytest配置文件
提供测试的通用配置和fixture
"""

import sys
from pathlib import Path
import pytest

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

@pytest.fixture(scope="session")
def project_root_path():
    """返回项目根目录路径"""
    return project_root

@pytest.fixture(scope="session") 
def vnpy_available():
    """检查vnpy是否可用"""
    try:
        import vnpy
        return True
    except ImportError:
        return False

@pytest.fixture(scope="session")
def ctp_available():
    """检查CTP插件是否可用"""
    try:
        import vnpy_ctp
        return True
    except ImportError:
        return False