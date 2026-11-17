"""新闻：经 AkShare 取自东方财富的个股新闻和全市场财经资讯。"""

from datetime import datetime

import akshare as ak
import pandas as pd

from app.tools.base import ToolError, ToolResult
from app.tools.market import SHANGHAI, _cached, resolve_stock


def _clip(text: object, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _lines(items: list[dict[str, str]]) -> str:
    return "\n".join(
        f"{i}. [{item['title']}]({item['url']})（{item['time']}{item['source']}）{item['summary']}"
        for i, item in enumerate(items, 1)
    )


_CITE_RULE = "引用某条新闻时，必须带上它的 Markdown 链接（原样照抄），并写明发布时间。"


async def get_stock_news(symbol: str, limit: int = 6) -> ToolResult:
    limit = max(1, min(int(limit), 10))
    code, name = resolve_stock(symbol)
    df = await _cached(("news", code), 120, lambda: ak.stock_news_em(symbol=code))
    if df is None or df.empty:
        raise ToolError(f"没有查到 {name}（{code}）的相关新闻")

    df = df.sort_values("发布时间", ascending=False).head(limit)
    items = [
        {
            "title": _clip(row["新闻标题"], 60),
            "url": str(row["新闻链接"]),
            "time": str(row["发布时间"])[:16],
            "source": f"，{row['文章来源']}" if row.get("文章来源") else "",
            "summary": _clip(row["新闻内容"], 90),
        }
        for _, row in df.iterrows()
    ]
    text = f"{name}（{code}）最近的 {len(items)} 条新闻（来源：东方财富）。{_CITE_RULE}\n{_lines(items)}"
    return ToolResult(text=text)


async def get_market_news(keyword: str = "", limit: int = 8) -> ToolResult:
    limit = max(1, min(int(limit), 12))
    df = await _cached(("market_news",), 60, ak.stock_news_global_em)
    if df is None or df.empty:
        raise ToolError("数据源没有返回财经资讯")

    df = df.copy()
    df["发布时间"] = pd.to_datetime(df["发布时间"], errors="coerce")
    df = df.dropna(subset=["发布时间"]).sort_values("发布时间", ascending=False)
    total = len(df)
    keyword = keyword.strip()
    if keyword:
        hit = df["标题"].str.contains(keyword, regex=False, na=False) | df["摘要"].str.contains(
            keyword, regex=False, na=False
        )
        df = df[hit]
        if df.empty:
            raise ToolError(
                f"最近的 {total} 条财经资讯里没有包含「{keyword}」的内容。"
                "可以换一个更短的关键词，或不带关键词查看最新资讯。"
            )
    df = df.head(limit)
    items = [
        {
            "title": _clip(row["标题"], 60),
            "url": str(row["链接"]),
            "time": row["发布时间"].strftime("%Y-%m-%d %H:%M"),
            "source": "",
            "summary": _clip(str(row["摘要"]).split("】", 1)[-1], 90),
        }
        for _, row in df.iterrows()
    ]
    today = datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    scope = f"包含「{keyword}」的" if keyword else "最新的"
    text = (
        f"{scope} {len(items)} 条财经资讯（来源：东方财富，今天是 {today}）。{_CITE_RULE}\n"
        f"{_lines(items)}"
    )
    return ToolResult(text=text)
