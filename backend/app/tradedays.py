"""交易日历：判断某天是不是 A 股交易日。

日历取自新浪财经（经 AkShare），交易所每年年初公布全年休市安排，所以包含今年余下的日期。
每天刷新一次；取不到时退回"周一到周五都是交易日"，节假日可能误判，但不影响其他功能。
"""

import asyncio
import logging
import time
from datetime import date, datetime

import akshare as ak

from app.tools.market import SHANGHAI

logger = logging.getLogger(__name__)

_days: tuple[float, set[str]] | None = None
_lock = asyncio.Lock()


def _fetch() -> set[str]:
    df = ak.calendar_trade_date_hist_sina()
    return {str(d)[:10] for d in df["trade_date"]}


async def is_trading_day(day: date | None = None) -> bool:
    global _days
    day = day or datetime.now(SHANGHAI).date()
    async with _lock:
        if _days is None or time.monotonic() - _days[0] > 12 * 3600:
            try:
                fresh = await asyncio.to_thread(_fetch)
                if len(fresh) > 1000:
                    _days = (time.monotonic(), fresh)
            except Exception as exc:  # noqa: BLE001
                logger.warning("交易日历取不到，按工作日判断：%r", exc)
                # 一小时后再试
                _days = (time.monotonic() - 11 * 3600, _days[1] if _days else set())
    known = _days[1] if _days else set()
    key = day.isoformat()
    # 日历里没有今年的日期（如跨年后尚未更新）时，按工作日判断
    if not any(d.startswith(key[:4]) for d in known):
        return day.weekday() < 5
    return key in known
