#!/usr/bin/env python3
"""
Quant Chef 🍳 — 期货行情终端查看器 (TUI)

在终端中查看国内期货实时行情和历史走势。

用法:
    python futures_tui.py                   # 按板块查看热门品种
    python futures_tui.py RB0               # 查看指定品种详情
    python futures_tui.py RB0 CU0 AU0       # 多品种对比
    python futures_tui.py --watch           # 实时刷新模式
    python futures_tui.py --interactive     # 交互式浏览模式
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

APP_DIR = __file__ and __file__[:__file__.rfind("/")] or "."
sys.path.insert(0, APP_DIR)

from src.data.futures_market import (
    fetch_futures_quotes,
    fetch_futures_kline,
    FUTURES_CONTRACTS,
    HOT_FUTURES_SECTORS,
)

console = Console()

# ═══════════════════════════════════════════════════════
#  终端图表引擎（复用股票版）
# ═══════════════════════════════════════════════════════

BLOCKS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]


def sparkline(values: List[float], width: int = 40, up_color="green", down_color="red") -> str:
    if not values:
        return ""
    if len(values) < 2:
        return BLOCKS[0]
    n = len(values)
    indices = [int(i * (n - 1) / (width - 1)) for i in range(width)]
    sampled = [values[i] for i in indices]
    mn, mx = min(sampled), max(sampled)
    if mx - mn < 0.001:
        return "─" * width
    spans = []
    for v in sampled:
        level = int((v - mn) / (mx - mn) * 7)
        level = max(0, min(7, level))
        spans.append(BLOCKS[level])
    color = up_color if values[-1] >= values[0] else down_color
    return f"[{color}]{''.join(spans)}[/]"


def ascii_candle_chart(klines: List[Dict], width: int = 50, height: int = 8) -> str:
    if not klines or len(klines) < 2:
        return "[dim]数据不足[/]"
    n = len(klines)
    indices = [int(i * (n - 1) / (width - 1)) for i in range(width)]
    sampled = [klines[i] for i in indices]
    highs = [d["high"] for d in sampled]
    lows = [d["low"] for d in sampled]
    mn, mx = min(lows), max(highs)
    if mx - mn < 0.001:
        return "[dim]价格无波动[/]"
    lines = []
    for row in range(height):
        lower_bound = mn + (mx - mn) * (height - 1 - row) / height
        upper_bound = mn + (mx - mn) * (height - row) / height
        line_chars = []
        for d in sampled:
            high, low = d["high"], d["low"]
            close, open_p = d["close"], d["open"]
            in_range = (high >= lower_bound and low <= upper_bound)
            if not in_range:
                line_chars.append(" ")
                continue
            is_up = close >= open_p
            body_high = max(open_p, close)
            body_low = min(open_p, close)
            in_body = (body_high >= lower_bound and body_low <= upper_bound)
            if in_body:
                line_chars.append(f"[green]█[/]" if is_up else f"[red]█[/]")
            else:
                line_chars.append(f"[dim]│[/]")
        lines.append("".join(line_chars))
    price_labels = [f"{p:,.2f}" for p in [mx, (mx + mn) / 2, mn]]
    for i, pos in enumerate([0, height // 2, height - 1]):
        if pos < len(lines):
            lines[pos] = lines[pos] + f"  [dim]{price_labels[i]}[/]"
    return "\n".join(lines)


def volume_bars(klines: List[Dict], width: int = 30) -> str:
    if not klines:
        return ""
    n = len(klines)
    indices = [int(i * (n - 1) / (width - 1)) for i in range(width)]
    sampled = [klines[i] for i in indices]
    volumes = [d["volume"] for d in sampled]
    closes = [d["close"] for d in sampled]
    opens = [d["open"] for d in sampled]
    mn, mx = min(volumes), max(volumes)
    if mx - mn < 0.001:
        return "─" * width
    chars = []
    for i in range(width):
        level = int((volumes[i] - mn) / (mx - mn) * 7)
        level = max(0, min(7, level))
        is_up = closes[i] >= opens[i]
        chars.append(f"[{'green' if is_up else 'red'}]{BLOCKS[level]}[/]")
    return "".join(chars)


# ═══════════════════════════════════════════════════════
#  格式化工具
# ═══════════════════════════════════════════════════════

def fmt_price(v: float) -> str:
    if v >= 1000:
        return f"{v:,.2f}"
    elif v >= 10:
        return f"{v:.2f}"
    else:
        return f"{v:.3f}"


def fmt_volume(v: float) -> str:
    if v >= 1_0000_0000:
        return f"{v / 1_0000_0000:.2f}亿"
    elif v >= 1_0000:
        return f"{v / 1_0000:.2f}万"
    return f"{v:.0f}"


def fmt_hold(v: float) -> str:
    if v >= 1_0000:
        return f"{v / 1_0000:.1f}万"
    return f"{v:.0f}"


# ═══════════════════════════════════════════════════════
#  UI 构建
# ═══════════════════════════════════════════════════════

def sector_emoji(sector: str) -> str:
    emojis = {
        "贵金属": "💎", "黑色系": "🪨", "有色": "🔩",
        "能源": "⛽", "农产品": "🌾", "化工": "🧪",
        "建材": "🧱",
    }
    return emojis.get(sector, "📊")


def build_futures_list() -> List[Panel]:
    """按板块构建期货列表"""
    panels = []

    for sector_name, sym_list in HOT_FUTURES_SECTORS:
        quotes = fetch_futures_quotes(sym_list)
        emoji = sector_emoji(sector_name)

        table = Table(
            title=f"{emoji} {sector_name}",
            box=box.SIMPLE,
            header_style="bold cyan",
            show_header=True,
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("代码", style="dim", width=6)
        table.add_column("名称", style="bold", width=8)
        table.add_column("最新价", justify="right", width=10)
        table.add_column("涨跌幅", justify="right", width=8)
        table.add_column("成交量", justify="right", width=10)
        table.add_column("持仓量", justify="right", width=10)

        for sym in sym_list:
            # 查找品种信息
            info = next((c for c in FUTURES_CONTRACTS if c[0] == sym), None)
            name = info[1] if info else sym
            q = quotes.get(sym, {})
            if not q or "_error" in q:
                table.add_row(sym, name, "—", "—", "—", "—")
                continue

            change = q.get("涨跌幅", 0)
            change_style = "green" if change >= 0 else "red"
            change_str = f"[{change_style}]{change:+.2f}%[/]"
            table.add_row(
                sym,
                name,
                fmt_price(q.get("最新价", 0)),
                change_str,
                fmt_volume(q.get("成交量", 0)),
                fmt_hold(q.get("持仓量", 0)),
            )

        panels.append(Panel(table, box=box.ROUNDED, border_style="dim"))

    return panels


def build_futures_detail(symbol: str, datalen: int = 90) -> Panel:
    """构建单个期货品种的详情视图"""
    # 查找品种信息
    info = next((c for c in FUTURES_CONTRACTS if c[0] == symbol), None)
    variety_name = info[1] if info else symbol
    sector_name = info[3] if info else ""
    emoji = sector_emoji(sector_name)

    # 实时行情
    quotes = fetch_futures_quotes([symbol])
    q = quotes.get(symbol, {})
    if not q or "_error" in q:
        return Panel(f"[red]无法获取 {symbol} 的数据[/]")

    # K线历史
    klines = fetch_futures_kline(symbol, datalen)
    has_error = klines and "_error" in klines[0]

    price = q.get("最新价", 0)
    change = q.get("涨跌幅", 0)
    change_amt = q.get("涨跌额", 0)
    open_p = q.get("今开", 0)
    last_settle = q.get("昨结算", 0)
    settle = q.get("结算价", 0)
    volume = q.get("成交量", 0)
    hold = q.get("持仓量", 0)
    exchange = q.get("交易所", "")

    color = "green" if change >= 0 else "red"
    arrow = "▲" if change >= 0 else "▼"

    # ── 头部 ──
    header = (
        f"[bold]{variety_name}[/] [dim]{symbol}[/]  "
        f"[bold]{fmt_price(price)}[/]  "
        f"[{color}]{arrow} {change:+.2f}% ({change_amt:+.2f})[/]  "
        f"[dim]{exchange}[/]"
    )

    # ── 关键指标 ──
    info_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    info_table.add_column(style="dim", width=8)
    info_table.add_column(style="bold", width=12)
    info_table.add_column(style="dim", width=8)
    info_table.add_column(style="bold", width=12)
    info_table.add_row(
        "📊 今开", fmt_price(open_p),
        "📊 昨结算", fmt_price(last_settle),
    )
    info_table.add_row(
        "💰 结算价", fmt_price(settle),
        "📦 成交量", fmt_volume(volume),
    )
    info_table.add_row(
        "📋 持仓量", fmt_hold(hold),
        "", "",
    )

    # ── 走势图 ──
    chart_lines = []
    if not has_error and len(klines) >= 2:
        closes = [d["close"] for d in klines]

        # Sparkline
        spark = sparkline(closes, width=50)
        chart_lines.append(f"\n[b]趋势图 (近{len(klines)}天):[/]")
        chart_lines.append(spark)

        # K线图
        chart_lines.append(f"\n[b]K线图:[/]")
        chart_lines.append(ascii_candle_chart(klines, width=50, height=8))

        # 成交量
        chart_lines.append(f"\n[b]成交量 / 持仓量:[/]")
        chart_lines.append(volume_bars(klines, width=50))

        # 统计
        recent5 = klines[-5:]
        chg5 = (recent5[-1]["close"] - recent5[0]["close"]) / recent5[0]["close"] * 100
        max_c = max(d["close"] for d in klines[-20:])
        min_c = min(d["close"] for d in klines[-20:])
        avg_v = sum(d["volume"] for d in klines[-20:]) / min(20, len(klines))
        avg_h = sum(d["hold"] for d in klines[-20:]) / min(20, len(klines))

        chart_lines.append(
            f"\n[dim]近5日涨跌:[/] {chg5:+.2f}%  "
            f"[dim]近20日区间:[/] {fmt_price(min_c)} ~ {fmt_price(max_c)}  "
            f"[dim]日均成交量:[/] {fmt_volume(avg_v)}  "
            f"[dim]均持仓:[/] {fmt_hold(avg_h)}"
        )
    else:
        chart_lines.append(f"\n[red]K线数据获取失败[/]")

    content = Group(Text(header), info_table, *chart_lines)

    return Panel(
        content,
        box=box.ROUNDED,
        border_style=f"bold {color}",
        title=f"[bold]{emoji} {variety_name} ({symbol})[/]",
        subtitle=f"更新: {q.get('日期', '—')}",
    )


# ═══════════════════════════════════════════════════════
#  Watch 模式
# ═══════════════════════════════════════════════════════

def build_watch_layout(symbols: Optional[List[str]] = None) -> Layout:
    if symbols is None:
        symbols = ["AU0", "AG0", "RB0", "CU0", "SC0", "M0"]

    layout = Layout()
    layout.split(
        Layout(name="header", size=1),
        Layout(name="main"),
    )

    layout["header"].update(
        Panel(
            f"[bold]Quant Chef 🍳  期货行情监控  [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]  按 Ctrl+C 退出[/]",
            style="bold white on dark_blue",
            box=box.SIMPLE,
        )
    )

    quotes = fetch_futures_quotes(symbols)
    panels = []
    for sym in symbols:
        info = next((c for c in FUTURES_CONTRACTS if c[0] == sym), None)
        name = info[1] if info else sym
        q = quotes.get(sym, {})
        if not q:
            continue
        price = q.get("最新价", 0)
        change = q.get("涨跌幅", 0)
        color = "green" if change >= 0 else "red"
        arrow = "▲" if change >= 0 else "▼"

        panels.append(
            Panel(
                f"[bold]{fmt_price(price)}[/]\n[{color}]{arrow} {change:+.2f}%[/]\n"
                f"[dim]量:{fmt_volume(q.get('成交量',0))} 仓:{fmt_hold(q.get('持仓量',0))}[/]",
                title=f"[bold]{name}[/] [dim]{sym}[/]",
                box=box.SIMPLE,
                border_style=color,
                width=22,
                height=6,
            )
        )

    # 板块列表
    list_panels = build_futures_list()

    layout["main"].update(
        Group(
            Panel(
                Columns(panels, equal=True, expand=True),
                title="📊 重点品种概览",
                box=box.ROUNDED,
            ),
            *list_panels,
        )
    )
    return layout


def watch_mode(symbols: Optional[List[str]] = None, interval: int = 5):
    if symbols is None:
        symbols = ["AU0", "AG0", "RB0", "CU0", "SC0", "M0"]
    try:
        with Live(refresh_per_second=1 / interval, screen=True) as live:
            while True:
                layout = build_watch_layout(symbols)
                live.update(layout)
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]监控已停止[/]")


# ═══════════════════════════════════════════════════════
#  交互式模式
# ═══════════════════════════════════════════════════════

def interactive_mode():
    console.clear()
    console.print(Panel("[bold]🍳 Quant Chef 期货浏览器[/]", style="bold cyan"))

    while True:
        panels = build_futures_list()
        for p in panels:
            console.print(p)

        print("\n📌 ", end="")
        print("输入 [bold cyan]代码[/] 查看详情（如 RB0）  ", end="")
        print("输入 [bold]l[/] 刷新  ", end="")
        print("输入 [bold]q[/] 退出  ", end="")

        choice = Prompt.ask("\n👉", default="l")
        if choice.lower() == "q":
            break
        elif choice.lower() == "l":
            console.clear()
            continue
        else:
            sym = choice.strip().upper()
            console.clear()
            panel = build_futures_detail(sym)
            console.print(panel)
            print("\n[dim]按 Enter 返回列表...[/]", end="")
            input()
            console.clear()


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Quant Chef 🍳 期货行情终端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                    按板块查看期货列表
  %(prog)s RB0                查看螺纹钢详情
  %(prog)s RB0 CU0 AU0        多品种对比
  %(prog)s --watch            实时监控模式
  %(prog)s --interactive      交互浏览模式
        """,
    )
    parser.add_argument("symbols", nargs="*", help="期货代码（如 RB0 CU0 AU0）")
    parser.add_argument("--watch", "-w", action="store_true", help="实时刷新模式")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互式浏览模式")
    parser.add_argument("--datalen", type=int, default=90, help="K线天数（默认90）")

    args = parser.parse_args()

    if args.interactive:
        interactive_mode()
        return

    if args.watch:
        watch_mode(args.symbols if args.symbols else None)
        return

    if not args.symbols:
        # 按板块列出
        console.print(
            Panel(
                "[bold]🍳 Quant Chef — 国内期货行情终端[/]\n"
                "[dim]python futures_tui.py <代码> 查看详情 | --interactive 浏览 | --watch 监控[/]",
                style="bold cyan",
            )
        )
        panels = build_futures_list()
        for p in panels:
            console.print(p)
    else:
        for sym in args.symbols:
            console.print(build_futures_detail(sym.upper(), args.datalen))


if __name__ == "__main__":
    main()
