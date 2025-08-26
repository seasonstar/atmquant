#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货品种配置管理
包含期货品种的基本参数和合约管理配置
"""

from typing import Dict, List, Any
from datetime import datetime, timedelta
from vnpy.trader.constant import Exchange

# 期货品种基本参数配置
FUTURES_INFO = {
    # 上期所品种 (SHFE)
    "rb": {  # 螺纹钢
        "name": "螺纹钢",
        "exchange": Exchange.SHFE,
        "size": 10,  # 10吨/手
        "pricetick": 1.0,  # 1元/吨
        "deposit_rate": 0.07,  # 7%保证金
        "rate": 0.0001,  # 1.0‰手续费率
        "slippage": 0,  # 滑点
        "active_months": [1, 5, 10],  # 活跃交易月份
    },
    "hc": {  # 热轧卷板
        "name": "热轧卷板", 
        "exchange": Exchange.SHFE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0001,  # 1.0‰手续费率
        "slippage": 0,
        "active_months": [1, 5, 10],
    },
    "cu": {  # 沪铜
        "name": "沪铜",
        "exchange": Exchange.SHFE,
        "size": 5,  # 5吨/手
        "pricetick": 10.0,  # 10元/吨
        "deposit_rate": 0.09,
        "rate": 0.00005,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "ad": {  # 铸造铝
        "name": "铸造铝",
        "exchange": Exchange.SHFE,
        "size": 10,  # 10吨/手
        "pricetick": 5.0,  # 5元/吨
        "deposit_rate": 0.09,  # 9%保证金
        "rate": 0.0001,  # 手续费率
        "slippage": 0.0,  # 滑点
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],  # 保持活跃的月份数量
    },
    "al": {  # 沪铝
        "name": "沪铝",
        "exchange": Exchange.SHFE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.09,
        "rate": 0,
        "slippage": 3.0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "zn": {  # 沪锌
        "name": "沪锌",
        "exchange": Exchange.SHFE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.09,
        "rate": 0,
        "slippage": 3.0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "au": {  # 沪金
        "name": "沪金",
        "exchange": Exchange.SHFE,
        "size": 1000,  # 1000克/手
        "pricetick": 0.02,  # 0.02元/克
        "deposit_rate": 0.11,
        "rate": 0,
        "slippage": 20.0,
        "active_months": [2, 4, 6, 8, 10, 12],
    },
    "ag": {  # 沪银
        "name": "沪银",
        "exchange": Exchange.SHFE,
        "size": 15,  # 15千克/手
        "pricetick": 1.0,  # 1元/千克
        "deposit_rate": 0.14,
        "rate": 0.00005,
        "slippage": 0,
        "active_months": [2, 4, 6, 8, 10, 12],
    },
    "ni": {  # 沪镍
        "name": "沪镍",
        "exchange": Exchange.SHFE,
        "size": 1,
        "pricetick": 10.0,
        "deposit_rate": 0.12,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "sn": {  # 沪锡
        "name": "沪锡",
        "exchange": Exchange.SHFE,
        "size": 1,
        "pricetick": 10.0,
        "deposit_rate": 0.12,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "pb": {  # 沪铅
        "name": "沪铅",
        "exchange": Exchange.SHFE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.09,
        "rate": 0.00004,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "wr": {  # 线材
        "name": "线材",
        "exchange": Exchange.SHFE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.10,
        "rate": 0.0004,
        "slippage": 0,
        "active_months": [1, 5, 10],
    },
    "bu": {  # 沥青
        "name": "沥青",
        "exchange": Exchange.SHFE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.10,
        "rate": 0.0005,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "ru": {  # 天然橡胶
        "name": "天然橡胶",
        "exchange": Exchange.SHFE,
        "size": 10,
        "pricetick": 5.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 5, 9],
    },
    "sp": {  # 纸浆
        "name": "纸浆",
        "exchange": Exchange.SHFE,
        "size": 10,
        "pricetick": 2.0,
        "deposit_rate": 0.08,
        "rate": 0.0005,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "ss": {  # 不锈钢
        "name": "不锈钢",
        "exchange": Exchange.SHFE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.10,
        "rate": 0.0,
        "slippage": 2.0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "fu": {  # 燃料油
        "name": "燃料油",
        "exchange": Exchange.SHFE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.10,
        "rate": 0.00005,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "ao": {  # 氧化铝
        "name": "氧化铝",
        "exchange": Exchange.SHFE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.10,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "br": {  # 丁二烯橡胶
        "name": "丁二烯橡胶",
        "exchange": Exchange.SHFE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.12,
        "rate": 0.00002,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    
    # 大商所品种 (DCE)
    "i": {  # 铁矿石
        "name": "铁矿石",
        "exchange": Exchange.DCE,
        "size": 100,  # 100吨/手
        "pricetick": 0.5,  # 0.5元/吨
        "deposit_rate": 0.15,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 5, 9],
    },
    "j": {  # 焦炭
        "name": "焦炭",
        "exchange": Exchange.DCE,
        "size": 100,
        "pricetick": 0.5,
        "deposit_rate": 0.15,
        "rate": 0.00014,
        "slippage": 0,
        "active_months": [1, 5, 9],
    },
    "jm": {  # 焦煤
        "name": "焦煤",
        "exchange": Exchange.DCE,
        "size": 60,  # 60吨/手
        "pricetick": 0.5,
        "deposit_rate": 0.20,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 5, 9],
    },
    "m": {  # 豆粕
        "name": "豆粕",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.5,
        "active_months": [1, 5, 9],
    },
    "y": {  # 豆油
        "name": "豆油",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 2.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 2.5,
        "active_months": [1, 5, 9],
    },
    "a": {  # 豆一
        "name": "豆一",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 2.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "b": {  # 豆二
        "name": "豆二",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "c": {  # 玉米
        "name": "玉米",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.2,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "cs": {  # 玉米淀粉
        "name": "玉米淀粉",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.06,
        "rate": 0.0,
        "slippage": 1.5,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "l": {  # 聚乙烯
        "name": "聚乙烯",
        "exchange": Exchange.DCE,
        "size": 5,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "v": {  # PVC
        "name": "PVC",
        "exchange": Exchange.DCE,
        "size": 5,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "p": {  # 棕榈油
        "name": "棕榈油",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 2.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 2.5,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "pp": {  # 聚丙烯
        "name": "聚丙烯",
        "exchange": Exchange.DCE,
        "size": 5,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "fb": {  # 纤维板
        "name": "纤维板",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 0.5,
        "deposit_rate": 0.10,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "bb": {  # 胶合板
        "name": "胶合板",
        "exchange": Exchange.DCE,
        "size": 500,
        "pricetick": 0.05,
        "deposit_rate": 0.50,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "jd": {  # 鸡蛋
        "name": "鸡蛋",
        "exchange": Exchange.DCE,
        "size": 5,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.00015,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "lh": {  # 生猪
        "name": "生猪",
        "exchange": Exchange.DCE,
        "size": 16,
        "pricetick": 5.0,
        "deposit_rate": 0.08,
        "rate": 0.0002,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "rr": {  # 粳米
        "name": "粳米",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.06,
        "rate": 0.0,
        "slippage": 1.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "eg": {  # 乙二醇
        "name": "乙二醇",
        "exchange": Exchange.DCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "eb": {  # 苯乙烯
        "name": "苯乙烯",
        "exchange": Exchange.DCE,
        "size": 5,
        "pricetick": 1.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "pg": {  # 液化石油气
        "name": "液化石油气",
        "exchange": Exchange.DCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 6.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "lg": {  # 原木
        "name": "原木",
        "exchange": Exchange.DCE,
        "size": 90,
        "pricetick": 0.5,
        "deposit_rate": 0.09,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "bz": {  # 苯
        "name": "苯",
        "exchange": Exchange.DCE,
        "size": 30,
        "pricetick": 1.0,
        "deposit_rate": 0.08,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    
    # 郑商所品种 (CZCE)
    "MA": {  # 甲醇
        "name": "甲醇",
        "exchange": Exchange.CZCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.08,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 5, 9],
    },
    "TA": {  # PTA
        "name": "PTA",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 2.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 5, 9],
    },
    "CF": {  # 棉花
        "name": "棉花",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.09,
        "rate": 0.0,
        "slippage": 4.3,
        "active_months": [1, 5, 9],
    },
    "SR": {  # 白糖
        "name": "白糖",
        "exchange": Exchange.CZCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 5, 9],
    },
    "RM": {  # 菜粕
        "name": "菜粕",
        "exchange": Exchange.CZCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.5,
        "active_months": [1, 5, 9],
    },
    "OI": {  # 菜籽油
        "name": "菜籽油",
        "exchange": Exchange.CZCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 2.0,
        "active_months": [1, 5, 9],
    },
    "FG": {  # 玻璃
        "name": "玻璃",
        "exchange": Exchange.CZCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.12,
        "rate": 0.0,
        "slippage": 6.0,
        "active_months": [1, 5, 9],
    },
    "WH": {  # 强麦
        "name": "强麦",
        "exchange": Exchange.CZCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.20,
        "rate": 0.0,
        "slippage": 30.0,
        "active_months": [1, 5, 9],
    },
    "PM": {  # 普麦
        "name": "普麦",
        "exchange": Exchange.CZCE,
        "size": 50,
        "pricetick": 1.0,
        "deposit_rate": 0.23,
        "rate": 0.0,
        "slippage": 30.0,
        "active_months": [1, 5, 9],
    },
    "RI": {  # 早籼稻
        "name": "早籼稻",
        "exchange": Exchange.CZCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.23,
        "rate": 0.0,
        "slippage": 2.5,
        "active_months": [1, 5, 9],
    },
    "LR": {  # 晚籼稻
        "name": "晚籼稻",
        "exchange": Exchange.CZCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.23,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 5, 9],
    },
    "JR": {  # 粳稻
        "name": "粳稻",
        "exchange": Exchange.CZCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.23,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 5, 9],
    },
    "SF": {  # 硅铁
        "name": "硅铁",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 2.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "SM": {  # 硅锰
        "name": "硅锰",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 2.0,
        "deposit_rate": 0.09,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "RS": {  # 菜籽
        "name": "菜籽",
        "exchange": Exchange.CZCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.20,
        "rate": 0.0,
        "slippage": 2.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "CY": {  # 棉纱
        "name": "棉纱",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.07,
        "rate": 0.0,
        "slippage": 1.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "AP": {  # 苹果
        "name": "苹果",
        "exchange": Exchange.CZCE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.10,
        "rate": 0.0,
        "slippage": 5.0,
        "active_months": [1, 3, 5, 10, 11],
    },
    "CJ": {  # 红枣
        "name": "红枣",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.15,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [1, 3, 5, 7, 9],
    },
    "UR": {  # 尿素
        "name": "尿素",
        "exchange": Exchange.CZCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.08,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 5, 9],
    },
    "SA": {  # 纯碱
        "name": "纯碱",
        "exchange": Exchange.CZCE,
        "size": 20,
        "pricetick": 1.0,
        "deposit_rate": 0.12,
        "rate": 0.0002,
        "slippage": 0,
        "active_months": [1, 5, 9],
    },
    "PF": {  # 短纤
        "name": "短纤",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 2.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 2.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "PK": {  # 花生
        "name": "花生",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 2.0,
        "deposit_rate": 0.08,
        "rate": 0.0,
        "slippage": 4.0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "PL": {  # 丙烯
        "name": "丙烯",
        "exchange": Exchange.CZCE,
        "size": 20,  # 5吨/手
        "pricetick": 1.0,  # 1元/吨
        "deposit_rate": 0.08,  # 8%保证金
        "rate": 0.0001,  # 手续费率
        "slippage": 0,  # 滑点
        "active_months": [1, 3, 5, 7, 9, 11],  # 保持活跃的月份数量
    },
    "PR": {  # 瓶片
        "name": "瓶片",
        "exchange": Exchange.CZCE,
        "size": 15,  # 5吨/手
        "pricetick": 2.0,  # 1元/吨
        "deposit_rate": 0.08,  # 8%保证金
        "rate": 0.00005,  # 手续费率
        "slippage": 0,  # 滑点
        "active_months": [1, 3, 5, 7, 9, 11],  # 保持活跃的月份数量
    },
    "SH": {  # 菜花
        "name": "菜花",
        "exchange": Exchange.CZCE,
        "size": 30,
        "pricetick": 1.0,
        "deposit_rate": 0.12,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 5, 9],
    },
    "PX": {  # 对二甲苯
        "name": "对二甲苯",
        "exchange": Exchange.CZCE,
        "size": 5,
        "pricetick": 2.0,
        "deposit_rate": 0.08,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "ZC": {  # 动力煤
        "name": "动力煤",
        "exchange": Exchange.CZCE,
        "size": 100,
        "pricetick": 0.2,
        "deposit_rate": 0.35,
        "rate": 0.0,
        "slippage": 150.0,
        "active_months": [1, 5, 9],
    },
    
    # 中金所品种 (CFFEX)
    "IF": {  # 沪深300股指期货
        "name": "沪深300股指",
        "exchange": Exchange.CFFEX,
        "size": 300,  # 300元/点
        "pricetick": 0.2,  # 0.2点
        "deposit_rate": 0.12,
        "rate": 0.0023,
        "slippage": 0,
        "active_months": [3, 6, 9, 12],
    },
    "IC": {  # 中证500股指期货
        "name": "中证500股指",
        "exchange": Exchange.CFFEX,
        "size": 200,
        "pricetick": 0.2,
        "deposit_rate": 0.15,
        "rate": 0.0023,
        "slippage": 0,
        "active_months": [3, 6, 9, 12],
    },
    "IH": {  # 上证50股指期货
        "name": "上证50股指",
        "exchange": Exchange.CFFEX,
        "size": 300,
        "pricetick": 0.2,
        "deposit_rate": 0.12,
        "rate": 0.0023,
        "slippage": 0,
        "active_months": [3, 6, 9, 12],
    },
    "IM": {  # 中证1000股指期货
        "name": "中证1000股指",
        "exchange": Exchange.CFFEX,
        "size": 200,
        "pricetick": 0.2,
        "deposit_rate": 0.15,
        "rate": 0.0023,
        "slippage": 0,
        "active_months": [3, 6, 9, 12],
    },
    "T": {  # 10年期国债期货
        "name": "10年期国债",
        "exchange": Exchange.CFFEX,
        "size": 10000,
        "pricetick": 0.005,
        "deposit_rate": 0.02,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [3, 6, 9, 12],
    },
    "TF": {  # 5年期国债期货
        "name": "5年期国债",
        "exchange": Exchange.CFFEX,
        "size": 10000,
        "pricetick": 0.005,
        "deposit_rate": 0.012,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [3, 6, 9, 12],
    },
    "TL": {  # 30年期国债期货
        "name": "30年期国债",
        "exchange": Exchange.CFFEX,
        "size": 10000,
        "pricetick": 0.01,
        "deposit_rate": 0.02,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [3, 6, 9, 12],
    },
    "TS": {  # 2年期国债期货
        "name": "2年期国债",
        "exchange": Exchange.CFFEX,
        "size": 20000,
        "pricetick": 0.002,
        "deposit_rate": 0.005,
        "rate": 0.0,
        "slippage": 3.0,
        "active_months": [3, 6, 9, 12],
    },
    
    # 上海国际能源交易中心 (INE)
    "sc": {  # 原油
        "name": "原油",
        "exchange": Exchange.INE,
        "size": 1000,
        "pricetick": 0.1,
        "deposit_rate": 0.10,
        "rate": 0.0,
        "slippage": 20.0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "lu": {  # 低硫燃料油
        "name": "低硫燃料油",
        "exchange": Exchange.INE,
        "size": 10,
        "pricetick": 1.0,
        "deposit_rate": 0.10,
        "rate": 0.00001,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "nr": {  # 20号胶
        "name": "20号胶",
        "exchange": Exchange.INE,
        "size": 10,
        "pricetick": 5.0,
        "deposit_rate": 0.08,
        "rate": 0.00002,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "bc": {  # 国际铜
        "name": "国际铜",
        "exchange": Exchange.INE,
        "size": 5,
        "pricetick": 10.0,
        "deposit_rate": 0.08,
        "rate": 0.00001,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    "ec": {  # 集运指数
        "name": "集运指数",
        "exchange": Exchange.INE,
        "size": 50,
        "pricetick": 0.1,
        "deposit_rate": 0.18,
        "rate": 0.0006,
        "slippage": 0,
        "active_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
    
    # 广州期货交易所 (GFEX)
    "si": {  # 工业硅
        "name": "工业硅",
        "exchange": Exchange.GFEX,
        "size": 5,
        "pricetick": 5.0,
        "deposit_rate": 0.08,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "lc": {  # 碳酸锂
        "name": "碳酸锂",
        "exchange": Exchange.GFEX,
        "size": 1,
        "pricetick": 20.0,
        "deposit_rate": 0.12,
        "rate": 0.00008,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
    "ps": {  # 聚苯乙烯
        "name": "聚苯乙烯",
        "exchange": Exchange.GFEX,
        "size": 3,
        "pricetick": 5.0,
        "deposit_rate": 0.09,
        "rate": 0.0001,
        "slippage": 0,
        "active_months": [1, 3, 5, 7, 9, 11],
    },
}


def get_futures_info(symbol: str) -> Dict[str, Any]:
    """获取期货品种信息"""
    return FUTURES_INFO.get(symbol, {})


def get_all_symbols() -> List[str]:
    """获取所有期货品种代码"""
    return list(FUTURES_INFO.keys())


def generate_contract_months(symbol: str, start_date: datetime = None) -> List[str]:
    """
    生成期货合约月份列表（基于active_months配置）
    
    Args:
        symbol: 期货品种代码
        start_date: 开始日期，默认为当前日期
    
    Returns:
        合约代码列表，如['rb2510', 'rb2601', 'rb2605']
    """
    if start_date is None:
        start_date = datetime.now()
    
    info = get_futures_info(symbol)
    if not info:
        return []
    
    # 获取该品种的活跃交易月份
    active_months = info.get("active_months", [1, 3, 5, 7, 9, 11])
    
    contracts = []
    current_year = start_date.year
    current_month = start_date.month
    
    # 从当前月份开始，找到下一个活跃月份
    found_contracts = 0
    max_contracts = min(len(active_months), 6)  # 最多6个合约
    
    # 向前查找24个月，确保能找到足够的合约
    for i in range(24):
        year = current_year + (current_month + i - 1) // 12
        month = (current_month + i - 1) % 12 + 1
        
        if month in active_months:
            # 生成合约代码：品种 + 年份后两位 + 月份（补零）
            year_suffix = str(year)[-2:]
            month_str = f"{month:02d}"
            contract = f"{symbol}{year_suffix}{month_str}"
            contracts.append(contract)
            found_contracts += 1
            
            if found_contracts >= max_contracts:
                break
    
    return contracts


def get_active_contracts(symbol: str, base_date: datetime = None) -> Dict[str, List[str]]:
    """
    获取需要下载数据的合约列表
    
    Args:
        symbol: 期货品种代码
        base_date: 基准日期
    
    Returns:
        包含不同类型合约的字典
    """
    if base_date is None:
        base_date = datetime.now()
    
    info = get_futures_info(symbol)
    if not info:
        return {}
    
    exchange_suffix = info["exchange"].value
    
    # 生成具体月份合约（基于active_months，最多6个）
    month_contracts = generate_contract_months(symbol, base_date)
    
    # 添加交易所后缀
    month_contracts_full = [f"{contract}.{exchange_suffix}" for contract in month_contracts]
    
    # 主连合约和加权合约
    continuous_contract = f"{symbol}9999.{exchange_suffix}"  # 主连合约
    weighted_contract = f"{symbol}8888.{exchange_suffix}"    # 加权合约
    
    return {
        "month_contracts": month_contracts_full,
        "continuous_contract": continuous_contract,
        "weighted_contract": weighted_contract,
        "all_contracts": month_contracts_full + [continuous_contract, weighted_contract]
    }


def get_priority_contracts(symbol: str, base_date: datetime = None) -> List[str]:
    """
    获取优先下载的合约列表（智能截断active_months）
    
    Args:
        symbol: 期货品种代码
        base_date: 基准日期
    
    Returns:
        优先合约列表
    """
    if base_date is None:
        base_date = datetime.now()
    
    info = get_futures_info(symbol)
    if not info:
        return []
    
    # 获取完整的active_months列表
    active_months = info.get("active_months", [1, 3, 5, 7, 9, 11])
    exchange_suffix = info["exchange"].value
    current_month = base_date.month
    current_year = base_date.year
    
    # CFFEX特殊处理：每次最多只下载2个未来合约
    if exchange_suffix == "CFFEX":
        contracts = []
        year = current_year
        
        # 找到接下来的2个活跃月份
        found_months = []
        
        # 从当前月份开始查找
        for i in range(24):  # 查找24个月内的合约
            check_month = (current_month + i) % 12
            if check_month == 0:
                check_month = 12
            
            check_year = current_year + (current_month + i - 1) // 12
            
            if check_month in active_months and len(found_months) < 2:
                # 跳过当前月份，只要未来的合约
                if check_year > current_year or check_month > current_month:
                    found_months.append((check_year, check_month))
        
        # 生成合约代码
        for year, month in found_months:
            year_suffix = str(year)[-2:]
            month_str = f"{month:02d}"
            future_contract = f"{symbol}{year_suffix}{month_str}.{exchange_suffix}"
            contracts.append(future_contract)
        
        # 添加主连和加权合约
        continuous_contract = f"{symbol}9999.{exchange_suffix}"
        weighted_contract = f"{symbol}8888.{exchange_suffix}"
        contracts.extend([continuous_contract, weighted_contract])
        
        return contracts
    
    # 其他交易所的原有逻辑
    # 智能截断逻辑：从下个月开始，选择连续的6个月
    if len(active_months) > 6:
        selected_months = []
        
        # 从下个月开始，按顺序选择6个月
        start_month = current_month + 1
        for i in range(6):
            target_month = start_month + i
            if target_month > 12:
                target_month = target_month - 12
            
            # 检查这个月份是否在active_months中
            if target_month in active_months:
                selected_months.append(target_month)
        
        # 如果选择的月份不够6个，继续从剩余的active_months中选择
        if len(selected_months) < 6:
            remaining_months = [m for m in active_months if m not in selected_months]
            needed = 6 - len(selected_months)
            selected_months.extend(remaining_months[:needed])
        
        active_months = selected_months
    
    # 生成合约代码
    contracts = []
    
    for month in active_months:
        # 确定年份：如果月份小于等于当前月份，则使用下一年
        if month <= current_month:
            year = current_year + 1
        else:
            year = current_year
        
        year_suffix = str(year)[-2:]
        month_str = f"{month:02d}"
        
        if exchange_suffix == "CZCE":
            # 郑商所格式：MA509 (5表示2025年，09表示9月)
            czce_year = str(year)[-1:]  # 取年份最后一位
            contract = f"{symbol}{czce_year}{month_str}.{exchange_suffix}"
        else:
            contract = f"{symbol}{year_suffix}{month_str}.{exchange_suffix}"
        
        contracts.append(contract)
    
    # 添加主连和加权合约
    continuous_contract = f"{symbol}9999.{exchange_suffix}"
    weighted_contract = f"{symbol}8888.{exchange_suffix}"
    
    contracts.extend([continuous_contract, weighted_contract])
    
    return contracts





if __name__ == "__main__":
    # 测试代码
    print("期货品种配置测试")
    print("=" * 50)
    
    # 测试螺纹钢
    symbol = "rb"
    info = get_futures_info(symbol)
    print(f"品种: {symbol} - {info.get('name', '未知')}")
    print(f"交易所: {info.get('exchange', '未知')}")
    print(f"合约乘数: {info.get('size', 0)}")
    print(f"最小变动价位: {info.get('pricetick', 0)}")
    
    # 测试合约生成
    contracts = get_active_contracts(symbol)
    print(f"\n月份合约: {contracts['month_contracts'][:5]}...")  # 只显示前5个
    print(f"主连合约: {contracts['continuous_contract']}")
    print(f"加权合约: {contracts['weighted_contract']}")
    
    # 测试优先合约
    priority = get_priority_contracts(symbol)
    print(f"\n优先下载合约: {priority}")
    
    # 测试CFFEX品种
    print("\n" + "=" * 50)
    print("CFFEX品种测试")
    
    cffex_symbols = ["IF", "IC", "IH", "IM", "T", "TF"]
    for cffex_symbol in cffex_symbols:
        info = get_futures_info(cffex_symbol)
        priority = get_priority_contracts(cffex_symbol)
        print(f"{cffex_symbol} ({info.get('name', '未知')}): {priority}")
        
        # 验证只有1个未来合约（除了主连和加权）
        future_contracts = [c for c in priority if not (c.endswith('9999.CFFEX') or c.endswith('8888.CFFEX'))]
        print(f"  -> 未来合约数量: {len(future_contracts)}")
        print()