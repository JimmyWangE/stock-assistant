"""财务数据：经 AkShare 取自新浪财经的财务摘要。"""

import akshare as ak
import pandas as pd

from app.tools.base import ToolError, ToolResult
from app.tools.market import _cached, _cite, resolve_stock

# （数据源里的指标名, 展示名, 单位）。金额换算成亿元，其余保持原单位
INDICATORS = [
    ("营业总收入", "营业总收入（亿元）", "yi"),
    ("归母净利润", "归母净利润（亿元）", "yi"),
    ("扣非净利润", "扣非净利润（亿元）", "yi"),
    ("经营现金流量净额", "经营现金流净额（亿元）", "yi"),
    ("营业总收入增长率", "营收同比（%）", "pct"),
    ("归属母公司净利润增长率", "归母净利润同比（%）", "pct"),
    ("毛利率", "毛利率（%）", "pct"),
    ("销售净利率", "净利率（%）", "pct"),
    ("净资产收益率(ROE)", "ROE（%）", "pct"),
    ("资产负债率", "资产负债率（%）", "pct"),
    ("基本每股收益", "每股收益（元）", "raw"),
    ("每股净资产", "每股净资产（元）", "raw"),
]
_PERIOD_NAMES = {"0331": "一季报", "0630": "中报", "0930": "三季报", "1231": "年报"}


def _period_label(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}{_PERIOD_NAMES.get(yyyymmdd[4:], yyyymmdd[4:])}"


def _format(value: object, unit: str) -> str:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "—"
    return f"{number / 1e8:,.2f}" if unit == "yi" else f"{number:,.2f}"


def _financial_url(code: str) -> str:
    return (
        "https://money.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/"
        f"stockid/{code}.phtml"
    )


async def get_financials(symbol: str, periods: int = 6) -> ToolResult:
    periods = max(2, min(int(periods), 8))
    code, name = resolve_stock(symbol)
    try:
        df = await _cached(("fin", code), 3600, lambda: ak.stock_financial_abstract(symbol=code))
    except Exception:  # noqa: BLE001 代码不存在时数据源库内部会直接报错
        df = None
    if df is None or df.empty:
        raise ToolError("数据源没有返回财务数据，请确认股票代码是否正确")

    period_cols = [c for c in df.columns if str(c).isdigit()][:periods]
    if not period_cols:
        raise ToolError("数据源没有返回任何报告期")
    # 同一个指标会在多个分类下重复出现，取第一次出现的那行
    by_name = df.drop_duplicates(subset="指标").set_index("指标")

    columns = ["指标", *(_period_label(str(c)) for c in period_cols)]
    rows = [
        [label, *(_format(by_name.at[source, c], unit) for c in period_cols)]
        for source, label, unit in INDICATORS
        if source in by_name.index
    ]
    title = f"{name}（{code}）主要财务指标"
    note = "金额类为年初至报告期末的累计值，同比为与上年同期相比"
    block = {
        "type": "table",
        "title": title,
        "columns": columns,
        "rows": rows,
        "note": note,
        "source": {"name": "新浪财经", "url": _financial_url(code)},
    }

    table = "\n".join(" | ".join(row) for row in [columns, *rows])
    text = (
        f"{title}，最新报告期 {columns[1]}。{note}。\n"
        f"这张表已由系统展示给用户，不必完整复述，重点做解读。\n{table}\n"
        + _cite("新浪财经", f"{name}（{code}）财务摘要", _financial_url(code))
    )
    return ToolResult(text=text, blocks=[block])


