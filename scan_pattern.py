#!/usr/bin/env python3
"""
A 股量化策略扫描脚本 — 三日低开高收抄底形态

策略逻辑:
  连续 3 个交易日:
    Day1: 阴线, 收盘 < 开盘, 实体较小
    Day2: 阴线, 收盘 < 开盘, 实体 > Day1 实体
    Day3: 阳线, 开盘 < Day2 收盘, 收盘 > 开盘, 收盘 > Day2 收盘

用法:
    conda activate quant-chef
    export all_proxy=http://127.0.0.1:6478   # 如需代理
    python scan_pattern.py
    python scan_pattern.py --days 120        # 自定义K线取数天数
    python scan_pattern.py --output results.csv
"""

import sys
import os
import argparse
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import pandas as pd
import akshare as ak
from tqdm import tqdm


# ── 配置 ──────────────────────────────────────────────

# K线数据参数
KLINE_DAYS = 120          # 每只股票获取多少天数据
SIGNAL_DAYS = 3           # 判断信号需要最近几个交易日
HOLD_DAYS = 10            # 信号成立后持有天数

# 输出
OUTPUT_FILE = "scan_results.csv"

# 请求间隔（秒），避免被限速
REQUEST_INTERVAL = 0.05


# ═══════════════════════════════════════════════════════
#  函数1: 获取 A 股股票列表
# ═══════════════════════════════════════════════════════

