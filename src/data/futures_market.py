"""
期货市场数据获取层
实时行情: 新浪财经 API
K线历史: AKShare (新浪源)
"""

import re
from typing import List, Dict, Any, Optional, Tuple

import requests
import akshare as ak

HEADERS = {"Referer": "https://finance.sina.com.cn"}
TIMEOUT = 10

# Sina 期货连续合约代码表
# symbol → (代码, 名称, 交易所, 板块)
FUTURES_CONTRACTS: List[Tuple[str, str, str, str]] = [
    ("RB0",   "螺纹钢", "上期所", "黑色系"),
    ("HC0",   "热卷",   "上期所", "黑色系"),
    ("I0",    "铁矿石", "大商所", "黑色系"),
    ("JM0",   "焦煤",   "大商所", "黑色系"),
    ("J0",    "焦炭",   "大商所", "黑色系"),
    ("CU0",   "铜",     "上期所", "有色"),
    ("AL0",   "铝",     "上期所", "有色"),
    ("ZN0",   "锌",     "上期所", "有色"),
    ("PB0",   "铅",     "上期所", "有色"),
    ("NI0",   "镍",     "上期所", "有色"),
    ("SN0",   "锡",     "上期所", "有色"),
    ("AU0",   "黄金",   "上期所", "贵金属"),
    ("AG0",   "白银",   "上期所", "贵金属"),
    ("SC0",   "原油",   "上期能源", "能源"),
    ("FU0",   "燃料油", "上期所", "能源"),
    ("BU0",   "沥青",   "上期所", "能源"),
    ("M0",    "豆粕",   "大商所", "农产品"),
    ("Y0",    "豆油",   "大商所", "农产品"),
    ("P0",    "棕榈油", "大商所", "农产品"),
    ("A0",    "豆一",   "大商所", "农产品"),
    ("B0",    "豆二",   "大商所", "农产品"),
    ("C0",    "玉米",   "大商所", "农产品"),
    ("CS0",   "淀粉",   "大商所", "农产品"),
    ("CF0",   "棉花",   "郑商所", "农产品"),
    ("SR0",   "白糖",   "郑商所", "农产品"),
    ("OI0",   "菜油",   "郑商所", "农产品"),
    ("RM0",   "菜粕",   "郑商所", "农产品"),
    ("TA0",   "PTA",    "郑商所", "化工"),
    ("MA0",   "甲醇",   "郑商所", "化工"),
    ("V0",    "PVC",    "大商所", "化工"),
    ("L0",    "塑料",   "大商所", "化工"),
    ("PP0",   "聚丙烯", "大商所", "化工"),
    ("EB0",   "苯乙烯", "大商所", "化工"),
    ("FG0",   "玻璃",   "郑商所", "建材"),
    ("SA0",   "纯碱",   "郑商所", "化工"),
    ("UR0",   "尿素",   "郑商所", "化工"),
    ("ZC0",   "动力煤", "郑商所", "能源"),
    ("SP0",   "纸浆",   "上期所", "建材"),
    ("RU0",   "橡胶",   "上期所", "化工"),
    ("SS0",   "不锈钢", "上期所", "黑色系"),
]

# 按板块索引
FUTURES_BY_SECTOR: Dict[str, List[Tuple[str, str, str]]] = {}
for sym, name, exch, sector in FUTURES_CONTRACTS:
    FUTURES_BY_SECTOR.setdefault(sector, []).append((sym, name, exch))


def _parse_futures_realtime(line: str) -> Optional[Dict[str, Any]]:
    """解析新浪期货实时行情的一行数据"""
    m = re.match(r'var hq_str_(\w+)="(.*)";', line.strip())
    if not m:
        return None

    parts = m.group(2).split(",")
    if len(parts) < 18:
        return None

    def sf(v, default=0.0):
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    name = parts[0]
    symbol = m.group(1).replace("nf_", "")
    open_price = sf(parts[2])
    last_settle = sf(parts[3])
    current = sf(parts[4])
    volume = sf(parts[13])
    hold = sf(parts[14])
    exchange = parts[15] if len(parts) > 15 else ""
    variety = parts[16] if len(parts) > 16 else ""
    date_str = parts[17] if len(parts) > 17 else ""
    settle = sf(parts[10]) if len(parts) > 10 else 0.0

    # 涨跌幅
    if last_settle and last_settle != 0:
        change_pct = (current - last_settle) / last_settle * 100
        change = current - last_settle
    else:
        change_pct = 0.0
        change = 0.0

    return {
        "代码": symbol,
        "名称": name.replace("连续", "").strip(),
        "品种": variety,
        "交易所": exchange,
        "最新价": current,
        "今开": open_price,
        "昨结算": last_settle,
        "涨跌幅": round(change_pct, 2),
        "涨跌额": round(change, 2),
        "成交量": int(volume),
        "持仓量": int(hold),
        "结算价": settle,
        "日期": date_str,
    }


def fetch_futures_quotes(symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """
    批量获取期货实时行情

    参数:
        symbols: 新浪代码列表，如 ['RB0', 'CU0']，None=全部

    返回: { 'RB0': { '名称': ..., '最新价': ..., ... }, ... }
    """
    if symbols is None:
        symbols = [s[0] for s in FUTURES_CONTRACTS]

    # 分批请求，每批最多30个
    results: Dict[str, Dict[str, Any]] = {}
    batch_size = 30
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        nf_codes = ",".join(f"nf_{s}" for s in batch)
        url = f"https://hq.sinajs.cn/list={nf_codes}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.encoding = "gbk"
            for line in resp.text.strip().split("\n"):
                parsed = _parse_futures_realtime(line)
                if parsed:
                    results[parsed["代码"]] = parsed
        except Exception as e:
            for sym in batch:
                results[sym] = {"_error": str(e)}

    return results


def fetch_futures_quote(symbol: str) -> Dict[str, Any]:
    """获取单个期货品种实时行情"""
    result = fetch_futures_quotes([symbol])
    return result.get(symbol, {})


def fetch_futures_kline(symbol: str, datalen: int = 90) -> List[Dict[str, Any]]:
    """
    获取期货日K线数据 (通过AKShare新浪源)

    参数:
        symbol: 新浪代码如 'RB0'
        datalen: 数据条数

    返回: [{ 'day': '2026-05-29', 'open': ..., 'high': ..., 'low': ..., 'close': ..., 'volume': ..., 'hold': ... }, ...]
    """
    try:
        df = ak.futures_main_sina(symbol=symbol)
        if df is None or df.empty:
            return []

        # 转成统一格式
        result = []
        for _, row in df.iterrows():
            result.append({
                "day": str(row["日期"]),
                "open": float(row["开盘价"]),
                "high": float(row["最高价"]),
                "low": float(row["最低价"]),
                "close": float(row["收盘价"]),
                "volume": float(row["成交量"]),
                "hold": float(row["持仓量"]),
                "settle": float(row["动态结算价"]),
            })
        return result[-datalen:]  # 只取最近 N 条
    except Exception as e:
        return [{"_error": str(e)}]


# 按板块组织的热门品种（用于 TUI 列表展示）
HOT_FUTURES_SECTORS = [
    ("贵金属", ["AU0", "AG0"]),
    ("黑色系", ["RB0", "HC0", "I0", "JM0", "J0"]),
    ("有色",   ["CU0", "AL0", "ZN0", "NI0"]),
    ("能源",   ["SC0", "FU0", "BU0"]),
    ("农产品", ["M0", "Y0", "P0", "CF0", "SR0", "C0"]),
    ("化工",   ["TA0", "MA0", "V0", "PP0", "SA0"]),
]
