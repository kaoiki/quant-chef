#!/usr/bin/env python3
"""
Quant Chef 🍳 — 终端股票查看器 (TUI)

在终端中查看 A 股实时行情和历史走势，支持 sparkline 趋势图。

用法:
    python stock_tui.py                  # 查看热门股票列表
    python stock_tui.py 000001           # 查看指定股票详情
    python stock_tui.py 000001 600519    # 查看多只股票
    python stock_tui.py --watch          # 实时刷新模式（每5秒）
    python stock_tui.py --interactive    # 交互式浏览模式
"""

import sys
import time
import argparse
from datetime import datetime
from typing import List, Optional, Dict, Any

from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.prompt import Prompt
from rich.align import Align

# 将项目根加入路径
import os
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from src.data.market import (
    fetch_quotes,
    fetch_kline,
    HOT_STOCKS,
)

console = Console()

# ═══════════════════════════════════════════════════════
#  终端图表引擎
# ═══════════════════════════════════════════════════════

# Unicode 半方块字符 (8 级高度)
BLOCKS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
# 用于涨跌颜色的字符
BLOCK_UP = "█"
BLOCK_DOWN = "▄"


def sparkline(values: List[float], width: int = 40, up_color="green", down_color="red") -> str:
    """
    绘制 sparkline 趋势线

    参数:
        values: 数值序列（最近的在最后）
        width:  字符宽度
    """
    if not values:
        return ""
    if len(values) < 2:
        return BLOCKS[0]

    n = len(values)
    # 采样到 width 个点
    indices = [int(i * (n - 1) / (width - 1)) for i in range(width)]
    sampled = [values[i] for i in indices]

    mn, mx = min(sampled), max(sampled)
    if mx - mn < 0.001:
        return "─" * width

    spans = []
    for i, v in enumerate(sampled):
        # 映射到 0-7 级
        level = int((v - mn) / (mx - mn) * 7)
        level = max(0, min(7, level))
        spans.append(BLOCKS[level])

    # 着色: 如果整体上涨用绿色，下跌用红色
    if values[-1] >= values[0]:
        return f"[{up_color}]{''.join(spans)}[/]"
    else:
        return f"[{down_color}]{''.join(spans)}[/]"


