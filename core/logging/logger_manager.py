#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志管理器
基于loguru实现的高性能异步日志系统
"""

import os
import sys
import atexit
from datetime import datetime, time
from pathlib import Path
from typing import Optional
from loguru import logger


class LoggerManager:
    """日志管理器"""
    
    def __init__(self):
        self.base_path = Path(__file__).parent.parent.parent
        self.log_path = self.base_path / "logs"
        self.project_name = "atmquant"
        self._initialized = False
        self._log_handlers = []
    
    def setup_logger(
        self, 
        log_name: str = None,
        level: str = "DEBUG",
        output_console: bool = True,
        symbol: str = ""
    ) -> None:
        """
        设置日志系统
        
        Args:
            log_name: 日志文件名，默认使用项目名
            level: 日志级别
            output_console: 是否输出到控制台
            symbol: 符号标识，用于区分不同模块
        """
        if self._initialized:
            return
            
        try:
            # 确保日志目录存在
            if not self.log_path.exists():
                print(f'日志文件夹不存在：{self.log_path}，创建！')
                self.log_path.mkdir(parents=True, exist_ok=True)
            
            # 使用默认日志名
            if log_name is None:
                log_name = self.project_name
            
            # 日志文件完整路径
            log_file = self.log_path / f"{log_name}.log"
            
            # 定义日志格式，包含时间戳、日志级别、symbol标识、消息内容和代码位置
            format_str = (
                "<dim>{time:YY-MM-DD HH:mm:ss}</dim> | "
                "<level>{level: <8}</level> | "
                "<level>" + symbol + "|{message}</level> | "
                "{function}:{line}"
            )
            
            # 移除默认处理器
            logger.remove()
            
            # 设置不同日志级别的颜色
            logger.level("TRACE", color="<dim>")
            logger.level("DEBUG", color="<blue>")
            logger.level("INFO", color="<yellow>")
            logger.level("SUCCESS", color="<green>")
            logger.level("WARNING", color="<cyan>")
            logger.level("ERROR", color="<magenta>")
            logger.level("CRITICAL", color="<red>")
            
            # 添加文件日志处理器，使用优化配置
            file_handler_id = logger.add(
                str(log_file),  # 使用完整路径
                format=format_str,
                rotation=time(3, 0, 0),  # 每天凌晨3点轮转
                retention="30 days",  # 保留30天的日志
                compression="zip",  # 压缩历史日志
                level=level,
                enqueue=True,  # 启用异步写入，避免IO阻塞
                catch=True,    # 捕获异常
                delay=False,   # 立即创建文件
                buffering=1024 * 32,  # 使用32KB缓冲区，减少IO操作
                encoding="utf-8",  # 明确指定编码
                backtrace=True,  # 异常时显示完整堆栈
                diagnose=True,   # 显示变量值
            )
            self._log_handlers.append(file_handler_id)
            
            # 添加控制台输出处理器
            if output_console:
                console_handler_id = logger.add(
                    sink=sys.stderr,
                    format=format_str,
                    colorize=True,
                    level=level,
                    enqueue=True,  # 启用异步输出
                    catch=True,
                    backtrace=True,
                    diagnose=True
                )
                self._log_handlers.append(console_handler_id)
            
            # 注册程序退出时的清理函数
            atexit.register(self._cleanup)
            
            self._initialized = True
            logger.info(f"日志系统初始化完成，日志文件：{log_file}")
            
        except Exception as e:
            print(f"无法创建日志文件夹或设置日志：{e}")
            raise  # 重新抛出异常，确保初始化失败时能够被捕获
    
    def _cleanup(self):
        """程序退出时的清理函数"""
        try:
            logger.info("程序正在关闭，等待日志写入完成...")
            # 确保所有日志都被写入
            logger.complete()
            logger.info("日志系统已安全关闭")
        except Exception as e:
            print(f"关闭日志系统时发生错误: {e}")
    
    def get_logger_instance(self):
        """获取logger实例"""
        if not self._initialized:
            self.setup_logger()
        return logger


# 全局日志管理器实例
_logger_manager = LoggerManager()


def get_logger(
    log_name: str = None,
    log_path: str = None, 
    level: str = "DEBUG",
    output: bool = True,
    symbol: str = ""
):
    """
    获取日志记录器
    
    Args:
        log_name: 日志文件名（兼容旧接口）
        log_path: 日志路径（兼容旧接口，实际不使用）
        level: 日志级别
        output: 是否输出到控制台
        symbol: 符号标识
    
    Returns:
        loguru.logger实例
    """
    # 如果还没有初始化，则进行初始化
    if not _logger_manager._initialized:
        _logger_manager.setup_logger(
            log_name=log_name,
            level=level,
            output_console=output,
            symbol=symbol
        )
    
    # 为不同的symbol创建绑定的logger
    if symbol:
        return _logger_manager.get_logger_instance().bind(symbol=symbol)
    else:
        return _logger_manager.get_logger_instance()