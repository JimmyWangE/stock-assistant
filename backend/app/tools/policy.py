"""官方政策原文：直接读取各部委官网的发布列表，链接指向官网原文。

AkShare 没有这类接口，所以这里自己抓。每个网站一个解析函数；
网站改版导致某一家解析不出来时，只影响那一家，其余照常返回。
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

import httpx

from app.tools.base import ToolError, ToolResult
from app.tools.market import SHANGHAI

logger = logging.getLogger(__name__)

Item = dict[str, str]  # title、url、date（YYYY-MM-DD）、source

# 政府网站会拒绝不带浏览器标识的请求
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}
_CACHE_SECONDS = 600
_KEEP_PER_SOURCE = 40


def _clean(text: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", "", text)).split())


def _parse_gov(resp: httpx.Response, base: str) -> list[Item]:
    return [
        {"title": _clean(row["TITLE"]), "url": row["URL"], "date": row["DOCRELPUBTIME"][:10]}
        for row in resp.json()
    ]


def _parse_csrc(resp: httpx.Response, base: str) -> list[Item]:
    return [
        {
            "title": _clean(row["title"]),
            "url": urljoin(base, row["url"]),
            "date": row["publishedTimeStr"][:10],
        }
        for row in resp.json()["data"]["results"]
    ]


def _parse_links(pattern: str) -> Callable[[httpx.Response, str], list[Item]]:
    """列表页是 HTML 的网站：用一条正则取出（链接、标题、日期）。"""
    regex = re.compile(pattern, re.S)

    def parse(resp: httpx.Response, base: str) -> list[Item]:
        resp.encoding = "utf-8"
        return [
            {
                "title": _clean(title),
                "url": urljoin(base, href),
                "date": date.replace("/", "-"),
            }
            for href, title, date in regex.findall(resp.text)
        ]

    return parse


_LI = r'<li>\s*<a href="([^"]+)"[^>]*?title=["\']([^"\']+)["\'][^>]*>.*?</a>\s*<span>(\d{4}[-/]\d{2}[-/]\d{2})</span>'

# （机构名，栏目名，列表地址，解析函数）
SOURCES: list[tuple[str, str, str, Callable[[httpx.Response, str], list[Item]]]] = [
    ("国务院", "最新政策", "https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json", _parse_gov),
    (
        "证监会",
        "证监会要闻",
        "http://www.csrc.gov.cn/searchList/a1a078ee0bc54721ab6b148884c784a8"
        "?_isAgg=true&_isJson=true&_pageSize=40&_template=index&page=1",
        _parse_csrc,
    ),
    (
        "中国人民银行",
        "新闻",
        "http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
        _parse_links(
            r'<a href="(/goutongjiaoliu/113456/113469/\d+/index\.html)"[^>]*>(.*?)</a>'
            r".{0,200}?(\d{4}-\d{2}-\d{2})"
        ),
    ),
    ("财政部", "政策发布", "https://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/", _parse_links(_LI)),
    ("国家发展改革委", "新闻发布", "https://www.ndrc.gov.cn/xwdt/xwfb/", _parse_links(_LI)),
]
SOURCE_NAMES = [name for name, *_ in SOURCES]
# 模型常用的简称
_ALIASES = {"央行": "中国人民银行", "人民银行": "中国人民银行", "人行": "中国人民银行", "发改委": "国家发展改革委", "国家发改委": "国家发展改革委", "中国证监会": "证监会"}

# 缓存：(取数时刻, 全部条目, 没取到的机构)
_cache: tuple[float, list[Item], list[str]] | None = None
_lock = asyncio.Lock()


async def _fetch_one(client: httpx.AsyncClient, source: tuple) -> list[Item]:
    name, channel, url, parse = source
    resp = await client.get(url)
    resp.raise_for_status()
    items = [item for item in parse(resp, url) if item["title"] and item["url"].startswith("http")]
    if not items:
        raise ValueError("列表页里没有解析出任何条目，可能是网站改版")
    for item in items:
        item["source"] = f"{name}·{channel}"
    return items[:_KEEP_PER_SOURCE]


async def _fetch_all() -> tuple[list[Item], list[str]]:
    global _cache
    async with _lock:
        if _cache and time.monotonic() - _cache[0] < _CACHE_SECONDS:
            return _cache[1], _cache[2]
        async with httpx.AsyncClient(
            timeout=8, headers=_HEADERS, follow_redirects=True
        ) as client:
            results = await asyncio.gather(
                *(_fetch_one(client, source) for source in SOURCES), return_exceptions=True
            )
        items: list[Item] = []
        failed: list[str] = []
        for source, result in zip(SOURCES, results):
            if isinstance(result, BaseException):
                logger.warning("政策来源 %s 读取失败：%r", source[0], result)
                failed.append(source[0])
            else:
                items.extend(result)
        items.sort(key=lambda item: item["date"], reverse=True)
        # 全部失败时不缓存，下次提问立即重试
        if items:
            _cache = (time.monotonic(), items, failed)
        return items, failed


async def get_policy(source: str = "", keyword: str = "", limit: int = 8) -> ToolResult:
    limit = max(1, min(int(limit), 12))
    source, keyword = source.strip(), keyword.strip()
    source = _ALIASES.get(source, source)
    if source and source not in SOURCE_NAMES:
        raise ToolError(f"没有「{source}」这个来源，可选：{'、'.join(SOURCE_NAMES)}；留空表示全部。")

    items, failed = await _fetch_all()
    if not items:
        raise ToolError("各官方网站都暂时无法访问")
    if source in failed:
        raise ToolError(f"{source}官网暂时无法访问")

    picked = [
        item
        for item in items
        if (not source or item["source"].startswith(source))
        and (not keyword or keyword in item["title"])
    ]
    if not picked:
        raise ToolError(
            f"官方网站最近发布的内容里，没有标题包含「{keyword}」的。"
            "可以换一个更短的关键词，或不带关键词查看最新发布。"
        )
    picked = picked[:limit]

    today = datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    lines = "\n".join(
        f"{i}. [{item['title']}]({item['url']})（{item['date']}，{item['source']}）"
        for i, item in enumerate(picked, 1)
    )
    scope = (source or "各部委官网") + (f"标题含「{keyword}」的" if keyword else "最新的")
    notes = [
        "这里只有标题、日期和官网原文链接，没有正文：不得臆测文件的具体条款，"
        "需要细节时请用户点开原文。引用时必须带上 Markdown 链接（原样照抄）和发布日期。"
    ]
    if failed and not source:
        notes.append(f"以下来源本次没有取到，请如实告知用户：{'、'.join(failed)}。")
    text = f"{scope} {len(picked)} 条官方发布（今天是 {today}）。{' '.join(notes)}\n{lines}"
    return ToolResult(text=text)