def ascii_candle_chart(klines: List[Dict], width: int = 50, height: int = 8) -> str:
    """
    绘制简易 ASCII K线图（由 | - + 组成）

    每一根 "K线" 用 3 字符表示: 上影线部分/实体/下影线部分
    因为终端空间限制，这里用改进的字符画法
    """
    if not klines or len(klines) < 2:
        return "[dim]数据不足[/]"

    n = len(klines)
    indices = [int(i * (n - 1) / (width - 1)) for i in range(width)]
    sampled = [klines[i] for i in indices]

    highs = [d["high"] for d in sampled]
    lows = [d["low"] for d in sampled]
    closes = [d["close"] for d in sampled]
    opens = [d["open"] for d in sampled]

    mn = min(lows)
    mx = max(highs)
    if mx - mn < 0.001:
        return "[dim]价格无波动[/]"

    lines = []
    for row in range(height):
        # 从下往上画，row=0 是最低价区域，row=height-1 是最高价区域
        lower_bound = mn + (mx - mn) * (height - 1 - row) / height
        upper_bound = mn + (mx - mn) * (height - row) / height
        line_chars = []
        for i, d in enumerate(sampled):
            high = d["high"]
            low = d["low"]
            close = d["close"]
            open_p = d["open"]

            # 判断这个高度的条带是否在价格范围内
            # 用中点判断
            in_range = (high >= lower_bound and low <= upper_bound)
            if not in_range:
                line_chars.append(" ")
                continue

            is_up = close >= open_p

            # 简化为: 实体部分用 █，影线部分用 │
            # 判断当前行是否在实体范围内
            body_high = max(open_p, close)
            body_low = min(open_p, close)

            # 检查是否在实体范围内
            in_body = (body_high >= lower_bound and body_low <= upper_bound)

            if in_body:
                line_chars.append(f"[green]█[/]" if is_up else f"[red]█[/]")
            else:
                # 影线
                shadow_in = (high >= lower_bound and low <= upper_bound)
                if shadow_in:
                    line_chars.append(f"[dim]│[/]")
                else:
                    line_chars.append(" ")
        lines.append("".join(line_chars))

    # 添加价格刻度
    price_labels = []
    for p in [mx, (mx + mn) / 2, mn]:
        price_labels.append(f"{p:,.2f}")
    # 在右侧标注价格
    label_positions = [0, height // 2, height - 1]
    for i, pos in enumerate(label_positions):
        if pos < len(lines):
            lines[pos] = lines[pos] + f"  [dim]{price_labels[i]}[/]"

    return "\n".join(lines)


def volume_bars(klines: List[Dict], width: int = 30) -> str:
    """成交量条形图"""
    if not klines:
        return ""

    n = len(klines)
    indices = [int(i * (n - 1) / (width - 1)) for i in range(width)]
    sampled = [klines[i] for i in indices]

    volumes = [d["volume"] for d in sampled]
    closes = [d["close"] for d in sampled]
    opens = [d["open"] for d in sampled]
    mn = min(volumes)
    mx = max(volumes)

    if mx - mn < 0.001:
        return "─" * width

    chars = []
    for i in range(width):
        level = int((volumes[i] - mn) / (mx - mn) * 7)
        level = max(0, min(7, level))
        is_up = closes[i] >= opens[i]
        color = "green" if is_up else "red"
        chars.append(f"[{color}]{BLOCKS[level]}[/]")

    return "".join(chars)


# ═══════════════════════════════════════════════════════
#  UI 构建函数
# ═══════════════════════════════════════════════════════

def fmt_price(v: float) -> str:
    """格式化价格"""
    if v >= 1000:
        return f"{v:,.2f}"
    elif v >= 10:
        return f"{v:.2f}"
    else:
        return f"{v:.3f}"


def fmt_volume(v: int) -> str:
    """格式化成交量"""
    if v >= 1_0000_0000:
        return f"{v / 1_0000_0000:.2f}亿"
    elif v >= 1_0000:
        return f"{v / 1_0000:.2f}万"
    return str(v)


def fmt_amount(v: float) -> str:
    """格式化成交额"""
    if v >= 1_0000_0000:
        return f"{v / 1_0000_0000:.2f}亿"
    elif v >= 1_0000:
        return f"{v / 1_0000:.2f}万"
    return f"{v:.2f}"


def build_stock_table() -> Table:
    """构建热门股票列表"""
    codes = [s[0] for s in HOT_STOCKS]
    quotes = fetch_quotes(codes)

    table = Table(
        title=f"📈 热门股票行情  [{datetime.now().strftime('%H:%M:%S')}]",
        box=box.ROUNDED,
        header_style="bold cyan",
        title_style="bold white",
        show_lines=True,
    )
    table.add_column("代码", style="dim", width=8)
    table.add_column("名称", style="bold", width=10)
    table.add_column("最新价", justify="right", width=10)
    table.add_column("涨跌幅", justify="right", width=8)
    table.add_column("涨跌额", justify="right", width=8)
    table.add_column("最高", justify="right", width=10)
    table.add_column("最低", justify="right", width=10)
    table.add_column("成交量", justify="right", width=10)
    table.add_column("板块", width=8)

    for code, name, sector in HOT_STOCKS:
        q = quotes.get(code, {})
        if not q or "_error" in q:
            table.add_row(code, name, "—", "—", "—", "—", "—", "—", sector)
            continue

        change = q.get("涨跌幅", 0)
        change_style = "green" if change >= 0 else "red"
        change_str = f"[{change_style}]{change:+.2f}%[/]"
        change_amount = q.get("涨跌额", 0)
        change_amt_str = f"[{change_style}]{change_amount:+.2f}[/]"

        table.add_row(
            code,
            name,
            fmt_price(q.get("当前价", 0)),
            change_str,
            change_amt_str,
            fmt_price(q.get("最高", 0)),
            fmt_price(q.get("最低", 0)),
            fmt_volume(q.get("成交量", 0)),
            sector,
        )

    return table


def build_stock_detail(code: str, datalen: int = 90) -> Panel:
    """构建单只股票的详细视图"""
    # 获取实时行情
    quotes = fetch_quotes([code])
    q = quotes.get(code, {})
    if not q or "_error" in q:
        return Panel(f"[red]无法获取 {code} 的数据[/]")

    # 获取K线历史
    klines = fetch_kline(code, datalen)
    has_error = klines and "_error" in klines[0]

    name = q.get("名称", code)
    price = q.get("当前价", 0)
    change = q.get("涨跌幅", 0)
    change_amt = q.get("涨跌额", 0)
    high = q.get("最高", 0)
    low = q.get("最低", 0)
    open_p = q.get("今开", 0)
    yclose = q.get("昨收", 0)
    volume = q.get("成交量", 0)
    amount = q.get("成交额", 0)

    color = "green" if change >= 0 else "red"
    arrow = "▲" if change >= 0 else "▼"

    # ── 头部：名称 + 价格 + 涨跌 ──
    header = (
        f"[bold]{name}[/] [dim]{code}[/]  "
        f"[bold]{fmt_price(price)}[/]  "
        f"[{color}]{arrow} {change:+.2f}% ({change_amt:+.2f})[/]"
    )

    # ── 关键指标 ──
    info_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    info_table.add_column(style="dim", width=8)
    info_table.add_column(style="bold", width=12)
    info_table.add_column(style="dim", width=8)
    info_table.add_column(style="bold", width=12)
    info_table.add_row(
        "📊 今开", fmt_price(open_p),
        "📈 最高", fmt_price(high),
    )
    info_table.add_row(
        "📉 昨收", fmt_price(yclose),
        "📊 最低", fmt_price(low),
    )
    info_table.add_row(
        "📦 成交量", fmt_volume(volume),
        "💰 成交额", fmt_amount(amount),
    )

    # ── 走势图 ──
    chart_section = []
    if not has_error and len(klines) >= 2:
        closes = [d["close"] for d in klines]

        # Sparkline趋势
        spark = sparkline(closes, width=50)
        chart_section.append(f"\n[b]趋势图 (近{len(klines)}天):[/]")
        chart_section.append(spark)

        # K线图
        chart_section.append(f"\n[b]K线图:[/]")
        chart_section.append(ascii_candle_chart(klines, width=50, height=8))

        # 成交量
        chart_section.append(f"\n[b]成交量:[/]")
        chart_section.append(volume_bars(klines, width=50))

        # 统计信息
        recent = klines[-5:]
        change_5d = (recent[-1]["close"] - recent[0]["close"]) / recent[0]["close"] * 100
        max_close = max(d["close"] for d in klines[-20:])
        min_close = min(d["close"] for d in klines[-20:])
        avg_vol = sum(d["volume"] for d in klines[-20:]) / min(20, len(klines))

        chart_section.append(
            f"\n[dim]近5日涨跌:[/] {change_5d:+.2f}%  "
            f"[dim]近20日区间:[/] {fmt_price(min_close)} ~ {fmt_price(max_close)}  "
            f"[dim]日均成交量:[/] {fmt_volume(int(avg_vol))}"
        )
    else:
        chart_section.append(f"\n[red]K线数据获取失败[/]")

    # ── 组装 ──
    content = Group(
        Text(header),
        info_table,
        *chart_section,
    )

    return Panel(
        content,
        box=box.ROUNDED,
        border_style=f"bold {color}",
        title=f"[bold]{'🟢' if change>=0 else '🔴'} {name} ({code})[/]",
        subtitle=f"更新: {q.get('时间', '—')}",
    )


def build_watch_layout(codes: Optional[List[str]] = None) -> Layout:
    """构建实时监控布局"""
    if codes is None:
        codes = [s[0] for s in HOT_STOCKS[:6]]

    layout = Layout()
    layout.split(
        Layout(name="header", size=1),
        Layout(name="main"),
    )

    # 头部
    layout["header"].update(
        Panel(
            f"[bold]Quant Chef 🍳  股票行情监控  [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]  按 Ctrl+C 退出[/]",
            style="bold white on dark_blue",
            box=box.SIMPLE,
        )
    )

    # 主区域：多面板
    quotes = fetch_quotes(codes)
    panels = []
    for code in codes:
        q = quotes.get(code, {})
        if not q:
            continue
        name = q.get("名称", code)
        price = q.get("当前价", 0)
        change = q.get("涨跌幅", 0)
        color = "green" if change >= 0 else "red"
        arrow = "▲" if change >= 0 else "▼"

        panels.append(
            Panel(
                f"[bold]{fmt_price(price)}[/]\n[{color}]{arrow} {change:+.2f}%[/]",
                title=f"[bold]{name}[/] [dim]{code}[/]",
                box=box.SIMPLE,
                border_style=color,
                width=20,
                height=5,
            )
        )

    layout["main"].update(
        Group(
            Panel(
                Columns(panels, equal=True, expand=True),
                title="📊 实时概览",
                box=box.ROUNDED,
            ),
            build_stock_table(),
        )
    )

    return layout


# ═══════════════════════════════════════════════════════
#  交互式模式 (基于 Prompt 的简单导航)
# ═══════════════════════════════════════════════════════

def interactive_mode():
    """交互式浏览模式"""
    current_codes = [s[0] for s in HOT_STOCKS]

    console.clear()
    console.print(Panel("[bold]🍳 Quant Chef 股票浏览器[/]", style="bold cyan"))

    while True:
        # 输出列表
        table = build_stock_table()
        console.print(table)

        print("\n📌 ", end="")
        print("输入 [bold cyan]股票代码[/] 查看详情  ", end="")
        print("输入 [bold]l[/] 刷新列表  ", end="")
        print("输入 [bold]q[/] 退出  ", end="")

        choice = Prompt.ask("\n👉", default="l")

        if choice.lower() == "q":
            break
        elif choice.lower() == "l":
            console.clear()
            continue
        else:
            # 查看详情
            code = choice.strip()
            console.clear()
            panel = build_stock_detail(code)
            console.print(panel)
            print("\n[dim]按 Enter 返回列表...[/]", end="")
            input()
            console.clear()


# ═══════════════════════════════════════════════════════
#  Watch 模式（实时刷新）
# ═══════════════════════════════════════════════════════

def watch_mode(codes: Optional[List[str]] = None, interval: int = 5):
    """实时刷新模式"""
    if codes is None:
        codes = [s[0] for s in HOT_STOCKS[:6]]

    try:
        with Live(refresh_per_second=1 / interval, screen=True) as live:
            while True:
                layout = build_watch_layout(codes)
                live.update(layout)
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]监控已停止[/]")


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Quant Chef 🍳 终端股票查看器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                    热门股票列表
  %(prog)s 000001             查看平安银行
  %(prog)s 000001 600519      多股对比
  %(prog)s --watch            实时监控模式
  %(prog)s 000001 --watch     指定股票监控
  %(prog)s --interactive      交互浏览模式
        """,
    )
    parser.add_argument("codes", nargs="*", help="股票代码（如 000001 600519）")
    parser.add_argument("--watch", "-w", action="store_true", help="实时刷新模式")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互式浏览模式")
    parser.add_argument("--datalen", type=int, default=90, help="K线数据天数（默认90）")

    args = parser.parse_args()

    if args.interactive:
        interactive_mode()
        return

    if args.watch:
        watch_mode(args.codes if args.codes else None)
        return

    # 默认模式
    codes = args.codes

    if not codes:
        # 显示热门股票列表
        table = build_stock_table()
        console.print(
            Panel(
                "[bold]🍳 Quant Chef — A股行情终端[/]\n[dim]python stock_tui.py <代码> 查看详情 | --interactive 浏览 | --watch 监控[/]",
                style="bold cyan",
            )
        )
        console.print(table)
    else:
        # 查看指定股票详情
        for code in codes:
            console.print(build_stock_detail(code, args.datalen))


if __name__ == "__main__":
    main()
