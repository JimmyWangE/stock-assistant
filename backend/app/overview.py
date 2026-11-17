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
from fastapi import APIRouter, Depends

from app.models import User
from app.security import current_user
from app.tools import policy
from app.tools.market import SHANGHAI

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["市场看板"])

_INDEX_CODES = ["sh000001", "sz399001", "sz399006", "sh000300", "sh000688"]
_IDLE_SECONDS = 120

# 全站共用的快照。各板块取到数据前是空值，页面据此决定是否显示
_board: dict[str, Any] = {
    "indices": [],
    "as_of": "",
    "sparks": {},
    "breadth": None,
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


async def _fetch_breadth() -> None:
    df = await asyncio.to_thread(ak.stock_market_activity_legu)
    values = dict(zip(df["item"], df["value"]))
    _board["breadth"] = {
        "up": int(values["上涨"]),
        "down": int(values["下跌"]),
        "flat": int(values["平盘"]),
        "limit_up": int(values["涨停"]),
        "limit_down": int(values["跌停"]),
        "as_of": str(values.get("统计日期", ""))[:16],
    }


async def _fetch_sectors() -> None:
    df = await asyncio.to_thread(ak.stock_board_industry_summary_ths)
    df = df.sort_values("涨跌幅", ascending=False)

    def rows(part: pd.DataFrame) -> list[dict]:
        return [
            {"name": str(r["板块"]), "percent": float(r["涨跌幅"]), "leader": str(r["领涨股"])}
            for _, r in part.iterrows()
        ]

    _board["sectors"] = {"top": rows(df.head(5)), "bottom": rows(df.tail(5).iloc[::-1])}


async def _fetch_headlines() -> None:
    df = await asyncio.to_thread(ak.stock_news_global_em)
    df = df.copy()
    df["发布时间"] = pd.to_datetime(df["发布时间"], errors="coerce")
    df = df.dropna(subset=["发布时间"]).sort_values("发布时间", ascending=False).head(12)
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
            for item in items[:12]
        ]


# （名称，刷新间隔秒，取数函数）
_JOBS: list[tuple[str, float, Callable[[], Awaitable[None]]]] = [
    ("指数", 5, _fetch_indices),
    ("分时", 60, _fetch_sparks),
    ("涨跌家数", 60, _fetch_breadth),
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