def get_stock_list() -> pd.DataFrame:
    """
    获取 A 股全部股票列表

    返回:
        DataFrame，包含 'code'(代码) 和 'name'(名称) 两列
    """
    try:
        # stock_zh_a_spot_em 返回所有 A 股实时行情，含代码和名称
        df = ak.stock_zh_a_spot_em()
        # 选取需要的列并重命名
        result = df[["代码", "名称"]].copy()
        result.columns = ["code", "name"]
        # 统一代码为6位字符串
        result["code"] = result["code"].astype(str).str.zfill(6)
        return result
    except Exception as e:
        print(f"[错误] 获取股票列表失败: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════
#  函数2: 获取单只股票日 K 线数据
# ═══════════════════════════════════════════════════════

def get_daily_data(symbol: str, days: int = KLINE_DAYS) -> Optional[pd.DataFrame]:
    """
    获取单只股票的日 K 线数据

    参数:
        symbol: 6位股票代码，如 "000001"
        days:   获取最近多少天的数据

    返回:
        DataFrame 包含日期/开盘/收盘/最高/最低，按日期升序排列
        失败返回 None
    """
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",           # 前复权
        )

        if df is None or df.empty:
            return None

        # 重命名列为英文，方便后续处理
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
        })

        # 日期升序排列
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        # 只保留需要的列
        return df[["date", "open", "close", "high", "low", "volume"]]

    except Exception as e:
        # 静默失败，调用方处理
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
        如果满足条件，返回包含信号详情的字典
        否则返回 None
    """
    if df is None or len(df) < SIGNAL_DAYS:
        return None

    # 取最近 SIGNAL_DAYS 天
    recent = df.tail(SIGNAL_DAYS).reset_index(drop=True)

    d1 = recent.iloc[0]  # Day 1（倒数第3天）
    d2 = recent.iloc[1]  # Day 2（倒数第2天）
    d3 = recent.iloc[2]  # Day 3（最后1天）

    o1, c1 = float(d1["open"]), float(d1["close"])
    o2, c2 = float(d2["open"]), float(d2["close"])
    o3, c3 = float(d3["open"]), float(d3["close"])

    # ── 条件判断 ──

    body1 = o1 - c1  # 阴线: 实体 = 开盘 - 收盘
    body2 = o2 - c2
    body3 = c3 - o3  # 阳线: 实体 = 收盘 - 开盘

    # Day 1: 阴线, 收盘 < 开盘, 实体 > 0
    if c1 >= o1:
        return None
    if body1 <= 0:
        return None

    # Day 2: 阴线, 收盘 < 开盘, 实体 > Day1 实体
    if c2 >= o2:
        return None
    if body2 <= body1:
        return None

    # Day 3: 阳线, 收盘 > 开盘
    if c3 <= o3:
        return None
    # Day 3: 开盘 < Day2 收盘（低开）
    if o3 >= c2:
        return None
    # Day 3: 收盘 > Day2 收盘（收高）
    if c3 <= c2:
        return None

    # ── 信号成立 ──
    return {
        "code":     d1.get("股票代码", ""),
        "name":     "",  # 由调用方填充
        "signal_date": d3["date"].strftime("%Y-%m-%d"),

        "day1_date":  d1["date"].strftime("%Y-%m-%d"),
        "day1_open":  round(o1, 2),
        "day1_close": round(c1, 2),
        "day1_body":  round(body1, 2),

        "day2_date":  d2["date"].strftime("%Y-%m-%d"),
        "day2_open":  round(o2, 2),
        "day2_close": round(c2, 2),
        "day2_body":  round(body2, 2),

        "day3_date":  d3["date"].strftime("%Y-%m-%d"),
        "day3_open":  round(o3, 2),
        "day3_close": round(c3, 2),
    }


# ═══════════════════════════════════════════════════════
#  函数4: 扫描全部股票
# ═══════════════════════════════════════════════════════

def scan_all_stocks(
    stock_list: pd.DataFrame,
    days: int = KLINE_DAYS,
    output_file: str = OUTPUT_FILE,
) -> List[Dict]:
    """
    遍历全部 A 股，筛选满足策略形态的股票

    参数:
        stock_list: 股票列表（含 code, name 列）
        days:       K线取数天数
        output_file: CSV 输出路径

    返回:
        满足条件的股票信号列表
    """
    signals = []
    total = len(stock_list)

    print(f"\n🔍 开始扫描 {total} 只 A 股...")
    print(f"   策略: 三日低开高收抄底形态")
    print(f"   K线窗口: {days} 天 | 判断最近 {SIGNAL_DAYS} 个交易日\n")

    # 创建进度条
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

        # 获取K线数据
        df = get_daily_data(code, days)

        if df is None or len(df) < SIGNAL_DAYS:
            continue

        # 判断形态
        signal = check_pattern(df)
        if signal is not None:
            signal["code"] = code
            signal["name"] = name
            signals.append(signal)

            # 进度条上显示发现的信号
            progress.set_postfix_str(f"发现 {len(signals)} 个信号", refresh=False)

        # 请求间隔，避免触发限速
        time.sleep(REQUEST_INTERVAL)

    # ── 输出结果 ──

    if not signals:
        print("\n📭 未发现满足条件的股票")
        return []

    # 转 DataFrame
    result_df = pd.DataFrame(signals)

    # 调整列顺序
    columns = [
        "code", "name", "signal_date",
        "day1_date", "day1_open", "day1_close", "day1_body",
        "day2_date", "day2_open", "day2_close", "day2_body",
        "day3_date", "day3_open", "day3_close",
    ]
    # 只保留存在的列
    columns = [c for c in columns if c in result_df.columns]
    result_df = result_df[columns]

    # 保存 CSV
    result_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n📁 结果已保存到: {output_file}")
    print(f"\n{'='*60}")
    print(f"📊 共发现 {len(signals)} 个抄底信号!")
    print(f"{'='*60}")

    # 控制台打印
    print_table(result_df)

    return signals


# ═══════════════════════════════════════════════════════
#  辅助函数: 打印结果表格
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
    )
    parser.add_argument(
        "--days", type=int, default=KLINE_DAYS,
        help=f"K线取数天数 (默认 {KLINE_DAYS})",
    )
    parser.add_argument(
        "--output", type=str, default=OUTPUT_FILE,
        help=f"CSV 输出路径 (默认 {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--interval", type=float, default=REQUEST_INTERVAL,
        help=f"请求间隔秒数 (默认 {REQUEST_INTERVAL})",
    )

    args = parser.parse_args()

    start_time = time.time()

    # 1. 获取股票列表
    print("📋 正在获取 A 股股票列表...")
    stock_list = get_stock_list()
    print(f"   共 {len(stock_list)} 只股票\n")

    # 2. 扫描信号
    signals = scan_all_stocks(
        stock_list=stock_list,
        days=args.days,
        output_file=args.output,
    )

    elapsed = time.time() - start_time
    print(f"\n⏱  总耗时: {elapsed:.1f} 秒")

    if signals:
        print(f"\n💡 提示: 信号出现后持有 {HOLD_DAYS} 个交易日为默认规则")
        print(f"   可使用 scan_results.csv 中的数据进行后续分析")


if __name__ == "__main__":
    main()
