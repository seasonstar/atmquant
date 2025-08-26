#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货数据下载器
支持天勤数据源的期货数据下载，包括历史数据和实时数据
"""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vnpy.trader.constant import Interval, Exchange
from vnpy.trader.object import BarData
from vnpy.trader.database import get_database

# 导入配置
from config.futures_config import get_active_contracts, get_priority_contracts, get_futures_info


class FuturesDataDownloader:
    """期货数据下载器"""
    
    def __init__(self):
        """初始化下载器"""
        self.database = None
        self.tq_api = None
        
        # 交易所映射
        self.exchange_mapping = {
            'CFFEX': Exchange.CFFEX,  # 中国金融期货交易所
            'INE': Exchange.INE,      # 上海国际能源交易中心
            'SHFE': Exchange.SHFE,    # 上期所
            'CZCE': Exchange.CZCE,    # 郑商所
            'DCE': Exchange.DCE,      # 大商所
            'GFEX': Exchange.GFEX,    # 广州商品交易所
        }
    
    def init_database(self):
        """初始化数据库连接"""
        try:
            self.database = get_database()
            print("✓ 数据库连接成功")
            return True
        except Exception as e:
            print(f"✗ 数据库连接失败: {e}")
            return False
    
    def init_tqsdk(self, username: str = None, password: str = None):
        """初始化天勤SDK"""
        try:
            from tqsdk import TqApi, TqAuth
            
            # 从环境变量获取账户信息
            if not username:
                username = os.getenv("DATAFEED_USERNAME")
            if not password:
                password = os.getenv("DATAFEED_PASSWORD")
            
            if not username or not password:
                print("⚠️  未配置天勤账户信息，使用游客模式")
                self.tq_api = TqApi()
            else:
                auth = TqAuth(username, password)
                self.tq_api = TqApi(auth=auth)
            
            print("✓ 天勤SDK初始化成功")
            return True
            
        except ImportError:
            print("✗ 天勤SDK未安装，请运行: pip install tqsdk")
            return False
        except Exception as e:
            print(f"✗ 天勤SDK初始化失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self.tq_api:
            self.tq_api.close()
            self.tq_api = None
    
    def convert_to_tq_symbol(self, vt_symbol: str) -> str:
        """
        将vnpy格式的合约代码转换为天勤格式
        
        Args:
            vt_symbol: vnpy格式，如 rb2510.SHFE
        
        Returns:
            天勤格式，如 SHFE.rb2510
        """
        if '.' not in vt_symbol:
            return vt_symbol
        
        symbol_part, exchange_part = vt_symbol.split('.')
        
        # 处理主连和加权合约
        if symbol_part.endswith('9999'):
            # 主连合约：rb9999 -> KQ.m@SHFE.rb
            base_symbol = symbol_part[:-4]
            return f"KQ.m@{exchange_part}.{base_symbol}"
        elif symbol_part.endswith('8888'):
            # 加权合约：rb8888 -> KQ.i@SHFE.rb
            base_symbol = symbol_part[:-4]
            return f"KQ.i@{exchange_part}.{base_symbol}"
        else:
            # 普通合约：rb2510 -> SHFE.rb2510
            return f"{exchange_part}.{symbol_part}"
    
    def parse_vt_symbol(self, vt_symbol: str) -> tuple:
        """
        解析vnpy格式的合约代码
        
        Returns:
            (exchange, symbol, month)
        """
        if '.' not in vt_symbol:
            return None, None, None
        
        symbol_month, exchange = vt_symbol.split('.')
        
        # 找到数字开始的位置
        last_idx = -1
        while last_idx >= -len(symbol_month) and symbol_month[last_idx].isdigit():
            last_idx -= 1
        
        if last_idx == -1:
            # 没有数字，可能是主连或加权合约
            return exchange, symbol_month, None
        
        symbol = symbol_month[:last_idx + 1]
        month = symbol_month[last_idx + 1:]
        
        return exchange, symbol, month
    
    def download_contract_data(
        self, 
        vt_symbol: str, 
        start_date: datetime = None,
        end_date: datetime = None,
        interval: Interval = Interval.MINUTE,
        size: int = 10000
    ) -> bool:
        """
        下载单个合约的数据
        
        Args:
            vt_symbol: 合约代码，如 rb2510.SHFE
            start_date: 开始日期
            end_date: 结束日期
            interval: 数据周期
            size: 数据长度（当未指定日期时使用）
        
        Returns:
            是否下载成功
        """
        if not self.tq_api:
            print("✗ 天勤SDK未初始化")
            return False
        
        if not self.database:
            print("✗ 数据库未初始化")
            return False
        
        try:
            # 转换为天勤格式
            tq_symbol = self.convert_to_tq_symbol(vt_symbol)
            print(f"下载合约: {vt_symbol} -> {tq_symbol}")
            
            # 解析合约信息
            exchange, symbol, month = self.parse_vt_symbol(vt_symbol)
            vnpy_exchange = self.exchange_mapping.get(exchange)
            
            if not vnpy_exchange:
                print(f"✗ 不支持的交易所: {exchange}")
                return False
            
            # 获取数据（兼容免费版和专业版）
            try:
                if start_date and end_date:
                    # 尝试使用日期范围（专业版功能）
                    klines = self.tq_api.get_kline_data_series(
                        tq_symbol, 
                        60,  # 1分钟数据
                        start_dt=start_date,
                        end_dt=end_date
                    )
                else:
                    # 使用数据长度
                    klines = self.tq_api.get_kline_serial(tq_symbol, 60, data_length=size)
            except Exception as e:
                if "专业版" in str(e) or "professional" in str(e).lower():
                    print(f"⚠️  检测到免费版限制，使用兼容模式")
                    # 免费版回退：使用get_kline_serial
                    klines = self.tq_api.get_kline_serial(tq_symbol, 60, data_length=size)
                else:
                    raise e
            
            if klines is None or len(klines) == 0:
                print(f"⚠️  {vt_symbol} 无数据")
                return False
            
            # 转换为vnpy格式
            bars = []
            for i in range(len(klines)):
                bar = BarData(
                    gateway_name="TQ",
                    symbol=symbol + (month or ""),
                    exchange=vnpy_exchange,
                    datetime=datetime.fromtimestamp(klines.iloc[i]["datetime"] / 1e9),
                    interval=interval,
                    volume=klines.volume.iloc[i],
                    open_price=klines.open.iloc[i],
                    high_price=klines.high.iloc[i],
                    low_price=klines.low.iloc[i],
                    close_price=klines.close.iloc[i],
                    open_interest=klines.close_oi.iloc[i] if 'close_oi' in klines.columns else 0
                )
                bars.append(bar)
            
            # 批量保存到数据库
            self.save_bars_batch(bars)
            
            print(f"✓ {vt_symbol} 下载完成，共 {len(bars)} 条数据")
            return True
            
        except Exception as e:
            print(f"✗ {vt_symbol} 下载失败: {e}")
            return False
    
    def save_bars_batch(self, bars: List[BarData], batch_size: int = 1000):
        """批量保存K线数据"""
        if not bars:
            return
        
        total = len(bars)
        saved = 0
        
        for i in range(0, total, batch_size):
            batch = bars[i:i + batch_size]
            try:
                self.database.save_bar_data(batch)
                saved += len(batch)
                print(f"  保存进度: {saved}/{total}")
            except Exception as e:
                print(f"  保存失败: {e}")
    
    def download_symbol_data(
        self, 
        symbol: str, 
        update_mode: str = "incremental",
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Dict[str, bool]:
        """
        下载某个品种的所有相关合约数据
        
        Args:
            symbol: 品种代码，如 'rb'
            update_mode: 更新模式，incremental或full
            start_date: 开始日期（专业版可用）
            end_date: 结束日期（专业版可用）
        
        Returns:
            下载结果字典
        """
        print(f"\n开始下载 {symbol} 数据...")
        print("=" * 50)
        
        # 获取品种信息
        info = get_futures_info(symbol)
        exchange = info.get("exchange")
        
        # 获取合约列表（基于active_months配置）
        contracts = get_priority_contracts(symbol)
        
        # CFFEX特殊提示
        if exchange and exchange.value == "CFFEX":
            future_contracts = [c for c in contracts if not (c.endswith('9999.CFFEX') or c.endswith('8888.CFFEX'))]
            print(f"⚠️  CFFEX品种限制: 每次最多下载2个未来合约")
            print(f"未来合约: {future_contracts}")
        
        print(f"下载合约: {len(contracts)} 个")
        
        # 根据update_mode确定数据量
        if update_mode == "incremental":
            size = 2000  # 约4-8天数据
            print(f"增量更新模式: 下载最近 {size} 条数据")
        else:  # full
            size = 10000  # 免费版最大值
            print(f"全量更新模式: 下载最近 {size} 条数据")
        
        results = {}
        success_count = 0
        
        for contract in contracts:
            print(f"\n下载: {contract}")
            success = self.download_contract_data(
                contract, 
                start_date=start_date,
                end_date=end_date,
                size=size
            )
            results[contract] = success
            if success:
                success_count += 1
        
        print(f"\n{symbol} 下载完成: {success_count}/{len(contracts)} 成功")
        return results
    
    def download_multiple_symbols(
        self, 
        symbols: List[str],
        update_mode: str = "incremental",
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Dict[str, Dict[str, bool]]:
        """
        下载多个品种的数据
        
        Args:
            symbols: 品种代码列表
            update_mode: 更新模式，incremental或full
            start_date: 开始日期（专业版可用）
            end_date: 结束日期（专业版可用）
        
        Returns:
            下载结果字典
        """
        print(f"批量下载开始，共 {len(symbols)} 个品种")
        print(f"更新模式: {update_mode}")
        print("=" * 60)
        
        all_results = {}
        
        for symbol in symbols:
            try:
                results = self.download_symbol_data(
                    symbol, 
                    update_mode=update_mode,
                    start_date=start_date,
                    end_date=end_date
                )
                all_results[symbol] = results
            except Exception as e:
                print(f"✗ {symbol} 下载异常: {e}")
                all_results[symbol] = {}
        
        # 统计结果
        total_contracts = 0
        total_success = 0
        
        for symbol, results in all_results.items():
            success_count = sum(1 for success in results.values() if success)
            total_contracts += len(results)
            total_success += success_count
            print(f"{symbol}: {success_count}/{len(results)} 成功")
        
        print(f"\n总计: {total_success}/{total_contracts} 合约下载成功")
        return all_results


def main():
    """测试函数"""
    print("期货数据下载器测试")
    print("=" * 50)
    
    # 初始化下载器
    downloader = FuturesDataDownloader()
    
    # 初始化数据库
    if not downloader.init_database():
        return
    
    # 初始化天勤SDK
    if not downloader.init_tqsdk():
        return
    
    try:
        # 测试下载螺纹钢数据
        symbol = "rb"
        
        # 设置下载日期范围（最近30天）
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        # 下载数据
        results = downloader.download_symbol_data(
            symbol,
            update_mode="incremental"
        )
        
        print(f"\n下载结果: {results}")
        
    finally:
        # 关闭连接
        downloader.close()


if __name__ == "__main__":
    main()