"""
AKShare 数据加载封装层
提供统一的数据获取接口，后续可扩展缓存、重试等功能
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta


def get_stock_daily(symbol: str, start_date: str = None, end_date: str = None, adjust: str = "qfq") -> pd.DataFrame:
    """
    获取A股日线行情

    参数:
        symbol: 股票代码，如 "000001"
        start_date: 开始日期 "YYYYMMDD"，默认一年前
        end_date: 结束日期 "YYYYMMDD"，默认今天
        adjust: 复权类型 "qfq"(前复权) "hfq"(后复权) ""(不复权)
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    return ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )


def list_all_stock_codes() -> pd.DataFrame:
    """获取所有A股股票代码列表"""
    return ak.stock_zh_a_spot_em()


def get_index_component(index_code: str = "000300") -> pd.DataFrame:
    """获取指数成分股，默认沪深300"""
    return ak.index_stock_cons(symbol=index_code)
