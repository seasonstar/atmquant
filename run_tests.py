#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试运行脚本
从项目根目录运行所有测试
"""

import sys
import subprocess
from pathlib import Path

def run_test(test_file):
    """运行单个测试文件"""
    print(f"\n{'='*60}")
    print(f"运行测试: {test_file}")
    print('='*60)
    
    try:
        result = subprocess.run([sys.executable, test_file], 
                              capture_output=False, 
                              text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"运行测试失败: {e}")
        return False

def main():
    """主函数"""
    print("ATMQuant 测试套件")
    print("="*60)
    
    # 测试文件列表
    test_files = [
        "tests/test_vnpy.py",
        "tests/test_plugins.py", 
        "tests/test_ctp_connection.py"
    ]
    
    # 检查测试文件是否存在
    existing_tests = []
    for test_file in test_files:
        if Path(test_file).exists():
            existing_tests.append(test_file)
        else:
            print(f"⚠️  测试文件不存在: {test_file}")
    
    if not existing_tests:
        print("❌ 没有找到可运行的测试文件")
        return False
    
    # 运行测试
    passed = 0
    total = len(existing_tests)
    
    for test_file in existing_tests:
        if run_test(test_file):
            passed += 1
            print(f"✅ {test_file} - 通过")
        else:
            print(f"❌ {test_file} - 失败")
    
    # 输出总结
    print(f"\n{'='*60}")
    print(f"测试总结: {passed}/{total} 个测试通过")
    print('='*60)
    
    if passed == total:
        print("🎉 所有测试都通过了！")
        return True
    else:
        print("⚠️  部分测试失败，请检查配置")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)