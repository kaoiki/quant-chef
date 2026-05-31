#!/usr/bin/env python3
"""
A 股量化策略扫描脚本 — 三日低开高收抄底形态

策略逻辑:
  连续 3 个交易日:
    Day1: 阴线, 收盘 < 开盘, 实体较小
    Day2: 阴线, 收盘 < 开盘, 实体 > Day1 实体
    Day3: 阳线, 开盘 < Day2 收盘, 收盘 > 开盘, 收盘 > Day2 收盘

用法:
    # 默认: Sina API 扫描全部A股（无需代理, 推荐）
    python scan_pattern.py

    # AKShare 模式（需开 proxy）
    python scan_pattern.py --mode akshare

    # 自定义参数
    python scan_pattern.py --days 90 --output my.csv
"""

import sys
import os
import argparse
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import pandas as pd
import requests
from tqdm import tqdm

# 项目模块路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

from src.data.market import fetch_kline


# ── 配置 ──────────────────────────────────────────────

KLINE_DAYS = 120          # 每只股票获取多少天数据
SIGNAL_DAYS = 3           # 判断信号需要最近几个交易日
HOLD_DAYS = 10            # 信号成立后持有天数
OUTPUT_FILE = "scan_results.csv"
REQUEST_INTERVAL = 0.03   # 请求间隔（秒）

SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}


# ═══════════════════════════════════════════════════════
#  函数1: 获取 A 股股票列表
# ═══════════════════════════════════════════════════════

def get_stock_list(use_sina: bool = True) -> pd.DataFrame:
    """
    获取 A 股全部股票列表

    参数:
        use_sina: True = Sina API（无需代理，推荐）
                  False = AKShare 东方财富（需代理）

    返回:
        DataFrame，包含 'code'(代码) 和 'name'(名称) 两列
    """
    if use_sina:
        return _get_stock_list_sina()
    else:
        return _get_stock_list_akshare()


def _get_stock_list_sina() -> pd.DataFrame:
    """通过 Sina API 获取全 A 股列表（无需代理，分页拉取）"""
    base_url = ("https://vip.stock.finance.sina.com.cn/quotes_service"
                "/api/json_v2.php/Market_Center.getHQNodeData")
    page = 1
    all_data = []
    print("   正在拉取 Sina 股票列表...", end="", flush=True)

    while True:
        try:
            url = (f"{base_url}?page={page}&num=100&sort=symbol"
                   f"&asc=1&node=hs_a&symbol=&_=1")
            resp = requests.get(url, headers=SINA_HEADERS, timeout=10)
            data = resp.json()
            if not data:
                break
            for item in data:
                code = item.get("code", "")
                name = item.get("name", "")
                if code and name:
                    all_data.append({"code": code, "name": name})
            page += 1
            if page % 10 == 0:
                print(f" {page*100}...", end="", flush=True)
        except Exception:
            break

    print(f" 共 {len(all_data)} 只")
    if not all_data:
        print("[错误] 无法从 Sina API 获取股票列表")
        sys.exit(1)

    result = pd.DataFrame(all_data)
    result["code"] = result["code"].astype(str).str.zfill(6)
    return result


def _get_stock_list_akshare() -> pd.DataFrame:
    """通过 AKShare 获取全 A 股列表（需代理）"""
    try:
        df = ak.stock_zh_a_spot_em()
        result = df[["代码", "名称"]].copy()
        result.columns = ["code", "name"]
        result["code"] = result["code"].astype(str).str.zfill(6)
        return result
    except Exception as e:
        print(f"[错误] 获取股票列表失败: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════
#  函数2: 获取单只股票日 K 线数据
# ═══════════════════════════════════════════════════════

def get_daily_data(symbol: str, days: int = KLINE_DAYS,
                   use_sina: bool = True) -> Optional[pd.DataFrame]:
    """
    获取单只股票的日 K 线数据

    参数:
        symbol:   6位股票代码
        days:     获取最近多少天的数据
        use_sina: True = Sina API（无需代理）, False = AKShare

    返回:
        DataFrame: date/open/close/high/low/volume，按日期升序
    """
    try:
        if use_sina:
            klines = fetch_kline(symbol, days)
            if not klines or len(klines) < SIGNAL_DAYS:
                return None
            records = [{
                "date": pd.to_datetime(d["day"]),
                "open": float(d["open"]),
                "close": float(d["close"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "volume": float(d["volume"]),
            } for d in klines]
            df = pd.DataFrame(records)
            return df.sort_values("date").reset_index(drop=True)
        else:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq",
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
            })
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)[
                ["date", "open", "close", "high", "low", "volume"]
            ]
    except Exception:
        return None


# ═══════════════════════════════════════════════════════
#  函数3: 判断是否满足三日低开高收抄底形态
# ═══════════════════════════════════════════════════════

