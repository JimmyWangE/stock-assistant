"""页面上的市场看板：指数、涨跌家数、行业板块、快讯、官方政策。与对话无关，只给页面展示用。

做法：后台任务定时刷新一份全站共用的快照，接口直接返回快照。
- 页面请求从不等待上游数据源，打开即有（服务刚启动的头几秒除外）。
- 无论多少人在线，对每个上游的请求频率都是固定的。
- 两分钟内没有人看页面时停止刷新。
- 每个板块独立：某个数据源取不到，只是那一块保留上一次的内容或不显示，不影响其他。
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import akshare as ak
import httpx
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from app import jsengine
from app.models import User
from app.security import current_user
from app.tools import market, policy
from app.tools.base import ToolError, ToolResult
from app.tools.market import SHANGHAI

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["市场看板"])

# 前 5 个显示在顶栏，全部显示在市场概览页
_INDEX_CODES = [
    "sh000001",
    "sz399001",
    "sz399006",
    "sh000300",
    "sh000688",
    "sh000016",
    "sh000905",
    "sh000852",
    "bj899050",
]
_IDLE_SECONDS = 120

# 全站共用的快照。各板块取到数据前是空值，页面据此决定是否显示
_board: dict[str, Any] = {
    "indices": [],
    "as_of": "",
    "sparks": {},
    "breadth": None,
    # 全市场统计：涨跌分布、涨幅榜、跌幅榜、成交额榜、两市总成交额
    "market": None,
    "sectors": None,
    "headlines": [],
    "policies": [],
}
_last_request = 0.0


async def _fetch_indices() -> None:
    """腾讯报价：每个代码一行，用 ~ 分隔，字段位置固定（与个股报价相同）。"""
    async with httpx.AsyncClient(timeout=4) as client:
        resp = await client.get(f"https://qt.gtimg.cn/q={','.join(_INDEX_CODES)}")
        resp.raise_for_status()
    indices = []
    as_of = ""
    for code, line in zip(_INDEX_CODES, resp.content.decode("gbk", errors="replace").split(";")):
        if '"' not in line:
            continue
        f = line.split('"')[1].split("~")
        if len(f) < 38 or not f[3]:
            continue
        indices.append(
            {
                "code": code,
                "name": f[1],
                "price": float(f[3]),
                "prev_close": float(f[4]),
                "open": float(f[5]),
                "high": float(f[33]),
                "low": float(f[34]),
                "change": float(f[31]),
                "percent": float(f[32]),
                "amount_yi": float(f[37]) / 1e4,  # 原始单位是万元
            }
        )
        as_of = max(as_of, datetime.strptime(f[30], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S"))
    if indices:
        _board["indices"], _board["as_of"] = indices, as_of


async def _fetch_sparks() -> None:
    """各指数当天的分时走势，画迷你走势线用。每 4 分钟取一个点，一天约 60 个点。"""
    sparks: dict[str, list[float]] = {}
    async with httpx.AsyncClient(timeout=6) as client:
        for code in _INDEX_CODES:
            resp = await client.get(
                f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}"
            )
            resp.raise_for_status()
            rows = resp.json()["data"][code]["data"]["data"]
            prices = [float(row.split(" ")[1]) for row in rows]
            if prices:
                sparks[code] = [*prices[:-1:4], prices[-1]]
    if sparks:
        _board["sparks"] = sparks


# 涨跌分布的分档（涨跌幅，%）。涨停、跌停单独计数，不进入分档
_BUCKETS = [
    (">7%", 7, None),
    ("5~7%", 5, 7),
    ("3~5%", 3, 5),
    ("0~3%", 0, 3),
    ("平", None, None),
    ("-3~0%", -3, 0),
    ("-5~-3%", -5, -3),
    ("-7~-5%", -7, -5),
    ("<-7%", None, -7),
]


def _bucket(percent: float) -> str:
    if percent == 0:
        return "平"
    for label, low, high in _BUCKETS:
        if label == "平":
            continue
        if (low is None or percent > low) and (high is None or percent <= high):
            return label
    return "<-7%"


def _market_stats(quotes: list[list[str]]) -> tuple[dict, dict]:
    """由全市场逐只报价统计涨跌家数、涨跌分布和各类排行。字段含义见 market.fetch_quote_fields。"""
    rows: list[dict] = []
    limit_up = limit_down = 0
    counts = {label: 0 for label, _, _ in _BUCKETS}
    as_of = ""
    for f in quotes:
        if len(f) < 49 or not f[3]:
            continue
        price, prev, volume = float(f[3]), float(f[4]), float(f[6] or 0)
        # 没有成交的视为停牌，不计入统计
        if price <= 0 or prev <= 0 or volume == 0:
            continue
        percent = round((price - prev) / prev * 100, 2)
        is_up_limit = bool(f[47]) and price >= float(f[47])
        is_down_limit = bool(f[48]) and price <= float(f[48])
        if is_up_limit:
            limit_up += 1
        elif is_down_limit:
            limit_down += 1
        else:
            counts[_bucket(percent)] += 1
        rows.append(
            {
                "code": f[2],
                "name": f[1],
                "price": price,
                "percent": percent,
                "amount_yi": round(float(f[37] or 0) / 1e4, 2),
                "turnover": float(f[38] or 0),
            }
        )
        as_of = max(as_of, f[30])
    if len(rows) < 1000:
        raise ValueError(f"只统计到 {len(rows)} 只股票，数据不完整")

    up = sum(1 for r in rows if r["percent"] > 0)
    down = sum(1 for r in rows if r["percent"] < 0)
    stamp = datetime.strptime(as_of, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M")
    breadth = {
        "up": up,
        "down": down,
        "flat": len(rows) - up - down,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "as_of": stamp,
    }
    distribution = [{"label": "涨停", "count": limit_up}]
    distribution += [{"label": label, "count": counts[label]} for label, _, _ in _BUCKETS]
    distribution.append({"label": "跌停", "count": limit_down})
    by_percent = sorted(rows, key=lambda r: r["percent"])
    stats = {
        "distribution": distribution,
        "gainers": by_percent[::-1][:10],
        "losers": by_percent[:10],
        "active": sorted(rows, key=lambda r: r["amount_yi"], reverse=True)[:10],
        "turnover_yi": round(sum(r["amount_yi"] for r in rows), 0),
        "count": len(rows),
        "as_of": stamp,
    }
    return breadth, stats


async def _market_from_tencent() -> tuple[dict, dict]:
    return _market_stats(await market.fetch_quote_fields(market.all_codes()))


async def _breadth_from_legu() -> dict:
    df = await asyncio.to_thread(ak.stock_market_activity_legu)
    values = dict(zip(df["item"], df["value"]))
    return {
        "up": int(values["上涨"]),
        "down": int(values["下跌"]),
        "flat": int(values["平盘"]),
        "limit_up": int(values["涨停"]),
        "limit_down": int(values["跌停"]),
        "as_of": str(values.get("统计日期", ""))[:16],
    }


async def _fetch_market() -> None:
    """全市场统计：用腾讯报价自己统计；不可用时涨跌家数退到乐咕乐股（经 AkShare），其余不显示。

    服务器上乐咕乐股的页面取不到表格，而腾讯报价在服务器上一直可用，所以以腾讯为主。
    """
    try:
        _board["breadth"], _board["market"] = await _market_from_tencent()
    except Exception as exc:  # noqa: BLE001 换备用来源
        logger.info("涨跌家数改用备用来源，腾讯报价统计失败：%r", exc)
        _board["breadth"] = await _breadth_from_legu()


async def _fetch_sectors() -> None:
    """同花顺行业板块：全部约 90 个行业的涨跌幅、资金净流入和领涨股。"""
    df = await asyncio.to_thread(jsengine.call, ak.stock_board_industry_summary_ths)
    df = df.sort_values("涨跌幅", ascending=False)

    def rows(part: pd.DataFrame) -> list[dict]:
        return [
            {
                "name": str(r["板块"]),
                "percent": float(r["涨跌幅"]),
                "leader": str(r["领涨股"]),
                "leader_percent": float(r["领涨股-涨跌幅"]),
                "inflow_yi": float(r["净流入"]),
                "up": int(r["上涨家数"]),
                "down": int(r["下跌家数"]),
            }
            for _, r in part.iterrows()
        ]

    _board["sectors"] = {
        "top": rows(df.head(10)),
        "bottom": rows(df.tail(10).iloc[::-1]),
        "all": rows(df),
    }


async def _fetch_headlines() -> None:
    df = await asyncio.to_thread(ak.stock_news_global_em)
    df = df.copy()
    df["发布时间"] = pd.to_datetime(df["发布时间"], errors="coerce")
    df = df.dropna(subset=["发布时间"]).sort_values("发布时间", ascending=False).head(20)
    _board["headlines"] = [
        {
            "title": str(r["标题"]),
            "url": str(r["链接"]),
            "time": r["发布时间"].strftime("%m-%d %H:%M"),
        }
        for _, r in df.iterrows()
    ]


async def _fetch_policies() -> None:
    items, _failed = await policy._fetch_all()
    if items:
        _board["policies"] = [
            {
                "title": item["title"],
                "url": item["url"],
                "time": item["date"][5:],
                "source": item["source"].split("·")[0],
            }
            for item in items[:20]
        ]


# （名称，刷新间隔秒，取数函数）
_JOBS: list[tuple[str, float, Callable[[], Awaitable[None]]]] = [
    ("指数", 5, _fetch_indices),
    ("分时", 60, _fetch_sparks),
    ("全市场统计", 30, _fetch_market),
    ("行业板块", 120, _fetch_sectors),
    ("快讯", 60, _fetch_headlines),
    ("官方政策", 600, _fetch_policies),
]


async def _run(name: str, fetch: Callable[[], Awaitable[None]], failing: set[str]) -> None:
    try:
        await asyncio.wait_for(fetch(), timeout=20)
        failing.discard(name)
    except Exception as exc:  # noqa: BLE001 看板只是辅助信息，任何一块取不到都不能影响服务
        # 同一个数据源连续失败时只记一次，避免刷屏
        if name not in failing:
            logger.warning("市场看板「%s」取数失败：%r", name, exc)
            failing.add(name)


async def keep_board_fresh() -> None:
    """后台任务：有人在看页面时，按各自的间隔刷新看板的每个板块。"""
    due = {name: 0.0 for name, _, _ in _JOBS}
    failing: set[str] = set()
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        if now - _last_request > _IDLE_SECONDS:
            continue
        ready = [(name, fetch) for name, interval, fetch in _JOBS if now >= due[name]]
        for name, interval, _ in _JOBS:
            if now >= due[name]:
                due[name] = now + interval
        if ready:
            await asyncio.gather(*(_run(name, fetch, failing) for name, fetch in ready))


def _session() -> str:
    """按时间粗略判断交易状态。不含节假日日历：节假日靠行情时间的日期不是今天来识别。"""
    now = datetime.now(SHANGHAI)
    if now.weekday() >= 5 or not _board["as_of"].startswith(now.strftime("%Y-%m-%d")):
        return "休市" if now.weekday() >= 5 or now.hour >= 10 else "未开盘"
    minutes = now.hour * 60 + now.minute
    if minutes < 9 * 60 + 30:
        return "未开盘"
    if minutes < 11 * 60 + 30:
        return "交易中"
    if minutes < 13 * 60:
        return "午间休市"
    if minutes < 15 * 60:
        return "交易中"
    return "已收盘"


@router.get("/board")
async def board(_: User = Depends(current_user)) -> dict:
    """市场看板快照。立即返回，不等待上游；板块没有数据时为空值。"""
    global _last_request
    _last_request = time.monotonic()
    return {**_board, "session": _session()}


@router.get("/ticker")
async def ticker() -> dict:
    """登录页用的指数行情，不需要登录。只含公开的指数点位，不含任何用户数据。"""
    global _last_request
    _last_request = time.monotonic()
    return {"indices": _board["indices"][:5], "as_of": _board["as_of"], "session": _session()}


# 指数详情缓存：代码 -> (取数时刻, 结果)
_detail_cache: dict[str, tuple[float, dict]] = {}


def _parse_minutes(rows: list[str]) -> list[list]:
    """分时数据每行"时间 价格 累计成交量 [累计成交额]"，转成每分钟的成交量。"""
    minutes = []
    last_volume = 0.0
    for row in rows:
        parts = row.split(" ")
        volume = float(parts[2])
        minutes.append([f"{parts[0][:2]}:{parts[0][2:]}", float(parts[1]), max(volume - last_volume, 0)])
        last_volume = volume
    return minutes


@router.get("/index/{code}")
async def index_detail(code: str, _: User = Depends(current_user)) -> dict:
    """单个指数的当日分时和最近 120 个交易日的日 K。同一指数 15 秒内只取一次。"""
    if code not in _INDEX_CODES:
        raise HTTPException(status_code=404, detail="不支持的指数")
    hit = _detail_cache.get(code)
    if hit and time.monotonic() - hit[0] < 15:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            minute_resp, day_bars = await asyncio.gather(
                client.get(f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}"),
                market.fetch_day_bars(client, code, 120),
            )
        minute = minute_resp.json()["data"][code]
        quote = minute["qt"][code]
        date = minute["data"]["date"]
        result = {
            "code": code,
            "name": quote[1],
            "price": float(quote[3]),
            "prev_close": float(quote[4]),
            "open": float(quote[5]),
            "high": float(quote[33]),
            "low": float(quote[34]),
            "change": float(quote[31]),
            "percent": float(quote[32]),
            "amount_yi": float(quote[37]) / 1e4,
            "as_of": datetime.strptime(quote[30], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
            "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
            "minutes": _parse_minutes(minute["data"]["data"]),
            # 与个股 K 线图同一格式：[日期, 开, 收, 低, 高, 成交量（股）]；接口给的成交量单位是手
            "bars": [
                [d[0], float(d[1]), float(d[2]), float(d[4]), float(d[3]), float(d[5]) * 100]
                for d in day_bars
            ],
            "source": {"name": "腾讯财经", "url": f"https://gu.qq.com/{code}/zs"},
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("指数详情 %s 取数失败：%r", code, exc)
        raise HTTPException(status_code=502, detail="指数数据暂时取不到，请稍后重试") from exc
    _detail_cache[code] = (time.monotonic(), result)
    return result


async def _ensure_fresh(max_age: float = 60) -> None:
    """模型要用看板数据时，若后台刷新已停（没人看页面）或数据还没取到，就现取一次。"""
    global _last_request
    idle = time.monotonic() - _last_request > _IDLE_SECONDS
    _last_request = time.monotonic()
    if idle or not _board["indices"] or not _board["market"] or not _board["sectors"]:
        failing: set[str] = set()
        await asyncio.gather(
            _run("指数", _fetch_indices, failing),
            _run("全市场统计", _fetch_market, failing),
            _run("行业板块", _fetch_sectors, failing),
        )


async def get_market_overview() -> ToolResult:
    """大盘概况，给模型做市场复盘、指数解读用。数字来自看板快照。"""
    await _ensure_fresh()
    if not _board["indices"]:
        raise ToolError("大盘指数暂时取不到")
    lines = [f"A 股大盘概况，行情时间 {_board['as_of']}（北京时间），交易状态：{_session()}"]
    # 模型上下文有限：只有上证指数给出开高低，其余指数只给点位和涨跌幅
    # 高开/低开由程序判断后写明，不让模型自己比较开盘价和昨收（服务器实测模型会说反）
    first = _board["indices"][0]
    gap = (first["open"] - first["prev_close"]) / first["prev_close"] * 100
    opening = "高开" if gap > 0 else "低开" if gap < 0 else "平开"
    lines.append(
        f"{first['name']} 收于/现报 {first['price']:.2f}，涨跌幅 {first['percent']:+.2f}%；"
        f"昨收 {first['prev_close']:.2f}，今开 {first['open']:.2f}（{opening} {gap:+.2f}%），"
        f"最高 {first['high']:.2f}，最低 {first['low']:.2f}"
    )
    lines.append(
        "其他指数："
        + "，".join(f"{i['name']} {i['price']:.2f}（{i['percent']:+.2f}%）" for i in _board["indices"][1:])
    )
    b, m = _board["breadth"], _board["market"]
    if b:
        lines.append(
            f"涨跌家数（含北交所）：上涨 {b['up']}，下跌 {b['down']}，平盘 {b['flat']}，"
            f"涨停 {b['limit_up']}，跌停 {b['limit_down']}"
        )
    if m:
        lines.append(f"沪深京三市成交额 {m['turnover_yi']:.0f} 亿元")
        # 分档标签写成"涨…/跌…"的文字，避免模型把 3~5% 这类正数档读成下跌（服务器实测出现过）
        dist = {d["label"]: d["count"] for d in m["distribution"]}
        lines.append(
            f"上涨家数按涨幅分档：涨停 {dist['涨停']}，涨超 7% {dist['>7%']}，涨 5%~7% {dist['5~7%']}，"
            f"涨 3%~5% {dist['3~5%']}，涨 0~3% {dist['0~3%']}；平盘 {dist['平']}"
        )
        lines.append(
            f"下跌家数按跌幅分档：跌 0~3% {dist['-3~0%']}，跌 3%~5% {dist['-5~-3%']}，"
            f"跌 5%~7% {dist['-7~-5%']}，跌超 7% {dist['<-7%']}，跌停 {dist['跌停']}"
        )
        lines.append("成交额前五：" + "，".join(f"{r['name']}（{r['percent']:+.2f}%，{r['amount_yi']:.0f} 亿）" for r in m["active"][:5]))
    s = _board["sectors"]
    if s:
        fmt = lambda r: f"{r['name']}（{r['percent']:+.2f}%，净流入 {r['inflow_yi']:+.1f} 亿，领涨 {r['leader']}）"  # noqa: E731
        # 排名和"最强/最弱"由程序写明。服务器实测：保险涨幅第一、银行第二，模型却写"银行板块表现最强"
        every = s["all"]
        rising = sum(1 for r in every if r["percent"] > 0)
        falling = sum(1 for r in every if r["percent"] < 0)
        best, worst = s["top"][0], s["bottom"][0]
        lines.append(
            f"行业板块共 {len(every)} 个，上涨 {rising} 个、下跌 {falling} 个。"
            f"按涨跌幅，今日表现最强的行业是 {best['name']}（{best['percent']:+.2f}%），"
            f"最弱的是 {worst['name']}（{worst['percent']:+.2f}%）"
        )
        lines.append(
            "行业涨跌幅从高到低第 1 至 5 名："
            + "，".join(f"第 {i} 名 {fmt(r)}" for i, r in enumerate(s["top"][:5], 1))
        )
        lines.append(
            "行业涨跌幅从低到高第 1 至 5 名："
            + "，".join(f"第 {i} 名 {fmt(r)}" for i, r in enumerate(s["bottom"][:5], 1))
        )
        inflow = sorted(every, key=lambda r: r["inflow_yi"], reverse=True)
        lines.append(
            "按资金净流入排序（与涨跌幅排名无关）：净流入最多的三个行业 "
            + "，".join(f"{r['name']} {r['inflow_yi']:+.1f} 亿" for r in inflow[:3])
            + "；净流出最多的三个行业 "
            + "，".join(f"{r['name']} {r['inflow_yi']:+.1f} 亿" for r in inflow[::-1][:3])
        )
    lines.append(
        "来源（请原样写在回答末尾）：[腾讯财经·沪深行情](https://gu.qq.com/sh000001/zs)、"
        "[同花顺·行业板块](https://q.10jqka.com.cn/thshy/)"
    )
    return ToolResult(text="\n".join(lines))
