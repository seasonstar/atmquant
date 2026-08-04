"""
General utility functions.
"""

import json
import sys
from datetime import datetime, time
from pathlib import Path
from collections.abc import Callable
from decimal import Decimal
from math import floor, ceil
from typing import overload, Literal

import numpy as np
import talib
from zoneinfo import ZoneInfo, available_timezones      # noqa

from .object import BarData, TickData
from .constant import Exchange, Interval
from .locale import _


def extract_vt_symbol(vt_symbol: str) -> tuple[str, Exchange]:
    """
    :return: (symbol, exchange)
    """
    symbol, exchange_str = vt_symbol.rsplit(".", 1)
    return symbol, Exchange(exchange_str)


def generate_vt_symbol(symbol: str, exchange: Exchange) -> str:
    """
    return vt_symbol
    """
    return f"{symbol}.{exchange.value}"


def _get_trader_dir(temp_name: str) -> tuple[Path, Path]:
    """
    Get path where trader is running in.
    """
    cwd: Path = Path.cwd()
    temp_path: Path = cwd.joinpath(temp_name)

    # If .vntrader folder exists in current working directory,
    # then use it as trader running path.
    if temp_path.exists():
        return cwd, temp_path

    # Otherwise use home path of system.
    home_path: Path = Path.home()
    temp_path = home_path.joinpath(temp_name)

    # Create .vntrader folder under home path if not exist.
    if not temp_path.exists():
        temp_path.mkdir()

    return home_path, temp_path


TRADER_DIR, TEMP_DIR = _get_trader_dir(".vntrader")
sys.path.append(str(TRADER_DIR))


def get_file_path(filename: str) -> Path:
    """
    Get path for temp file with filename.
    """
    return TEMP_DIR.joinpath(filename)


def get_folder_path(folder_name: str) -> Path:
    """
    Get path for temp folder with folder name.
    """
    folder_path: Path = TEMP_DIR.joinpath(folder_name)
    if not folder_path.exists():
        folder_path.mkdir()
    return folder_path


def get_icon_path(filepath: str, ico_name: str) -> str:
    """
    Get path for icon file with ico name.
    """
    ui_path: Path = Path(filepath).parent
    icon_path: Path = ui_path.joinpath("ico", ico_name)
    return str(icon_path)


def load_json(filename: str) -> dict:
    """
    Load data from json file in temp path.
    """
    filepath: Path = get_file_path(filename)

    if filepath.exists():
        with open(filepath, encoding="UTF-8") as f:
            data: dict = json.load(f)
        return data
    else:
        save_json(filename, {})
        return {}