def check_pattern(df: pd.DataFrame) -> Optional[Dict]:
    """
    检查最近 SIGNAL_DAYS 个交易日是否满足策略形态

    返回: 满足返回信号字典, 否则 None
    """
    if df is None or len(df) < SIGNAL_DAYS:
        return None

    recent = df.tail(SIGNAL_DAYS).reset_index(drop=True)
    d1, d2, d3 = recent.iloc[0], recent.iloc[1], recent.iloc[2]

    o1, c1 = float(d1["open"]), float(d1["close"])
    o2, c2 = float(d2["open"]), float(d2["close"])
    o3, c3 = float(d3["open"]), float(d3["close"])

    body1, body2 = o1 - c1, o2 - c2

    # Day 1: 阴线
    if c1 >= o1 or body1 <= 0:
        return None
    # Day 2: 阴线, 实体 > Day1
    if c2 >= o2 or body2 <= body1:
        return None
    # Day 3: 阳线, 低开, 收高于 Day2
    if c3 <= o3 or o3 >= c2 or c3 <= c2:
        return None

    return {
        "code":         d1.get("股票代码", ""),
        "name":         "",
        "signal_date":  d3["date"].strftime("%Y-%m-%d"),
        "day1_date":    d1["date"].strftime("%Y-%m-%d"),
        "day1_open":    round(o1, 2),
        "day1_close":   round(c1, 2),
        "day1_body":    round(body1, 2),
        "day2_date":    d2["date"].strftime("%Y-%m-%d"),
        "day2_open":    round(o2, 2),
        "day2_close":   round(c2, 2),
        "day2_body":    round(body2, 2),
        "day3_date":    d3["date"].strftime("%Y-%m-%d"),
        "day3_open":    round(o3, 2),
        "day3_close":   round(c3, 2),
    }


# ═══════════════════════════════════════════════════════
#  函数4: 扫描全部股票
# ═══════════════════════════════════════════════════════

def scan_all_stocks(
    stock_list: pd.DataFrame,
    days: int = KLINE_DAYS,
    output_file: str = OUTPUT_FILE,
    use_sina: bool = True,
) -> List[Dict]:
    """遍历全部 A 股，筛选满足策略形态的股票"""
    signals: List[Dict] = []
    total = len(stock_list)
    source = "Sina API" if use_sina else "AKShare"
    kline_source = "Sina" if use_sina else "East Money"

    print(f"\n🔍 开始扫描 {total} 只 A 股...")
    print(f"   数据源: {source} | K线: {kline_source}")
    print(f"   策略: 三日低开高收抄底形态")
    print(f"   K线窗口: {days} 天 | 判断最近 {SIGNAL_DAYS} 个交易日\n")

    progress = tqdm(stock_list.iterrows(), total=total,
                    desc="扫描进度", ncols=80, unit="只")

    for idx, row in progress:
        df = get_daily_data(row["code"], days, use_sina=use_sina)
        if df is None or len(df) < SIGNAL_DAYS:
            continue
        signal = check_pattern(df)
        if signal is not None:
            signal["code"] = row["code"]
            signal["name"] = row["name"]
            signals.append(signal)
            progress.set_postfix_str(f"发现 {len(signals)} 个信号", refresh=False)
        time.sleep(REQUEST_INTERVAL)

    if not signals:
        print("\n📭 未发现满足条件的股票")
        return []

    result_df = pd.DataFrame(signals)
    cols = ["code", "name", "signal_date",
            "day1_date", "day1_open", "day1_close", "day1_body",
            "day2_date", "day2_open", "day2_close", "day2_body",
            "day3_date", "day3_open", "day3_close"]
    cols = [c for c in cols if c in result_df.columns]
    result_df = result_df[cols]

    result_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n📁 结果已保存到: {output_file}")
    print(f"\n{'='*60}")
    print(f"📊 共发现 {len(signals)} 个抄底信号!")
    print(f"{'='*60}")

    print(f"\n{'代码':<8} {'名称':<8} {'信号日期':<12} "
          f"{'Day1实体':<8} {'Day2实体':<8} "
          f"{'Day3开盘':<10} {'Day3收盘':<10} {'Day3涨跌':<8}")
    print("-" * 75)
    for _, row in result_df.iterrows():
        chg = round(row["day3_close"] - row["day2_close"], 2)
        print(f"{row['code']:<8} {row['name']:<8} {str(row['signal_date']):<12} "
              f"{row['day1_body']:<8.2f} {row['day2_body']:<8.2f} "
              f"{row['day3_open']:<10.2f} {row['day3_close']:<10.2f} "
              f"{chg:<+8.2f}")

    return signals


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="A股量化策略扫描 — 三日低开高收抄底形态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scan_pattern.py                     Sina 模式（无需代理, 推荐）
  python scan_pattern.py --mode akshare      AKShare 模式（需 proxy）
  python scan_pattern.py --days 90           自定义K线天数
  python scan_pattern.py --output my.csv     自定义输出路径
        """,
    )
    parser.add_argument("--days", type=int, default=KLINE_DAYS,
                        help=f"K线取数天数 (默认 {KLINE_DAYS})")
    parser.add_argument("--output", type=str, default=OUTPUT_FILE,
                        help=f"CSV 输出路径 (默认 {OUTPUT_FILE})")
    parser.add_argument("--interval", type=float, default=REQUEST_INTERVAL,
                        help=f"请求间隔秒数 (默认 {REQUEST_INTERVAL})")
    parser.add_argument("--mode", choices=["sina", "akshare"], default="sina",
                        help="数据源: sina(默认,无需代理) / akshare(需代理)")

    args = parser.parse_args()
    start_time = time.time()

    use_sina = args.mode == "sina"
    print("📋 正在获取 A 股股票列表...")
    stock_list = get_stock_list(use_sina=use_sina)
    print(f"   共 {len(stock_list)} 只股票\n")

    scan_all_stocks(
        stock_list=stock_list,
        days=args.days,
        output_file=args.output,
        use_sina=use_sina,
    )

    elapsed = time.time() - start_time
    print(f"\n⏱  总耗时: {elapsed:.1f} 秒")
    print(f"💡 提示: 信号出现后可持有 {HOLD_DAYS} 个交易日")


if __name__ == "__main__":
    main()
