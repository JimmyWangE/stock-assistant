"""自选股与异动提醒（站内）。

提醒由后台任务产生，每类事件每只股票每天最多提醒一次：
- 涨跌幅：交易时段每 30 秒检查一次，涨幅或跌幅达到该股设定的阈值（默认 5%）。
- 涨停、跌停：现价触及涨停价或跌停价。
- 新公告：每 5 分钟查一次自选股的公告（东方财富），只提醒加入自选之后发布的。
- 火眼金睛：交易日 9:35 后，自选股出现在当天定格的名单里。
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from app import hawkeye, tradedays
from app.db import SessionLocal
from app.models import Alert, ScreenData, User, WatchItem, now
from app.security import current_user
from app.stock import fetch_announcements, parse_quote
from app.tools import market
from app.tools.base import ToolError
from app.tools.market import SHANGHAI, _exchange_prefix, resolve_stock

logger = logging.getLogger(__name__)
router = APIRouter(tags=["自选股"])

MAX_ITEMS = 100
KEEP_ALERT_DAYS = 30
# 例行披露（A+H 股每天的股份变动报表等）不提醒，否则会天天刷屏
_ROUTINE = re.compile(r"翌日披露报表|证券变动月报表")


class WatchIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)


class WatchPatch(BaseModel):
    alert_pct: float = Field(ge=1, le=20)


def _item_out(item: WatchItem, quote: dict | None) -> dict:
    return {"code": item.code, "name": item.name, "alert_pct": item.alert_pct, "quote": quote}


async def _quotes(codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    rows = await market.fetch_quote_fields([_exchange_prefix(c) + c for c in codes])
    return {f[2]: parse_quote(f) for f in rows if len(f) > 49 and f[3]}


@router.get("/api/watchlist")
async def list_items(user: User = Depends(current_user)) -> list[dict]:
    async with SessionLocal() as db:
        items = list(
            await db.scalars(select(WatchItem).where(WatchItem.user_id == user.id).order_by(WatchItem.id))
        )
    try:
        quotes = await _quotes([i.code for i in items])
    except Exception as exc:  # noqa: BLE001 行情取不到时仍返回名单
        logger.warning("自选股行情取不到：%r", exc)
        quotes = {}
    return [_item_out(i, quotes.get(i.code)) for i in items]


@router.post("/api/watchlist")
async def add_item(body: WatchIn, user: User = Depends(current_user)) -> dict:
    try:
        code, name = resolve_stock(body.symbol)
    except ToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    async with SessionLocal() as db:
        existing = await db.scalar(
            select(WatchItem).where(WatchItem.user_id == user.id, WatchItem.code == code)
        )
        if existing:
            return _item_out(existing, None)
        count = await db.scalar(select(func.count()).select_from(WatchItem).where(WatchItem.user_id == user.id))
        if count >= MAX_ITEMS:
            raise HTTPException(status_code=409, detail=f"自选股最多 {MAX_ITEMS} 只")
        item = WatchItem(user_id=user.id, code=code, name=name, alert_pct=5.0)
        db.add(item)
        await db.commit()
    return _item_out(item, None)


@router.patch("/api/watchlist/{code}")
async def set_threshold(code: str, body: WatchPatch, user: User = Depends(current_user)) -> dict:
    async with SessionLocal() as db:
        item = await db.scalar(select(WatchItem).where(WatchItem.user_id == user.id, WatchItem.code == code))
        if item is None:
            raise HTTPException(status_code=404, detail="不在自选股里")
        item.alert_pct = round(body.alert_pct, 1)
        await db.commit()
    return _item_out(item, None)


@router.delete("/api/watchlist/{code}", status_code=204)
async def remove_item(code: str, user: User = Depends(current_user)) -> Response:
    async with SessionLocal() as db:
        await db.execute(delete(WatchItem).where(WatchItem.user_id == user.id, WatchItem.code == code))
        await db.commit()
    return Response(status_code=204)


@router.get("/api/alerts")
async def list_alerts(user: User = Depends(current_user)) -> dict:
    """最近 50 条提醒和未读数。"""
    async with SessionLocal() as db:
        rows = list(
            await db.scalars(
                select(Alert).where(Alert.user_id == user.id).order_by(Alert.id.desc()).limit(50)
            )
        )
        unread = await db.scalar(
            select(func.count()).select_from(Alert).where(Alert.user_id == user.id, Alert.read.is_(False))
        )
    return {
        "unread": unread,
        "items": [
            {
                "id": a.id,
                "code": a.code,
                "name": a.name,
                "kind": a.kind,
                "message": a.message,
                "url": a.url,
                "read": a.read,
                "created_at": _as_utc(a.created_at).isoformat(),
            }
            for a in rows
        ],
    }


@router.post("/api/alerts/read")
async def mark_read(user: User = Depends(current_user)) -> dict:
    async with SessionLocal() as db:
        await db.execute(
            update(Alert).where(Alert.user_id == user.id, Alert.read.is_(False)).values(read=True)
        )
        await db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------- 后台检查


def _as_utc(value: datetime) -> datetime:
    # SQLite 读回来的时间不带时区
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _in_session(now_sh: datetime) -> bool:
    hm = now_sh.hour * 60 + now_sh.minute
    return 9 * 60 + 30 <= hm <= 11 * 60 + 31 or 13 * 60 <= hm <= 15 * 60 + 1


async def _save_alerts(candidates: list[Alert]) -> int:
    """写入提醒，已经提醒过的（同一用户同一去重键）跳过。"""
    if not candidates:
        return 0
    async with SessionLocal() as db:
        keys = {a.dedupe for a in candidates}
        existing = set(
            (await db.execute(select(Alert.user_id, Alert.dedupe).where(Alert.dedupe.in_(keys)))).all()
        )
        fresh, seen = [], set()
        for a in candidates:
            key = (a.user_id, a.dedupe)
            if key in existing or key in seen:
                continue
            seen.add(key)
            fresh.append(a)
        db.add_all(fresh)
        await db.commit()
    return len(fresh)


def _alert(item: WatchItem, kind: str, message: str, dedupe: str, url: str | None = None) -> Alert:
    return Alert(
        user_id=item.user_id, code=item.code, name=item.name, kind=kind,
        message=message[:300], url=url, dedupe=dedupe, read=False, created_at=now(),
    )


def _price_alerts(items: list[WatchItem], quotes: dict[str, dict], day: str) -> list[Alert]:
    out = []
    for item in items:
        q = quotes.get(item.code)
        if not q or not q["price"] or q["percent"] is None:
            continue
        pct, price = q["percent"], q["price"]
        if q["limit_up"] and price >= q["limit_up"]:
            out.append(_alert(item, "涨停", f"{item.name} 涨停，现价 {price:.2f}（{pct:+.2f}%）", f"{item.code}:zt:{day}"))
        elif q["limit_down"] and price <= q["limit_down"]:
            out.append(_alert(item, "跌停", f"{item.name} 跌停，现价 {price:.2f}（{pct:+.2f}%）", f"{item.code}:dt:{day}"))
        if pct >= item.alert_pct:
            out.append(
                _alert(item, "涨幅", f"{item.name} 涨幅 {pct:+.2f}%，达到提醒阈值 {item.alert_pct:g}%，现价 {price:.2f}",
                       f"{item.code}:up:{day}")
            )
        elif pct <= -item.alert_pct:
            out.append(
                _alert(item, "跌幅", f"{item.name} 跌幅 {pct:+.2f}%，达到提醒阈值 {item.alert_pct:g}%，现价 {price:.2f}",
                       f"{item.code}:down:{day}")
            )
    return out


async def _announcement_alerts(items: list[WatchItem]) -> list[Alert]:
    codes = sorted({i.code for i in items})
    notices = []
    for i in range(0, len(codes), 50):
        notices.extend(await fetch_announcements(codes[i : i + 50], 100))
    by_code: dict[str, list[WatchItem]] = {}
    for item in items:
        by_code.setdefault(item.code, []).append(item)
    since_floor = datetime.now(SHANGHAI) - timedelta(days=1)
    out = []
    for n in notices:
        try:
            shown = datetime.strptime(n["time"], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
        title = n["title"]
        if _ROUTINE.search(title):
            continue
        tag = "风险类" if hawkeye._NEGATIVE.search(title) else ""
        if not tag and not hawkeye._FOLLOW_UP.search(title) and not hawkeye._NOT_BUSINESS.search(title):
            if any(p.search(title) for _, p, _ in hawkeye._POSITIVE):
                tag = "利好类"
        for item in by_code.get(n["code"], []):
            # 只提醒加入自选之后、且一天以内发布的公告，避免刚加入时涌出一堆旧公告
            if shown < max(_as_utc(item.created_at), since_floor):
                continue
            label = f"【{tag}】" if tag else ""
            out.append(_alert(item, "公告", f"{item.name} 发布公告{label}：{title}", f"{item.code}:ann:{n['id']}", n["url"]))
    return out


async def _hawkeye_alerts(items: list[WatchItem], day: str) -> list[Alert] | None:
    """返回 None 表示今天的名单还没定格，下一轮再查。"""
    await hawkeye.latest()
    async with SessionLocal() as db:
        frozen = await db.get(ScreenData, f"hawkeye:{day}")
    if frozen is None:
        return None
    picks = {p["code"]: p for p in frozen.payload["picks"]}
    out = []
    for item in items:
        p = picks.get(item.code)
        if p:
            kinds = "、".join(p.get("kinds", []))
            out.append(
                _alert(item, "火眼金睛", f"{item.name} 入选今日火眼金睛（{p['stars']} 星，{kinds}）",
                       f"{item.code}:hawkeye:{day}", "/hawkeye")
            )
    return out


async def keep_watching() -> None:
    """后台任务：盘中每 30 秒查一次涨跌幅，每 5 分钟查一次公告；每天清理 30 天前的提醒。"""
    last_notice = 0.0
    hawkeye_done = ""
    last_purge = ""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(30)
        try:
            now_sh = datetime.now(SHANGHAI)
            day = now_sh.strftime("%Y-%m-%d")
            async with SessionLocal() as db:
                items = list(await db.scalars(select(WatchItem)))
            trading = await tradedays.is_trading_day(now_sh.date())

            candidates: list[Alert] = []
            if items and trading and _in_session(now_sh):
                quotes = await _quotes(sorted({i.code for i in items}))
                # 行情时间不是今天（如临时停市）时不提醒
                quotes = {c: q for c, q in quotes.items() if q["as_of"].startswith(day)}
                candidates += _price_alerts(items, quotes, day)
            if items and loop.time() - last_notice > 300 and 7 <= now_sh.hour < 23:
                last_notice = loop.time()
                candidates += await _announcement_alerts(items)
            if trading and hawkeye_done != day and (now_sh.hour, now_sh.minute) >= (9, 36) and now_sh.hour < 15:
                found = await _hawkeye_alerts(items, day)
                if found is not None:
                    hawkeye_done = day
                    candidates += found
            saved = await _save_alerts(candidates)
            if saved:
                logger.info("自选股提醒：新增 %d 条", saved)

            if last_purge != day:
                last_purge = day
                cutoff = now() - timedelta(days=KEEP_ALERT_DAYS)
                async with SessionLocal() as db:
                    await db.execute(delete(Alert).where(Alert.created_at < cutoff))
                    await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 某一轮失败不影响下一轮
            logger.exception("自选股提醒检查失败")
            await asyncio.sleep(60)
