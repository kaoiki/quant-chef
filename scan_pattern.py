#!/usr/bin/env python3
"""
A 股量化策略扫描脚本 — 三日低开高收抄底形态

策略逻辑:
  连续 3 个交易日:
    Day1: 阴线, 收盘 < 开盘, 实体较小
    Day2: 阴线, 收盘 < 开盘, 实体 > Day1 实体
    Day3: 阳线, 开盘 < Day2 收盘, 收盘 > 开盘, 收盘 > Day2 收盘

用法:
    # 完整扫描（需代理，扫描全部~5000只A股）
    export all_proxy=http://127.0.0.1:6478
    python scan_pattern.py

    # 快速测试（无需代理，扫描20只热门股）
    python scan_pattern.py --test
    python scan_pattern.py --test --days 90
"""

import sys
import os
import argparse
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import pandas as pd
from tqdm import tqdm

# 项目模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

from src.data.market import fetch_kline, HOT_STOCKS


# ── 配置 ──────────────────────────────────────────────

KLINE_DAYS = 120          # 每只股票获取多少天数据
SIGNAL_DAYS = 3           # 判断信号需要最近几个交易日
HOLD_DAYS = 10            # 信号成立后持有天数
OUTPUT_FILE = "scan_results.csv"
REQUEST_INTERVAL = 0.05   # 请求间隔（秒）


# ═══════════════════════════════════════════════════════
#  函数1: 获取 A 股股票列表
# ═══════════════════════════════════════════════════════

