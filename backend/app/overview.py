"""页面顶部的大盘指数条。与对话无关，只给页面展示用。"""

import asyncio
import logging
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends

from app.models import User
from app.security import current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["大盘"])

_SYMBOLS = "sh000001,sz399001,sz399006,sh000300,sh000688"
# 所有用户共用一份结果：无论多少人在线，最多每 5 秒向上游请求一次
_CACHE_SECONDS = 5
_cache: tuple[float, dict] | None = None
_lock = asyncio.Lock()


def _parse(body: str) -> dict:
    """腾讯报价每个代码一行，用 ~ 分隔，字段位置固定（与个股报价相同）。"""
    indices = []
    as_of = ""
    for line in body.split(";"):
        if '"' not in line:
            continue
        f = line.split('"')[1].split("~")
        if len(f) < 33 or not f[3]:
            continue
        indices.append(
            {"name": f[1], "price": float(f[3]), "change": float(f[31]), "percent": float(f[32])}
        )
        as_of = max(as_of, datetime.strptime(f[30], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S"))
    return {"indices": indices, "as_of": as_of}


@router.get("/indices")
async def indices(_: User = Depends(current_user)) -> dict:
    """主要指数的最新点位和涨跌幅。取不到时返回空列表，页面隐藏指数条，不报错。"""
    global _cache
    async with _lock:
        if _cache and time.monotonic() - _cache[0] < _CACHE_SECONDS:
            return _cache[1]
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"https://qt.gtimg.cn/q={_SYMBOLS}")
                resp.raise_for_status()
            data = _parse(resp.content.decode("gbk", errors="replace"))
        except Exception:  # noqa: BLE001 指数条只是装饰，取不到不影响使用
            logger.warning("大盘指数接口不可用")
            data = {"indices": [], "as_of": ""}
        _cache = (time.monotonic(), data)
        return data
