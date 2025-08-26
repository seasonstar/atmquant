#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货数据定时下载脚本
支持定时下载期货数据，可配置下载品种和时间范围
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入配置
from config.settings import apply_settings
from config.futures_config import get_all_symbols, get_futures_info
from core.data.downloader import FuturesDataDownloader


class FuturesDataScheduler:
    """期货数据定时下载调度器"""
    
    def __init__(self, config_file: str = "config/download_config.json"):
        """
        初始化调度器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config = self.load_config()
        self.downloader = FuturesDataDownloader()
    
    def load_config(self) -> Dict[str, Any]:
        """加载下载配置"""
        config_path = Path(self.config_file)
        
        # 默认配置
        default_config = {
            "enabled_symbols": ["rb", "hc", "i", "j", "jm", "cu", "al", "zn"],  # 默认下载的品种
            "download_mode": "priority",  # priority: 优先合约, all: 全部合约
            "data_range_days": 30,  # 默认下载最近30天数据
            "update_mode": "incremental",  # incremental: 增量更新, full: 全量更新
            "batch_size": 5,  # 批量下载的品种数量
            "retry_times": 3,  # 失败重试次数
            "retry_delay": 60,  # 重试间隔（秒）
            "log_level": "INFO",
            "notification": {
                "enabled": False,
                "email": True,
                "feishu": False
            }
        }
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
                    print(f"✓ 加载配置文件: {config_path}")
            except Exception as e:
                print(f"⚠️  配置文件加载失败: {e}，使用默认配置")
        else:
            # 创建默认配置文件
            self.save_config(default_config)
            print(f"✓ 创建默认配置文件: {config_path}")
        
        return default_config
    
    def save_config(self, config: Dict[str, Any] = None):
        """保存配置到文件"""
        if config is None:
            config = self.config
        
        config_path = Path(self.config_file)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print(f"✓ 配置已保存: {config_path}")
        except Exception as e:
            print(f"✗ 配置保存失败: {e}")
    
    def get_download_date_range(self) -> tuple:
        """获取下载日期范围（仅专业版可用，免费版通过size控制）"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)  # 默认1天，实际由size控制
        return start_date, end_date
    
    def download_with_retry(self, symbol: str, max_retries: int = None) -> bool:
        """
        带重试的下载函数
        
        Args:
            symbol: 品种代码
            max_retries: 最大重试次数
        
        Returns:
            是否下载成功
        """
        if max_retries is None:
            max_retries = self.config["retry_times"]
        
        start_date, end_date = self.get_download_date_range()
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    print(f"第 {attempt} 次重试下载 {symbol}...")
                    import time
                    time.sleep(self.config["retry_delay"])
                
                results = self.downloader.download_symbol_data(
                    symbol,
                    update_mode=self.config["update_mode"],
                    start_date=start_date,
                    end_date=end_date
                )
                
                # 检查是否有成功的下载
                success_count = sum(1 for success in results.values() if success)
                if success_count > 0:
                    print(f"✓ {symbol} 下载成功 ({success_count}/{len(results)} 合约)")
                    return True
                else:
                    print(f"⚠️  {symbol} 所有合约下载失败")
                    
            except Exception as e:
                print(f"✗ {symbol} 下载异常: {e}")
                if attempt == max_retries:
                    print(f"✗ {symbol} 达到最大重试次数，放弃下载")
        
        return False
    
    def run_download(self, symbols: List[str] = None) -> Dict[str, bool]:
        """
        执行数据下载
        
        Args:
            symbols: 要下载的品种列表，None表示使用配置文件中的品种
        
        Returns:
            下载结果字典
        """
        if symbols is None:
            symbols = self.config["enabled_symbols"]
        
        print(f"开始定时下载任务")
        print(f"下载品种: {symbols}")
        print(f"更新模式: {self.config['update_mode']}")
        
        start_date, end_date = self.get_download_date_range()
        if self.config["update_mode"] == "incremental":
            print(f"增量更新: 下载最近2000条数据（约4-8天）")
        else:
            print(f"全量更新: 下载最近10000条数据（约1-2个月）")
        print("=" * 60)
        
        # 初始化下载器
        if not self.downloader.init_database():
            print("✗ 数据库初始化失败")
            return {}
        
        if not self.downloader.init_tqsdk():
            print("✗ 天勤SDK初始化失败")
            return {}
        
        results = {}
        success_count = 0
        
        try:
            # 批量下载
            batch_size = self.config["batch_size"]
            for i in range(0, len(symbols), batch_size):
                batch_symbols = symbols[i:i + batch_size]
                print(f"\n批次 {i//batch_size + 1}: {batch_symbols}")
                
                for symbol in batch_symbols:
                    print(f"\n处理品种: {symbol}")
                    
                    # 检查品种是否存在
                    info = get_futures_info(symbol)
                    if not info:
                        print(f"⚠️  未知品种: {symbol}")
                        results[symbol] = False
                        continue
                    
                    # 下载数据
                    success = self.download_with_retry(symbol)
                    results[symbol] = success
                    
                    if success:
                        success_count += 1
        
        finally:
            # 关闭连接
            self.downloader.close()
        
        # 输出总结
        print("\n" + "=" * 60)
        print(f"下载任务完成")
        print(f"成功: {success_count}/{len(symbols)} 品种")
        
        for symbol, success in results.items():
            status = "✓" if success else "✗"
            print(f"{status} {symbol}")
        
        return results
    
    def show_config(self):
        """显示当前配置"""
        print("当前下载配置:")
        print("=" * 40)
        print(f"启用品种: {self.config['enabled_symbols']}")
        print(f"更新模式: {self.config['update_mode']}")
        if self.config['update_mode'] == 'incremental':
            print(f"数据量: 2000条（约4-8天）")
        else:
            print(f"数据量: 10000条（约1-2个月）")
        print(f"批量大小: {self.config['batch_size']}")
        print(f"重试次数: {self.config['retry_times']}")
        print("=" * 40)
    
    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
                print(f"✓ 更新配置: {key} = {value}")
            else:
                print(f"⚠️  未知配置项: {key}")
        
        self.save_config()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="期货数据定时下载脚本")
    parser.add_argument("--symbols", nargs="+", help="指定下载的品种代码")
    parser.add_argument("--config", default="config/download_config.json", help="配置文件路径")
    parser.add_argument("--mode", choices=["priority", "all"], help="下载模式")
    parser.add_argument("--days", type=int, help="数据范围天数")
    parser.add_argument("--update-mode", choices=["incremental", "full"], help="更新模式")
    parser.add_argument("--show-config", action="store_true", help="显示配置")
    parser.add_argument("--list-symbols", action="store_true", help="列出所有支持的品种")
    
    args = parser.parse_args()
    
    # 应用vnpy配置
    apply_settings()
    
    if args.list_symbols:
        print("支持的期货品种:")
        print("=" * 30)
        all_symbols = get_all_symbols()
        for symbol in all_symbols:
            info = get_futures_info(symbol)
            print(f"{symbol:6} - {info.get('name', '未知')} ({info.get('exchange', '').value})")
        return
    
    # 创建调度器
    scheduler = FuturesDataScheduler(args.config)
    
    # 更新配置
    if args.mode:
        scheduler.update_config(download_mode=args.mode)
    if args.days:
        scheduler.update_config(data_range_days=args.days)
    if args.update_mode:
        scheduler.update_config(update_mode=args.update_mode)
    
    if args.show_config:
        scheduler.show_config()
        return
    
    # 执行下载
    symbols = args.symbols if args.symbols else None
    results = scheduler.run_download(symbols)
    
    # 返回结果
    success_count = sum(1 for success in results.values() if success)
    exit_code = 0 if success_count > 0 else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()