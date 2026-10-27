"""日志系统退出生命周期的子进程回归测试。"""

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_pytest_exit_does_not_write_to_closed_capture_stream() -> None:
    """pytest 关闭捕获流后，atexit 日志清理不能再向旧 handler 写消息。"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(PROJECT_ROOT / "tests" / "test_script_contracts.py"),
            "-q",
            "--capture=fd",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Logging error in Loguru Handler" not in output, output
    assert "I/O operation on closed file" not in output, output
