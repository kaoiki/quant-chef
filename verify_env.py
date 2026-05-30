#!/usr/bin/env python3
"""
环境验证脚本 - 确认 quant-chef 环境已正确配置
"""

import sys

print("=" * 50)
print("🧪 Quant Chef 环境验证")
print("=" * 50)

# Python 版本
print(f"\n📦 Python: {sys.version.split()[0]}")
print(f"  路径: {sys.executable}")

# 核心库
checks = {
    "akshare": "ak",
    "pandas": "pd",
    "numpy": "np",
    "matplotlib": "mpl",
    "seaborn": "sns",
    "scipy": "sp",
    "statsmodels": "sm",
    "sklearn": "skl",
    "backtrader": "bt",
    "mplfinance": "mpf",
    "tqdm": "tqdm",
}

all_ok = True
for lib, alias in checks.items():
    try:
        mod = __import__(lib)
        ver = getattr(mod, "__version__", "N/A")
        print(f"  ✅ {lib:20s} {ver:15s}  as {alias}")
    except ImportError as e:
        print(f"  ❌ {lib:20s} 未安装 — {e}")
        all_ok = False

print(f"\n{'=' * 50}")
if all_ok:
    print("✅ 环境验证通过！厨师就位，可以开始量化烹饪了 🍳")
else:
    print("⚠️  部分依赖缺失，请检查安装")
print("=" * 50)