def save_json(filename: str, data: dict) -> None:
    """
    Save data into json file in temp path.
    """
    filepath: Path = get_file_path(filename)
    with open(filepath, mode="w+", encoding="UTF-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )


def round_to(value: float, target: float) -> float:
    """
    Round price to price tick value.
    """
    decimal_value: Decimal = Decimal(str(value))
    decimal_target: Decimal = Decimal(str(target))
    rounded: float = float(int(round(decimal_value / decimal_target)) * decimal_target)
    return rounded


def floor_to(value: float, target: float) -> float:
    """
    Similar to math.floor function, but to target float number.
    """
    decimal_value: Decimal = Decimal(str(value))
    decimal_target: Decimal = Decimal(str(target))
    result: float = float(int(floor(decimal_value / decimal_target)) * decimal_target)
    return result


def ceil_to(value: float, target: float) -> float:
    """
    Similar to math.ceil function, but to target float number.
    """
    decimal_value: Decimal = Decimal(str(value))
    decimal_target: Decimal = Decimal(str(target))
    result: float = float(int(ceil(decimal_value / decimal_target)) * decimal_target)
    return result


def get_digits(value: float) -> int:
    """
    Get number of digits after decimal point.
    """
    value_str: str = str(value)

    if "e-" in value_str:
        _, buf = value_str.split("e-")
        return int(buf)
    elif "." in value_str:
        _, buf = value_str.split(".")
        return len(buf)
    else:
        return 0


class BarGenerator:
    """
    For:
    1. generating 1 minute bar data from tick data
    2. generating x minute bar/x hour bar data from 1 minute data
    Notice:
    1. for x minute bar, x must be able to divide 60: 2, 3, 5, 6, 10, 15, 20, 30
    2. for x hour bar, x can be any number
    3. hour_sessions parameter allows custom trading sessions for hour bars
    """

    def __init__(
        self,
        on_bar: Callable,
        window: int = 0,
        on_window_bar: Callable | None = None,
        interval: Interval = Interval.MINUTE,
        daily_end: time | None = None,
        hour_sessions: list[tuple[time, time]] | None = None,
        half_hour_sessions: list[tuple[time, time]] | None = None
    ) -> None:
        """
        Constructor

        Args:
            on_bar: 1分钟K线回调函数
            window: 窗口大小
            on_window_bar: 窗口K线回调函数
            interval: 窗口K线周期
            daily_end: 每日收盘时间
            hour_sessions: 小时交易时段列表，格式：[(开始时间, 结束时间), ...]
                          例如：[(time(9, 0), time(9, 59)), (time(10, 0), time(11, 14))]
                          如果为None，则使用默认的自然小时划分
            half_hour_sessions: 半小时交易时段列表，格式：[(开始时间, 结束时间), ...]
                               例如：[(time(9, 0), time(9, 29)), (time(9, 30), time(9, 59))]
                               如果为None，则使用默认的30分钟窗口划分
        """
        self.bar: BarData | None = None
        self.on_bar: Callable = on_bar

        self.interval: Interval = interval
        self.interval_count: int = 0

        self.hour_bar: BarData | None = None
        self.half_hour_bar: BarData | None = None
        self.daily_bar: BarData | None = None

        self.window: int = window
        self.window_bar: BarData | None = None
        self.on_window_bar: Callable | None = on_window_bar

        self.last_tick: TickData | None = None

        self.daily_end: time | None = daily_end
        if self.interval == Interval.DAILY and not self.daily_end:
            raise RuntimeError(_("合成日K线必须传入每日收盘时间"))

        # 交易时段配置（用于小时K线合成）
        self.hour_sessions = hour_sessions
        self.current_session_index: int | None = None

        # 交易时段配置（用于半小时K线合成）
        self.half_hour_sessions = half_hour_sessions
        self.current_half_hour_session_index: int | None = None

    def update_tick(self, tick: TickData) -> None:
        """
        Update new tick data into generator.
        """
        new_minute: bool = False

        # Filter tick data with 0 last price
        if not tick.last_price:
            return

        if not self.bar:
            new_minute = True
        elif (
            (self.bar.datetime.minute != tick.datetime.minute)
            or (self.bar.datetime.hour != tick.datetime.hour)
        ):
            self.bar.datetime = self.bar.datetime.replace(
                second=0, microsecond=0
            )
            self.on_bar(self.bar)

            new_minute = True

        if new_minute:
            self.bar = BarData(
                symbol=tick.symbol,
                exchange=tick.exchange,
                interval=Interval.MINUTE,
                datetime=tick.datetime,
                gateway_name=tick.gateway_name,
                open_price=tick.last_price,
                high_price=tick.last_price,
                low_price=tick.last_price,
                close_price=tick.last_price,
                open_interest=tick.open_interest
            )
        elif self.bar:
            self.bar.high_price = max(self.bar.high_price, tick.last_price)
            if self.last_tick and tick.high_price > self.last_tick.high_price:
                self.bar.high_price = max(self.bar.high_price, tick.high_price)

            self.bar.low_price = min(self.bar.low_price, tick.last_price)
            if self.last_tick and tick.low_price < self.last_tick.low_price:
                self.bar.low_price = min(self.bar.low_price, tick.low_price)

            self.bar.close_price = tick.last_price
            self.bar.open_interest = tick.open_interest
            self.bar.datetime = tick.datetime

        if self.last_tick and self.bar:
            volume_change: float = tick.volume - self.last_tick.volume
            self.bar.volume += max(volume_change, 0)

            turnover_change: float = tick.turnover - self.last_tick.turnover
            self.bar.turnover += max(turnover_change, 0)

        self.last_tick = tick

    def update_bar(self, bar: BarData) -> None:
        """
        Update 1 minute bar into generator
        """
        if self.interval == Interval.MINUTE:
            # 如果配置了半小时时段且window=30，使用半小时时段合成逻辑
            if self.window == 30 and self.half_hour_sessions:
                self.update_bar_half_hour_window(bar)
            else:
                self.update_bar_minute_window(bar)
        elif self.interval == Interval.HOUR:
            self.update_bar_hour_window(bar)
        else:
            self.update_bar_daily_window(bar)

    def update_bar_minute_window(self, bar: BarData) -> None:
        """"""
        # If not inited, create window bar object
        if not self.window_bar:
            dt: datetime = bar.datetime.replace(second=0, microsecond=0)
            self.window_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price
            )
        # Otherwise, update high/low price into window bar
        else:
            self.window_bar.high_price = max(
                self.window_bar.high_price,
                bar.high_price
            )
            self.window_bar.low_price = min(
                self.window_bar.low_price,
                bar.low_price
            )

        # Update close price/volume/turnover into window bar
        self.window_bar.close_price = bar.close_price
        self.window_bar.volume += bar.volume
        self.window_bar.turnover += bar.turnover
        self.window_bar.open_interest = bar.open_interest

        # Check if window bar completed
        if not (bar.datetime.minute + 1) % self.window:
            if self.on_window_bar:
                self.on_window_bar(self.window_bar)

            self.window_bar = None

    def update_bar_hour_window(self, bar: BarData) -> None:
        """
        更新小时K线窗口
        
        如果配置了hour_sessions，则按照交易时段合成K线
        否则按照自然小时（59分钟）合成K线
        """
        # 如果配置了交易时段，使用交易时段逻辑
        if self.hour_sessions:
            self._update_bar_hour_window_with_sessions(bar)
        else:
            self._update_bar_hour_window_default(bar)
    
    def _update_bar_hour_window_default(self, bar: BarData) -> None:
        """默认的小时K线更新逻辑（按自然小时）"""
        # If not inited, create window bar object
        if not self.hour_bar:
            dt: datetime = bar.datetime.replace(minute=0, second=0, microsecond=0)
            self.hour_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest
            )
            return

        finished_bar: BarData | None = None

        # If minute is 59, update minute bar into window bar and push
        if bar.datetime.minute == 59:
            self.hour_bar.high_price = max(
                self.hour_bar.high_price,
                bar.high_price
            )
            self.hour_bar.low_price = min(
                self.hour_bar.low_price,
                bar.low_price
            )

            self.hour_bar.close_price = bar.close_price
            self.hour_bar.volume += bar.volume
            self.hour_bar.turnover += bar.turnover
            self.hour_bar.open_interest = bar.open_interest

            finished_bar = self.hour_bar
            self.hour_bar = None

        # If minute bar of new hour, then push existing window bar
        elif bar.datetime.hour != self.hour_bar.datetime.hour:
            finished_bar = self.hour_bar

            dt = bar.datetime.replace(minute=0, second=0, microsecond=0)
            self.hour_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest
            )
        # Otherwise only update minute bar
        else:
            self.hour_bar.high_price = max(
                self.hour_bar.high_price,
                bar.high_price
            )
            self.hour_bar.low_price = min(
                self.hour_bar.low_price,
                bar.low_price
            )

            self.hour_bar.close_price = bar.close_price
            self.hour_bar.volume += bar.volume
            self.hour_bar.turnover += bar.turnover
            self.hour_bar.open_interest = bar.open_interest

        # Push finished window bar
        if finished_bar:
            self.on_hour_bar(finished_bar)
    
    def _update_bar_hour_window_with_sessions(self, bar: BarData) -> None:
        """基于交易时段的小时K线更新逻辑"""
        bar_time = bar.datetime.time()
        
        # 查找当前K线所属的交易时段
        session_index = self._find_session_index(bar_time)
        
        # 如果不在任何交易时段内，忽略该K线
        if session_index is None:
            return
        
        # 判断是否需要生成新的小时K线
        need_new_hour_bar = False
        
        # 如果是第一根K线，或者切换到了新的交易时段
        if not self.hour_bar:
            need_new_hour_bar = True
        elif self.current_session_index != session_index:
            # 切换到新的交易时段，先推送旧的小时K线
            finished_bar = self.hour_bar
            self.on_hour_bar(finished_bar)
            need_new_hour_bar = True
        else:
            # 同一个交易时段内，检查是否到达时段结束时间
            session_start, session_end = self.hour_sessions[session_index]
            if bar_time >= session_end:
                # 到达时段结束时间，更新并推送小时K线
                self.hour_bar.high_price = max(self.hour_bar.high_price, bar.high_price)
                self.hour_bar.low_price = min(self.hour_bar.low_price, bar.low_price)
                self.hour_bar.close_price = bar.close_price
                self.hour_bar.volume += bar.volume
                self.hour_bar.turnover += bar.turnover
                self.hour_bar.open_interest = bar.open_interest
                
                finished_bar = self.hour_bar
                self.on_hour_bar(finished_bar)
                
                # 检查是否立即开始下一个时段
                next_session_index = self._find_session_index(bar_time, start_from=session_index + 1)
                if next_session_index is not None:
                    need_new_hour_bar = True
                    session_index = next_session_index
                else:
                    self.hour_bar = None
                    self.current_session_index = None
                    return
        
        # 创建新的小时K线
        if need_new_hour_bar:
            session_start, session_end = self.hour_sessions[session_index]
            dt = bar.datetime.replace(
                hour=session_start.hour,
                minute=session_start.minute,
                second=0,
                microsecond=0
            )
            
            self.hour_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest
            )
            self.current_session_index = session_index
        else:
            # 更新现有小时K线
            self.hour_bar.high_price = max(self.hour_bar.high_price, bar.high_price)
            self.hour_bar.low_price = min(self.hour_bar.low_price, bar.low_price)
            self.hour_bar.close_price = bar.close_price
            self.hour_bar.volume += bar.volume
            self.hour_bar.turnover += bar.turnover
            self.hour_bar.open_interest = bar.open_interest
    
    def _find_session_index(
        self,
        bar_time: time,
        start_from: int = 0
    ) -> int | None:
        """
        查找给定时间所属的交易时段索引
        
        Args:
            bar_time: K线时间
            start_from: 从哪个索引开始查找
        
        Returns:
            交易时段索引，如果不在任何时段内则返回None
        """
        if not self.hour_sessions:
            return None
        
        for i in range(start_from, len(self.hour_sessions)):
            session_start, session_end = self.hour_sessions[i]
            
            # 处理跨日的情况（例如夜盘）
            if session_start <= session_end:
                # 正常时段（不跨日）
                if session_start <= bar_time <= session_end:
                    return i
            else:
                # 跨日时段
                if bar_time >= session_start or bar_time <= session_end:
                    return i
        
        return None

    def update_bar_half_hour_window(self, bar: BarData) -> None:
        """
        更新半小时K线窗口（基于交易时段）

        使用 half_hour_sessions 配置的时段进行合成
        """
        bar_time = bar.datetime.time()

        # 查找当前K线所属的交易时段
        session_index = self._find_half_hour_session_index(bar_time)

        # 如果不在任何交易时段内，忽略该K线
        if session_index is None:
            return

        # 判断是否需要生成新的半小时K线
        need_new_half_hour_bar = False

        # 如果是第一根K线，或者切换到了新的交易时段
        if not self.half_hour_bar:
            need_new_half_hour_bar = True
        elif self.current_half_hour_session_index != session_index:
            # 切换到新的交易时段，先推送旧的半小时K线
            finished_bar = self.half_hour_bar
            self.on_half_hour_bar(finished_bar)
            need_new_half_hour_bar = True
        else:
            # 同一个交易时段内，检查是否到达时段结束时间
            session_start, session_end = self.half_hour_sessions[session_index]
            if bar_time >= session_end:
                # 到达时段结束时间，更新并推送半小时K线
                self.half_hour_bar.high_price = max(self.half_hour_bar.high_price, bar.high_price)
                self.half_hour_bar.low_price = min(self.half_hour_bar.low_price, bar.low_price)
                self.half_hour_bar.close_price = bar.close_price
                self.half_hour_bar.volume += bar.volume
                self.half_hour_bar.turnover += bar.turnover
                self.half_hour_bar.open_interest = bar.open_interest

                finished_bar = self.half_hour_bar
                self.on_half_hour_bar(finished_bar)

                # 检查是否立即开始下一个时段
                next_session_index = self._find_half_hour_session_index(bar_time, start_from=session_index + 1)
                if next_session_index is not None:
                    need_new_half_hour_bar = True
                    session_index = next_session_index
                else:
                    self.half_hour_bar = None
                    self.current_half_hour_session_index = None
                    return

        # 创建新的半小时K线
        if need_new_half_hour_bar:
            session_start, session_end = self.half_hour_sessions[session_index]
            dt = bar.datetime.replace(
                hour=session_start.hour,
                minute=session_start.minute,
                second=0,
                microsecond=0
            )

            self.half_hour_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest
            )
            self.current_half_hour_session_index = session_index
        else:
            # 更新现有半小时K线
            self.half_hour_bar.high_price = max(self.half_hour_bar.high_price, bar.high_price)
            self.half_hour_bar.low_price = min(self.half_hour_bar.low_price, bar.low_price)
            self.half_hour_bar.close_price = bar.close_price
            self.half_hour_bar.volume += bar.volume
            self.half_hour_bar.turnover += bar.turnover
            self.half_hour_bar.open_interest = bar.open_interest

    def _find_half_hour_session_index(
        self,
        bar_time: time,
        start_from: int = 0
    ) -> int | None:
        """
        查找给定时间所属的半小时交易时段索引

        Args:
            bar_time: K线时间
            start_from: 从哪个索引开始查找

        Returns:
            交易时段索引，如果不在任何时段内则返回None
        """
        if not self.half_hour_sessions:
            return None

        for i in range(start_from, len(self.half_hour_sessions)):
            session_start, session_end = self.half_hour_sessions[i]

            # 处理跨日的情况（例如夜盘）
            if session_start <= session_end:
                # 正常时段（不跨日）
                if session_start <= bar_time <= session_end:
                    return i
            else:
                # 跨日时段
                if bar_time >= session_start or bar_time <= session_end:
                    return i

        return None

    def on_half_hour_bar(self, bar: BarData) -> None:
        """半小时K线回调"""
        if self.on_window_bar:
            self.on_window_bar(bar)

    def on_hour_bar(self, bar: BarData) -> None:
        """"""
        if self.window == 1:
            if self.on_window_bar:
                self.on_window_bar(bar)
        else:
            if not self.window_bar:
                self.window_bar = BarData(
                    symbol=bar.symbol,
                    exchange=bar.exchange,
                    datetime=bar.datetime,
                    gateway_name=bar.gateway_name,
                    open_price=bar.open_price,
                    high_price=bar.high_price,
                    low_price=bar.low_price
                )
            else:
                self.window_bar.high_price = max(
                    self.window_bar.high_price,
                    bar.high_price
                )
                self.window_bar.low_price = min(
                    self.window_bar.low_price,
                    bar.low_price
                )

            self.window_bar.close_price = bar.close_price
            self.window_bar.volume += bar.volume
            self.window_bar.turnover += bar.turnover
            self.window_bar.open_interest = bar.open_interest

            self.interval_count += 1
            if not self.interval_count % self.window:
                self.interval_count = 0

                if self.on_window_bar:
                    self.on_window_bar(self.window_bar)

                self.window_bar = None

    def update_bar_daily_window(self, bar: BarData) -> None:
        """"""
        # If not inited, create daily bar object
        if not self.daily_bar:
            self.daily_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=bar.datetime,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price
            )
        # Otherwise, update high/low price into daily bar
        else:
            self.daily_bar.high_price = max(
                self.daily_bar.high_price,
                bar.high_price
            )
            self.daily_bar.low_price = min(
                self.daily_bar.low_price,
                bar.low_price
            )

        # Update close price/volume/turnover into daily bar
        self.daily_bar.close_price = bar.close_price
        self.daily_bar.volume += bar.volume
        self.daily_bar.turnover += bar.turnover
        self.daily_bar.open_interest = bar.open_interest

        # Check if daily bar completed
        if bar.datetime.time() == self.daily_end:
            self.daily_bar.datetime = bar.datetime.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )

            if self.on_window_bar:
                self.on_window_bar(self.daily_bar)

            self.daily_bar = None

    def generate(self) -> BarData | None:
        """
        Generate the bar data and call callback immediately.
        """
        bar: BarData | None = self.bar

        if bar:
            bar.datetime = bar.datetime.replace(second=0, microsecond=0)
            self.on_bar(bar)

        self.bar = None
        return bar


