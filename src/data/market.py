"""
市场数据获取层
基于新浪财经 API，稳定可靠，无需代理
"""

import json
import re
from typing import Optional, List, Dict, Any

import requests

# ── 基础配置 ──────────────────────────────────────────
HEADERS = {"Referer": "https://finance.sina.com.cn"}
TIMEOUT = 10

# 交易所前缀映射: 6位代码 → 新浪前缀
def _code_to_prefix(code: str) -> str:
    """根据股票代码确定交易所前缀"""
    code = code.strip()
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith(("0", "3", "2")):
        return "sz"
    elif code.startswith(("4", "8")):
        return "bj"
    return "sh"


def _to_sina_symbol(code: str) -> str:
    return f"{_code_to_prefix(code)}{code}"


def _to_sina_kline_symbol(code: str) -> str:
    """新浪K线接口使用的符号: sz000001 / sh600519"""
    prefix = _code_to_prefix(code)
    return f"{prefix}{code}"


# ── 实时行情 ──────────────────────────────────────────

SINA_REALTIME_FIELDS = [
    "名称", "今开", "昨收", "当前价", "最高", "最低",
    "买一价", "卖一价", "成交量", "成交额",
    "买一量", "买一价2", "买二量", "买二价", "买三量", "买三价",
    "买四量", "买四价", "买五量", "买五价",
    "卖一量", "卖一价2", "卖二量", "卖二价", "卖三量", "卖三价",
    "卖四量", "卖四价", "卖五量", "卖五价",
    "日期", "时间", "状态",
]


def fetch_quotes(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    批量获取实时行情

    返回: { "000001": { "名称": ..., "当前价": ..., "涨跌幅": ..., ... }, ... }
    """
    symbols = ",".join(_to_sina_symbol(c) for c in codes)
    url = f"https://hq.sinajs.cn/list={symbols}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = "gbk"
    except Exception as e:
        return {c: {"_error": str(e)} for c in codes}

    result = {}
    # 解析: var hq_str_sz000001="...";
    for line in resp.text.strip().split("\n"):
        m = re.match(r'var hq_str_\w+="(.*)";', line.strip())
        if not m:
            continue
        parts = m.group(1).split(",")
        if len(parts) < 6:
            continue

        # 从第一个字段取代码
        raw_symbol = re.search(r"hq_str_(\w+)=", line)
        code = raw_symbol.group(1)[2:] if raw_symbol else ""

        name = parts[0]
        current_str = parts[3]  # 当前价
        yesterday_close_str = parts[2]  # 昨收
        open_str = parts[1]
        high_str = parts[4]
        low_str = parts[5]
        volume_str = parts[8]   # 成交量（股）
        amount_str = parts[9]   # 成交额（元）
        date_str = parts[30] if len(parts) > 30 else ""
        time_str = parts[31] if len(parts) > 31 else ""

        # 转为浮点数
        def safe_float(v, default=0.0):
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        current = safe_float(current_str)
        yesterday_close = safe_float(yesterday_close_str)
        high = safe_float(high_str)
        low = safe_float(low_str)
        open_price = safe_float(open_str)

        # 计算涨跌幅
        if yesterday_close and yesterday_close != 0:
            change_pct = (current - yesterday_close) / yesterday_close * 100
            change = current - yesterday_close
        else:
            change_pct = 0.0
            change = 0.0

        result[code] = {
            "代码": code,
            "名称": name,
            "当前价": current,
            "昨收": yesterday_close,
            "今开": open_price,
            "最高": high,
            "最低": low,
            "涨跌额": round(change, 2),
            "涨跌幅": round(change_pct, 2),
            "成交量": int(safe_float(volume_str)),
            "成交额": safe_float(amount_str),
            "日期": date_str,
            "时间": time_str,
        }
    return result


def fetch_quote(code: str) -> Dict[str, Any]:
    """获取单只股票的实时行情"""
    result = fetch_quotes([code])
    return result.get(code, {})


# ── K线历史数据 ───────────────────────────────────────

def fetch_kline(code: str, datalen: int = 120) -> List[Dict[str, Any]]:
    """
    获取日K线数据（新浪接口）

    参数:
        code: 股票代码，如 "000001"
        datalen: 数据条数（最大约 2400）

    返回: [{ "day": "2026-05-29", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ... }, ...]
    """
    symbol = _to_sina_kline_symbol(code)
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
        "/CN_MarketData.getKLineData"
        f"?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        data = resp.json()
        for d in data:
            for k in ("open", "high", "low", "close", "volume"):
                d[k] = float(d.get(k, 0))
        return data
    except Exception as e:
        return [{"_error": str(e)}]


# ── 板块排行（用于首页推荐）─────────────────────────

# 预设一批热门股票及其分类
HOT_STOCKS = [
    # (代码, 名称, 板块)
    ("000001", "平安银行", "银行"),
    ("600519", "贵州茅台", "消费"),
    ("300750", "宁德时代", "新能源"),
    ("688981", "中芯国际", "半导体"),
    ("000858", "五粮液", "消费"),
    ("601318", "中国平安", "保险"),
    ("600036", "招商银行", "银行"),
    ("000333", "美的集团", "家电"),
    ("002415", "海康威视", "科技"),
    ("601012", "隆基绿能", "新能源"),
    ("600276", "恒瑞医药", "医药"),
    ("300059", "东方财富", "金融"),
    ("600900", "长江电力", "公用事业"),
    ("002594", "比亚迪", "新能源"),
    ("688111", "金山办公", "软件"),
    ("601899", "紫金矿业", "有色"),
    ("600030", "中信证券", "券商"),
    ("002714", "牧原股份", "农牧"),
    ("000725", "京东方A", "电子"),
    ("600887", "伊利股份", "消费"),
]
