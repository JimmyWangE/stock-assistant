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


def _signed(text: str) -> str:
    """同比数字带上正负号，避免模型漏掉方向。"""
    return text if text == "—" or text.startswith("-") else f"+{text}"


def _financial_url(code: str) -> str:
    return (
        "https://money.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/"
        f"stockid/{code}.phtml"
    )


def _num(by_name: pd.DataFrame, name: str, period: str) -> float | None:
    if name not in by_name.index:
        return None
    value = pd.to_numeric(by_name.at[name, period], errors="coerce")
    return None if pd.isna(value) else float(value)


def _growth_word(change: float) -> str:
    return f"增长 {change:.2f}%" if change > 0 else f"下降 {abs(change):.2f}%" if change < 0 else "持平"


def _trend(changes: list[tuple[str, float]], label: str) -> str:
    """最近几期同比的走向，由程序写好措辞。changes 按时间从早到晚。"""
    if len(changes) < 2:
        return ""
    path = " → ".join(f"{p} {_growth_word(c)}" for p, c in changes)
    (_, before), (_, after) = changes[-2], changes[-1]
    if before > 0 and after < 0:
        how = "由同比增长转为同比下降"
    elif before < 0 and after > 0:
        how = "由同比下降转为同比增长"
    elif before < 0 and after < 0:
        how = "仍是同比下降，降幅" + ("收窄" if after > before else "扩大" if after < before else "不变")
    elif before > 0 and after > 0:
        how = "仍是同比增长，增速" + ("加快" if after > before else "放缓" if after < before else "不变")
    else:
        how = "最新一期同比持平" if after == 0 else "上一期同比持平"
    return f"{label}同比走向（从早到晚）：{path}；最新一期{how}。"


def _relation(revenue: float, profit: float) -> str:
    """营收和利润同比放在一起比较，方向由程序写明。服务器实测模型把营收微增说成"营收降幅"。"""
    gap = abs(profit - revenue)
    if revenue > 0 and profit < 0:
        return "营收同比增长、归母净利润同比下降，两者方向相反（增收不增利）。"
    if revenue < 0 and profit > 0:
        return "营收同比下降、归母净利润同比增长，两者方向相反（减收增利）。"
    if revenue > 0 and profit > 0:
        faster = "高于" if profit > revenue else "低于"
        return f"营收和归母净利润都同比增长，利润增速{faster}营收增速 {gap:.2f} 个百分点。"
    if revenue < 0 and profit < 0:
        more = "大于" if profit < revenue else "小于"
        return f"营收和归母净利润都同比下降，利润降幅{more}营收降幅 {gap:.2f} 个百分点。"
    return ""


def _direction(by_name: pd.DataFrame, periods: list[str]) -> str:
    """把"盈利还是亏损""同比增还是减""营收与利润谁快谁慢""同比怎么变化"由程序写明，不交给模型推断。

    服务器实测：归母净利润 644.67 亿元、同比 −0.25%，模型说成"净利润已转负""盈利首次转负"；
    比亚迪营收同比 +0.01%，模型写成"利润降幅小于营收降幅"。
    """
    latest = periods[0]
    lines = []
    changes: dict[str, float | None] = {}
    for amount, growth, label in (
        ("营业总收入", "营业总收入增长率", "营收"),
        ("归母净利润", "归属母公司净利润增长率", "归母净利润"),
    ):
        value = _num(by_name, amount, latest)
        if value is None:
            continue
        change = changes[label] = _num(by_name, growth, latest)
        state = "" if label == "营收" else ("，为盈利" if value > 0 else "，为亏损")
        part = f"{label} {value / 1e8:,.2f} 亿元{state}"
        if change is not None:
            part += f"，同比{_growth_word(change)}"
            if label == "归母净利润" and change < 0 and value > 0:
                part += "（利润仍为正，只是比上年同期少，不是亏损）"
        lines.append(part)
    if not lines:
        return ""
    out = ["最新一期要点：" + "；".join(lines) + "。"]
    if changes.get("营收") is not None and changes.get("归母净利润") is not None:
        relation = _relation(changes["营收"], changes["归母净利润"])
        if relation:
            out.append(relation)
    recent = list(reversed(periods[:3]))
    for growth, label in (("营业总收入增长率", "营收"), ("归属母公司净利润增长率", "归母净利润")):
        series = [(_period_label(p), v) for p in recent if (v := _num(by_name, growth, p)) is not None]
        trend = _trend(series, label)
        if trend:
            out.append(trend)
    out.append(
        '写法要求：同比为负只能写"同比下降"；利润金额为正时不得写"转负""转亏""亏损""盈利转负"；'
        "上面已写明的方向和比较结论照用，不要自己重新比较。"
    )
    return "\n".join(out) + "\n"


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

    # 逐项写成"指标：报告期 数值"的文字，不给模型 | 分隔的表格（给了表格，模型会照着再画一遍）
    labels = columns[1:]
    detail = "\n".join(
        f"{row[0]}：" + "；".join(f"{p} {_signed(v) if '同比' in row[0] else v}" for p, v in zip(labels, row[1:]))
        for row in rows
    )
    text = (
        f"{title}，最新报告期 {columns[1]}。{note}。\n"
        + _direction(by_name, [str(c) for c in period_cols])
        + "以下各期数据已由系统以表格展示在回答上方，回答里不要再画表格，也不要逐期罗列，挑关键变化做解读。\n"
        + f"{detail}\n"
        + _cite("新浪财经", f"{name}（{code}）财务摘要", _financial_url(code))
    )
    return ToolResult(text=text, blocks=[block])