class ArrayManager:
    """
    For:
    1. time series container of bar data
    2. calculating technical indicator value
    """

    def __init__(self, size: int = 100) -> None:
        """Constructor"""
        self.count: int = 0
        self.size: int = size
        self.inited: bool = False

        self.open_array: np.ndarray = np.zeros(size)
        self.high_array: np.ndarray = np.zeros(size)
        self.low_array: np.ndarray = np.zeros(size)
        self.close_array: np.ndarray = np.zeros(size)
        self.volume_array: np.ndarray = np.zeros(size)
        self.turnover_array: np.ndarray = np.zeros(size)
        self.open_interest_array: np.ndarray = np.zeros(size)

    def update_bar(self, bar: BarData) -> None:
        """
        Update new bar data into array manager.
        """
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True

        self.open_array[:-1] = self.open_array[1:]
        self.high_array[:-1] = self.high_array[1:]
        self.low_array[:-1] = self.low_array[1:]
        self.close_array[:-1] = self.close_array[1:]
        self.volume_array[:-1] = self.volume_array[1:]
        self.turnover_array[:-1] = self.turnover_array[1:]
        self.open_interest_array[:-1] = self.open_interest_array[1:]

        self.open_array[-1] = bar.open_price
        self.high_array[-1] = bar.high_price
        self.low_array[-1] = bar.low_price
        self.close_array[-1] = bar.close_price
        self.volume_array[-1] = bar.volume
        self.turnover_array[-1] = bar.turnover
        self.open_interest_array[-1] = bar.open_interest

    @property
    def open(self) -> np.ndarray:
        """
        Get open price time series.
        """
        return self.open_array

    @property
    def high(self) -> np.ndarray:
        """
        Get high price time series.
        """
        return self.high_array

    @property
    def low(self) -> np.ndarray:
        """
        Get low price time series.
        """
        return self.low_array

    @property
    def close(self) -> np.ndarray:
        """
        Get close price time series.
        """
        return self.close_array

    @property
    def volume(self) -> np.ndarray:
        """
        Get trading volume time series.
        """
        return self.volume_array

    @property
    def turnover(self) -> np.ndarray:
        """
        Get trading turnover time series.
        """
        return self.turnover_array

    @property
    def open_interest(self) -> np.ndarray:
        """
        Get trading volume time series.
        """
        return self.open_interest_array

    @overload
    def sma(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def sma(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def sma(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        Simple moving average.
        """
        result_array: np.ndarray = talib.SMA(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def ema(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def ema(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def ema(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        Exponential moving average.
        """
        result_array: np.ndarray = talib.EMA(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def kama(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def kama(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def kama(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        KAMA.
        """
        result_array: np.ndarray = talib.KAMA(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def wma(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def wma(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def wma(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        WMA.
        """
        result_array: np.ndarray = talib.WMA(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def apo(self, fast_period: int, slow_period: int, matype: int = 0, array: Literal[False] = False) -> float: ...
    @overload
    def apo(self, fast_period: int, slow_period: int, matype: int = 0, *, array: Literal[True]) -> np.ndarray: ...
    def apo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: bool = False
    ) -> float | np.ndarray:
        """
        APO.
        """
        result_array: np.ndarray = talib.APO(self.close, fast_period, slow_period, matype)      # type: ignore
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def cmo(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def cmo(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def cmo(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        CMO.
        """
        result_array: np.ndarray = talib.CMO(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def mom(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def mom(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def mom(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        MOM.
        """
        result_array: np.ndarray = talib.MOM(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def ppo(self, fast_period: int, slow_period: int, matype: int = 0, array: Literal[False] = False) -> float: ...
    @overload
    def ppo(self, fast_period: int, slow_period: int, matype: int = 0, *, array: Literal[True]) -> np.ndarray: ...
    def ppo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: bool = False
    ) -> float | np.ndarray:
        """
        PPO.
        """
        result_array: np.ndarray = talib.PPO(self.close, fast_period, slow_period, matype)      # type: ignore
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def roc(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def roc(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def roc(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        ROC.
        """
        result_array: np.ndarray = talib.ROC(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def rocr(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def rocr(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def rocr(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        ROCR.
        """
        result_array: np.ndarray = talib.ROCR(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def rocp(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def rocp(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def rocp(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        ROCP.
        """
        result_array: np.ndarray = talib.ROCP(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def rocr_100(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def rocr_100(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def rocr_100(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        ROCR100.
        """
        result_array: np.ndarray = talib.ROCR100(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def trix(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def trix(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def trix(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        TRIX.
        """
        result_array: np.ndarray = talib.TRIX(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def std(self, n: int, nbdev: int = 1, array: Literal[False] = False) -> float: ...
    @overload
    def std(self, n: int, nbdev: int = 1, *, array: Literal[True]) -> np.ndarray: ...
    def std(self, n: int, nbdev: int = 1, array: bool = False) -> float | np.ndarray:
        """
        Standard deviation.
        """
        result_array: np.ndarray = talib.STDDEV(self.close, n, nbdev)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def obv(self, array: Literal[False] = False) -> float: ...
    @overload
    def obv(self, array: Literal[True]) -> np.ndarray: ...
    def obv(self, array: bool = False) -> float | np.ndarray:
        """
        OBV.
        """
        result_array: np.ndarray = talib.OBV(self.close, self.volume)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def cci(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def cci(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def cci(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        Commodity Channel Index (CCI).
        """
        result_array: np.ndarray = talib.CCI(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def atr(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def atr(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def atr(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        Average True Range (ATR).
        """
        result_array: np.ndarray = talib.ATR(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def natr(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def natr(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def natr(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        NATR.
        """
        result_array: np.ndarray = talib.NATR(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def rsi(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def rsi(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def rsi(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        Relative Strenght Index (RSI).
        """
        result_array: np.ndarray = talib.RSI(self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def macd(self, fast_period: int, slow_period: int, signal_period: int, array: Literal[False] = False) -> tuple[float, float, float]: ...
    @overload
    def macd(self, fast_period: int, slow_period: int, signal_period: int, array: Literal[True]) -> tuple[np.ndarray, np.ndarray, np.ndarray]: ...
    def macd(
        self,
        fast_period: int,
        slow_period: int,
        signal_period: int,
        array: bool = False
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | tuple[float, float, float]:
        """
        MACD.
        """
        macd, signal, hist = talib.MACD(
            self.close, fast_period, slow_period, signal_period
        )
        if array:
            return macd, signal, hist
        return macd[-1], signal[-1], hist[-1]

    @overload
    def adx(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def adx(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def adx(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        ADX.
        """
        result_array: np.ndarray = talib.ADX(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def adxr(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def adxr(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def adxr(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        ADXR.
        """
        result_array: np.ndarray = talib.ADXR(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def dx(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def dx(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def dx(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        DX.
        """
        result_array: np.ndarray = talib.DX(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def minus_di(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def minus_di(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def minus_di(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        MINUS_DI.
        """
        result_array: np.ndarray = talib.MINUS_DI(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def plus_di(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def plus_di(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def plus_di(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        PLUS_DI.
        """
        result_array: np.ndarray = talib.PLUS_DI(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def willr(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def willr(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def willr(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        WILLR.
        """
        result_array: np.ndarray = talib.WILLR(self.high, self.low, self.close, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def ultosc(self, time_period1: int = 7, time_period2: int = 14, time_period3: int = 28, array: Literal[False] = False) -> float: ...
    @overload
    def ultosc(self, time_period1: int = 7, time_period2: int = 14, time_period3: int = 28, *, array: Literal[True]) -> np.ndarray: ...
    def ultosc(
        self,
        time_period1: int = 7,
        time_period2: int = 14,
        time_period3: int = 28,
        array: bool = False
    ) -> float | np.ndarray:
        """
        Ultimate Oscillator.
        """
        result_array: np.ndarray = talib.ULTOSC(self.high, self.low, self.close, time_period1, time_period2, time_period3)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def trange(self, array: Literal[False] = False) -> float: ...
    @overload
    def trange(self, array: Literal[True]) -> np.ndarray: ...
    def trange(self, array: bool = False) -> float | np.ndarray:
        """
        TRANGE.
        """
        result_array: np.ndarray = talib.TRANGE(self.high, self.low, self.close)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def boll(self, n: int, dev: float, array: Literal[False] = False) -> tuple[float, float]: ...
    @overload
    def boll(self, n: int, dev: float, array: Literal[True]) -> tuple[np.ndarray, np.ndarray]: ...
    def boll(
        self,
        n: int,
        dev: float,
        array: bool = False
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """
        Bollinger Channel.
        """
        mid_array: np.ndarray = talib.SMA(self.close, n)
        std_array: np.ndarray = talib.STDDEV(self.close, n, 1)

        if array:
            up_array: np.ndarray = mid_array + std_array * dev
            down_array: np.ndarray = mid_array - std_array * dev
            return up_array, down_array
        else:
            mid: float = mid_array[-1]
            std: float = std_array[-1]
            up: float = mid + std * dev
            down: float = mid - std * dev
            return up, down

    @overload
    def keltner(self, n: int, dev: float, array: Literal[False] = False) -> tuple[float, float]: ...
    @overload
    def keltner(self, n: int, dev: float, array: Literal[True]) -> tuple[np.ndarray, np.ndarray]: ...
    def keltner(
        self,
        n: int,
        dev: float,
        array: bool = False
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """
        Keltner Channel.
        """
        mid_array: np.ndarray = talib.SMA(self.close, n)
        atr_array: np.ndarray = talib.ATR(self.high, self.low, self.close, n)

        if array:
            up_array: np.ndarray = mid_array + atr_array * dev
            down_array: np.ndarray = mid_array - atr_array * dev
            return up_array, down_array
        else:
            mid: float = mid_array[-1]
            atr: float = atr_array[-1]
            up: float = mid + atr * dev
            down: float = mid - atr * dev
            return up, down

    @overload
    def donchian(self, n: int, array: Literal[False] = False) -> tuple[float, float]: ...
    @overload
    def donchian(self, n: int, array: Literal[True]) -> tuple[np.ndarray, np.ndarray]: ...
    def donchian(
        self, n: int, array: bool = False
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """
        Donchian Channel.
        """
        up: np.ndarray = talib.MAX(self.high, n)
        down: np.ndarray = talib.MIN(self.low, n)

        if array:
            return up, down
        return up[-1], down[-1]

    @overload
    def aroon(self, n: int, array: Literal[False] = False) -> tuple[float, float]: ...
    @overload
    def aroon(self, n: int, array: Literal[True]) -> tuple[np.ndarray, np.ndarray]: ...
    def aroon(
        self,
        n: int,
        array: bool = False
    ) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
        """
        Aroon indicator.
        """
        aroon_down, aroon_up = talib.AROON(self.high, self.low, n)

        if array:
            return aroon_up, aroon_down
        return aroon_up[-1], aroon_down[-1]

    @overload
    def aroonosc(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def aroonosc(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def aroonosc(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        Aroon Oscillator.
        """
        result_array: np.ndarray = talib.AROONOSC(self.high, self.low, n)

        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def minus_dm(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def minus_dm(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def minus_dm(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        MINUS_DM.
        """
        result_array: np.ndarray = talib.MINUS_DM(self.high, self.low, n)

        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def plus_dm(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def plus_dm(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def plus_dm(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        PLUS_DM.
        """
        result_array: np.ndarray = talib.PLUS_DM(self.high, self.low, n)

        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def mfi(self, n: int, array: Literal[False] = False) -> float: ...
    @overload
    def mfi(self, n: int, array: Literal[True]) -> np.ndarray: ...
    def mfi(self, n: int, array: bool = False) -> float | np.ndarray:
        """
        Money Flow Index.
        """
        result_array: np.ndarray = talib.MFI(self.high, self.low, self.close, self.volume, n)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def ad(self, array: Literal[False] = False) -> float: ...
    @overload
    def ad(self, array: Literal[True]) -> np.ndarray: ...
    def ad(self, array: bool = False) -> float | np.ndarray:
        """
        AD.
        """
        result_array: np.ndarray = talib.AD(self.high, self.low, self.close, self.volume)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def adosc(self, fast_period: int, slow_period: int, array: Literal[False] = False) -> float: ...
    @overload
    def adosc(self, fast_period: int, slow_period: int, array: Literal[True]) -> np.ndarray: ...
    def adosc(
        self,
        fast_period: int,
        slow_period: int,
        array: bool = False
    ) -> float | np.ndarray:
        """
        ADOSC.
        """
        result_array: np.ndarray = talib.ADOSC(self.high, self.low, self.close, self.volume, fast_period, slow_period)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def bop(self, array: Literal[False] = False) -> float: ...
    @overload
    def bop(self, array: Literal[True]) -> np.ndarray: ...
    def bop(self, array: bool = False) -> float | np.ndarray:
        """
        BOP.
        """
        result_array: np.ndarray = talib.BOP(self.open, self.high, self.low, self.close)

        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value

    @overload
    def stoch(self, fastk_period: int, slowk_period: int, slowk_matype: int, slowd_period: int, slowd_matype: int, array: Literal[False] = False) -> tuple[float, float]: ...
    @overload
    def stoch(self, fastk_period: int, slowk_period: int, slowk_matype: int, slowd_period: int, slowd_matype: int, array: Literal[True]) -> tuple[np.ndarray, np.ndarray]: ...
    def stoch(
        self,
        fastk_period: int,
        slowk_period: int,
        slowk_matype: int,
        slowd_period: int,
        slowd_matype: int,
        array: bool = False
    ) -> tuple[float, float] | tuple[np.ndarray, np.ndarray]:
        """
        Stochastic Indicator
        """
        k, d = talib.STOCH(
            self.high,
            self.low,
            self.close,
            fastk_period,
            slowk_period,
            slowk_matype,    # type: ignore
            slowd_period,
            slowd_matype     # type: ignore
        )
        if array:
            return k, d
        return k[-1], d[-1]

    @overload
    def sar(self, acceleration: float, maximum: float, array: Literal[False] = False) -> float: ...
    @overload
    def sar(self, acceleration: float, maximum: float, array: Literal[True]) -> np.ndarray: ...
    def sar(self, acceleration: float, maximum: float, array: bool = False) -> float | np.ndarray:
        """
        SAR.
        """
        result_array: np.ndarray = talib.SAR(self.high, self.low, acceleration, maximum)
        if array:
            return result_array

        result_value: float = result_array[-1]
        return result_value


def virtual(func: Callable) -> Callable:
    """
    mark a function as "virtual", which means that this function can be override.
    any base class should use this or @abstractmethod to decorate all functions
    that can be (re)implemented by subclasses.
    """
    return func
