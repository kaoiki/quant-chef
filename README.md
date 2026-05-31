# Quant Chef 🍳

> 基于 **AKShare** 的量化交易研究与策略开发环境。

一站式量化厨房——从数据获取、指标计算到策略回测，开箱即用。

---

## 环境版本

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | **3.11.13** (64-bit) | akshare 官方推荐版本 |
| akshare | **1.18.64** | 金融数据接口（A股/期货/基金/宏观/加密货币等） |
| pandas | 3.0.3 | 数据处理核心 |
| numpy | 2.4.6 | 数值计算 |
| matplotlib | 3.10.9 | 图表绘制 |
| backtrader | 1.9.78.123 | 事件驱动回测框架 |

> 完整依赖清单见 [`environment.yml`](environment.yml)

---

## 快速开始

```bash
# 1. 创建环境（首次）
conda env create -f environment.yml

# 2. 激活环境
conda activate quant-chef

# 3. 验证安装
python verify_env.py
```

### 如果遇到 conda 版本过旧

当前系统 conda 为 4.5.x（来自 Anaconda 早期版本），建议手动安装 Python 3.11 环境：

```bash
# 创建 Python 3.11 环境
conda create -n quant-chef python=3.11 -y

# 激活后通过 pip 安装依赖
conda activate quant-chef
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 项目结构

```
quant-chef/
│
├── src/                          # 核心代码
│   ├── data/
│   │   ├── __init__.py
│   │   └── akshare_loader.py     # AKShare 数据封装（A股行情、成分股等）
│   ├── analysis/
│   │   ├── __init__.py
│   │   └── indicators.py         # 技术指标计算（SMA/EMA/RSI/MACD）
│   └── strategy/
│       └── __init__.py           # 策略模块（待扩展）
│
├── notebooks/                    # Jupyter Notebooks 工作区
├── config/                       # 配置文件（API密钥、参数等）
├── tests/                        # 单元测试
│
├── environment.yml               # Conda 环境定义
├── requirements.txt              # pip 依赖清单
├── verify_env.py                 # 环境验证脚本
└── README.md                     # 本文件
```

---

## 快速上手

### 获取股票行情数据

```python
import akshare as ak

# A股日线（前复权）
df = ak.stock_zh_a_hist(
    symbol="000001",
    period="daily",
    start_date="20250101",
    end_date="20250410",
    adjust="qfq",
)
print(df)
```

### 使用封装模块

```python
from src.data.akshare_loader import get_stock_daily
from src.analysis.indicators import sma, rsi, macd

# 获取数据
df = get_stock_daily("000001", start_date="20240101")

# 计算指标
df["SMA20"] = sma(df["收盘"], 20)
df["RSI14"] = rsi(df["收盘"])
macd_df = macd(df["收盘"])

print(df.tail())
```

### 运行 Jupyter

```bash
conda activate quant-chef
jupyter notebook notebooks/
```

---

## 已集成能力

| 模块 | 功能 | 状态 |
|------|------|------|
| 📡 **数据层** | A股日线行情、实时行情、指数成分股 | ✅ 可用 |
| 📊 **分析层** | SMA、EMA、RSI、MACD 指标计算 | ✅ 可用 |
| 🧪 **策略扫描** | 三日低开高收抄底形态扫描（全A股） | ✅ 可用 |
| 📈 **可视化** | mplfinance K线图、matplotlib/seaborn 图表 | ✅ 可用 |
| 📉 **回测层** | backtrader 框架已安装，策略模板待编写 | ⏳ 待扩展 |

---

## 参考链接

- [AKShare 官方文档](https://akshare.akfamily.xyz/)
- [AKShare GitHub](https://github.com/akfamily/akshare)
- [Backtrader 文档](https://www.backtrader.com/docu/)
- [AKQuant（推荐量化框架）](https://github.com/akfamily/akquant)

---

## 提示

> 程序所在目录、文件名不能命名为 `akshare`，否则会导致导入错误。
>
> 首次使用 matplotlib 会触发字体缓存构建，属正常行为。