def get_stock_list() -> pd.DataFrame:
    """
    获取 A 股全部股票列表（AKShare 东方财富接口）

    返回:
        DataFrame，包含 'code'(代码) 和 'name'(名称) 两列
    """
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
                   use_sina: bool = False) -> Optional[pd.DataFrame]:
    """
    获取单只股票的日 K 线数据

    参数:
        symbol:   6位股票代码，如 "000001"
        days:     获取最近多少天的数据
        use_sina: True = Sina API（测试用, 无需代理）
                  False = AKShare（完整扫描用）

    返回:
        DataFrame: date/open/close/high/low/volume，按日期升序
        失败返回 None
    """
    try:
        if use_sina:
            # ── Sina API 模式 ──
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
            # ── AKShare 模式 ──
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

    参数:
        df: 日K线数据（按日期升序排列）

    返回:
        如果满足条件，返回包含信号详情的字典；否则返回 None
    """
    if df is None or len(df) < SIGNAL_DAYS:
        return None

    recent = df.tail(SIGNAL_DAYS).reset_index(drop=True)

    d1 = recent.iloc[0]  # Day 1（倒数第3天）
    d2 = recent.iloc[1]  # Day 2（倒数第2天）
    d3 = recent.iloc[2]  # Day 3（最后1天）

    o1, c1 = float(d1["open"]), float(d1["close"])
    o2, c2 = float(d2["open"]), float(d2["close"])
    o3, c3 = float(d3["open"]), float(d3["close"])

    body1 = o1 - c1   # Day1 阴线实体
    body2 = o2 - c2   # Day2 阴线实体

    # ── Day 1: 阴线 ──
    if c1 >= o1:
        return None
    if body1 <= 0:
        return None

    # ── Day 2: 阴线, 实体 > Day1 ──
    if c2 >= o2:
        return None
    if body2 <= body1:
        return None

    # ── Day 3: 阳线, 低开高收 ──
    if c3 <= o3:       # 必须阳线
        return None
    if o3 >= c2:       # 必须低开（开盘 < Day2收盘）
        return None
    if c3 <= c2:       # 必须收高（收盘 > Day2收盘）
        return None

    # ── 信号成立 ──
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
    use_sina: bool = False,
) -> List[Dict]:
    """
    遍历全部 A 股，筛选满足策略形态的股票

    参数:
        stock_list: 股票列表（含 code, name 列）
        days:       K线取数天数
        output_file: CSV 输出路径
        use_sina:   是否使用 Sina API

    返回:
        满足条件的股票信号列表
    """
    signals: List[Dict] = []
    total = len(stock_list)

    source = "Sina API" if use_sina else "AKShare (East Money)"
    print(f"\n🔍 开始扫描 {total} 只 A 股...")
    print(f"   数据源: {source}")
    print(f"   策略: 三日低开高收抄底形态")
    print(f"   K线窗口: {days} 天 | 判断最近 {SIGNAL_DAYS} 个交易日\n")

    progress = tqdm(
        stock_list.iterrows(),
        total=total,
        desc="扫描进度",
        ncols=80,
        unit="只",
    )

    for idx, row in progress:
        code = row["code"]
        name = row["name"]

        df = get_daily_data(code, days, use_sina=use_sina)
        if df is None or len(df) < SIGNAL_DAYS:
            continue

        signal = check_pattern(df)
        if signal is not None:
            signal["code"] = code
            signal["name"] = name
            signals.append(signal)
            progress.set_postfix_str(f"发现 {len(signals)} 个信号", refresh=False)

        time.sleep(REQUEST_INTERVAL)

    # ── 输出结果 ──
    if not signals:
        print("\n📭 未发现满足条件的股票")
        return []

    result_df = pd.DataFrame(signals)
    columns = [
        "code", "name", "signal_date",
        "day1_date", "day1_open", "day1_close", "day1_body",
        "day2_date", "day2_open", "day2_close", "day2_body",
        "day3_date", "day3_open", "day3_close",
    ]
    columns = [c for c in columns if c in result_df.columns]
    result_df = result_df[columns]

    result_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n📁 结果已保存到: {output_file}")
    print(f"\n{'='*60}")
    print(f"📊 共发现 {len(signals)} 个抄底信号!")
    print(f"{'='*60}")

    print_table(result_df)
    return signals


# ═══════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════

def print_table(df: pd.DataFrame):
    """在控制台打印格式化的结果表格"""
    print(f"\n{'代码':<8} {'名称':<8} {'信号日期':<12} "
          f"{'Day1实体':<8} {'Day2实体':<8} "
          f"{'Day3开盘':<10} {'Day3收盘':<10} {'Day3涨跌':<8}")
    print("-" * 75)
    for _, row in df.iterrows():
        day3_chg = round(row["day3_close"] - row["day2_close"], 2)
        print(f"{row['code']:<8} {row['name']:<8} {str(row['signal_date']):<12} "
              f"{row['day1_body']:<8.2f} {row['day2_body']:<8.2f} "
              f"{row['day3_open']:<10.2f} {row['day3_close']:<10.2f} "
              f"{day3_chg:<+8.2f}")


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="A股量化策略扫描 — 三日低开高收抄底形态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scan_pattern.py                       完整扫描（需代理）
  python scan_pattern.py --test                快速测试（无需代理）
  python scan_pattern.py --test --days 90      指定K线天数
  python scan_pattern.py --output my.csv       自定义输出路径
        """,
    )
    parser.add_argument("--days", type=int, default=KLINE_DAYS,
                        help=f"K线取数天数 (默认 {KLINE_DAYS})")
    parser.add_argument("--output", type=str, default=OUTPUT_FILE,
                        help=f"CSV 输出路径 (默认 {OUTPUT_FILE})")
    parser.add_argument("--interval", type=float, default=REQUEST_INTERVAL,
                        help=f"请求间隔秒数 (默认 {REQUEST_INTERVAL})")
    parser.add_argument("--test", action="store_true",
                        help="测试模式: 仅扫描 20 只热门股 (Sina API 无需代理)")

    args = parser.parse_args()
    start_time = time.time()

    if args.test:
        # ── 测试模式: Sina API + 热门股票 ──
        print("🧪 测试模式: 使用 Sina API 扫描 20 只热门 A 股")
        print("   完整扫描请运行: python scan_pattern.py (需开启代理)\n")
        stock_data = [{"code": c, "name": n} for c, n, _ in HOT_STOCKS]
        stock_list = pd.DataFrame(stock_data)
        sina_mode = True
    else:
        # ── 完整模式: AKShare 东方财富接口 ──
        if not HAS_AKSHARE:
            print("[错误] 未安装 akshare，完整扫描不可用")
            sys.exit(1)
        print("📋 正在获取 A 股股票列表...")
        stock_list = get_stock_list()
        print(f"   共 {len(stock_list)} 只股票\n")
        sina_mode = False

    # 扫描信号
    signals = scan_all_stocks(
        stock_list=stock_list,
        days=args.days,
        output_file=args.output,
        use_sina=sina_mode,
    )

    elapsed = time.time() - start_time
    print(f"\n⏱  总耗时: {elapsed:.1f} 秒")

    if signals:
        print(f"\n💡 提示: 信号出现后持有 {HOLD_DAYS} 个交易日为默认持有规则")
        print(f"   结果已保存至: {args.output}")


if __name__ == "__main__":
    main()
