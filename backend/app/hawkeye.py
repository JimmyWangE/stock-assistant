"""火眼金睛：从昨天收盘以来的公告里找出重大利好，再用开盘表现确认，给出当日值得关注的股票。

评分 = 利好强度（公告类型、业绩预增幅度）+ 盘面确认（高开幅度、量比、开盘后是否站稳）
     − 风险扣分（同期的减持、处罚等负面公告，一字涨停买不进，市值过小）。
规则全部写在本文件里、可核对；不调用模型，也不做任何"一定上涨"的判断。

每天 9:35 后第一次计算的结果"定格"存库，之后可以回看每天入选股票从当天开盘到现在的表现，
用来检验规则是否有效。
"""

import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

import akshare as ak
import httpx
import pandas as pd
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ScreenData, User, now
from app.security import current_user
from app.tools import market
from app.tools.market import SHANGHAI

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hawkeye", tags=["火眼金睛"])

# 只看首次披露的实质内容；律师意见、核查意见、进展、修订稿等是同一事项的后续文件，不重复计分
_FOLLOW_UP = re.compile(
    r"意见书|核查意见|财务顾问|问询|回复|进展|实施完毕|完成|结果|调整|解除|注销|摘要|修订|更正|补充|"
    r"提示性|说明|延期|取消|终止"
)

# （类别，标题规则，分值）。同一只股票命中多条时取各类别最高分相加
_POSITIVE: list[tuple[str, re.Pattern, int]] = [
    ("重大合同/中标", re.compile(r"中标|签订.*合同|重大合同|签署.*(合同|订单)"), 20),
    ("重组/收购", re.compile(r"(重大资产重组|发行股份购买资产).*(预案|草案)|收购.*控制权|控制权.*变更|筹划.*(重组|收购)"), 20),
    # 临床试验获批要排在"获批"前面，否则会被当成上市获批
    ("临床试验获批", re.compile(r"临床试验.*(批准|许可)"), 8),
    ("新药/器械获批", re.compile(r"获得.*(批准|注册证)|获批上市|药品注册证书"), 18),
    ("控股股东增持", re.compile(r"(控股股东|实际控制人|董事长).*增持.*计划|增持.*计划"), 15),
    ("回购方案", re.compile(r"回购.*(方案|预案)"), 12),
    ("股权激励", re.compile(r"激励计划[（(]草案[）)]"), 8),
]
_NEGATIVE = re.compile(
    r"减持|立案|行政处罚|警示函|监管函|风险提示|退市|重大诉讼|被冻结|业绩预亏|预减|首亏|终止(收购|重组|发行)"
)

_cache: tuple[float, dict] | None = None
_lock = asyncio.Lock()
_FREEZE_PREFIX = "hawkeye:"


def _phase(now_sh: datetime, trading_today: bool) -> str:
    if not trading_today:
        return "休市"
    hm = now_sh.hour * 60 + now_sh.minute
    if hm < 9 * 60 + 15:
        return "盘前"
    if hm < 9 * 60 + 30:
        return "集合竞价"
    if hm < 15 * 60:
        return "盘中"
    return "收盘后"


async def _trading_days(client: httpx.AsyncClient) -> list[str]:
    """最近几个交易日（由上证指数日 K 得到，自动避开节假日）。"""
    bars = await market.fetch_day_bars(client, "sh000001", 5)
    return [b[0] for b in bars]


def _window(days: list[str], today: str, preview: bool) -> tuple[list[str], str]:
    """要看的公告日期：上一个交易日到今天之间的每个自然日（含周末发布的公告）。
    收盘后和休市时看的是"下一个交易日"：从最近一个交易日起算。"""
    previous = days[-1] if preview or days[-1] != today else days[-2]
    start = date.fromisoformat(previous)
    span = (date.fromisoformat(today) - start).days
    return [(start + timedelta(d)).strftime("%Y%m%d") for d in range(span + 1)], previous


def _fetch_announcements(dates: list[str]) -> pd.DataFrame:
    frames = []
    for d in dates:
        try:
            frames.append(ak.stock_notice_report(symbol="全部", date=d))
        except Exception:  # noqa: BLE001 某天没有公告时接口会报错
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fetch_forecasts(dates: list[str]) -> pd.DataFrame:
    """业绩预告：只取窗口期内发布的预增、扭亏（归母净利润口径）。"""
    today = datetime.now(SHANGHAI).date()
    periods = {f"{today.year}1231", f"{today.year - 1}1231"}
    q_end = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[(today.month - 1) // 3 + 1]
    periods.add(f"{today.year}{q_end}")
    wanted = {f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dates}
    frames = []
    for period in periods:
        try:
            df = ak.stock_yjyg_em(date=period)
        except Exception:  # noqa: BLE001
            continue
        df = df[df["公告日期"].astype(str).str[:10].isin(wanted)]
        frames.append(df[(df["预测指标"] == "归属于上市公司股东的净利润") & df["预告类型"].isin(["预增", "扭亏"])])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _catalysts(notices: pd.DataFrame, forecasts: pd.DataFrame) -> dict[str, dict]:
    """按股票汇总利好与负面公告。"""
    stocks: dict[str, dict] = {}

    def entry(code: str, name: str) -> dict:
        return stocks.setdefault(code, {"name": name, "best": {}, "items": [], "warnings": []})

    for _, row in notices.iterrows():
        code, title = str(row["代码"]), str(row["公告标题"])
        body = title.split(":", 1)[-1]
        if _NEGATIVE.search(body):
            entry(code, row["名称"])["warnings"].append({"title": body, "url": row["网址"]})
            continue
        if _FOLLOW_UP.search(body):
            continue
        for kind, pattern, score in _POSITIVE:
            if pattern.search(body):
                item = entry(code, row["名称"])
                item["best"][kind] = max(item["best"].get(kind, 0), score)
                item["items"].append(
                    {"kind": kind, "title": body, "url": row["网址"], "date": str(row["公告日期"])[:10]}
                )
                break
    for _, row in forecasts.iterrows():
        code = str(row["股票代码"])
        change = float(row["业绩变动幅度"]) if pd.notna(row["业绩变动幅度"]) else 0.0
        if row["预告类型"] == "预增" and change < 50:
            continue
        score = 25 + min(int(change // 20), 15) if row["预告类型"] == "预增" else 25
        item = entry(code, row["股票简称"])
        item["best"]["业绩预增"] = max(item["best"].get("业绩预增", 0), score)
        item["items"].append(
            {
                "kind": "业绩预增" if row["预告类型"] == "预增" else "业绩扭亏",
                "title": str(row["业绩变动"])[:120],
                "url": f"https://data.eastmoney.com/notices/stock/{code}.html",
                "date": str(row["公告日期"])[:10],
            }
        )
    return {code: s for code, s in stocks.items() if s["best"]}


def _score(code: str, info: dict, quote: list[str] | None, phase: str) -> dict | None:
    """利好分 + 盘面分 − 风险分。返回 None 表示不入选（ST、停牌等）。"""
    if quote is None or "ST" in quote[1].upper():
        return None
    price, prev, open_ = float(quote[3] or 0), float(quote[4] or 0), float(quote[5] or 0)
    limit_up = float(quote[47] or 0)
    volume_ratio = float(quote[49] or 0)
    mktcap = float(quote[45] or 0)
    if prev <= 0:
        return None

    reasons: list[str] = []
    risks: list[str] = []
    catalyst = sum(info["best"].values())
    market_score = 0
    opened = phase == "盘中" and open_ > 0 and price > 0
    gap = (open_ / prev - 1) * 100 if opened else None
    pct = (price / prev - 1) * 100 if price > 0 else None

    if opened:
        locked = limit_up > 0 and open_ >= limit_up and price >= limit_up
        if locked:
            market_score -= 10
            risks.append("开盘即涨停且未打开，普通投资者难以买入")
        elif 1 <= gap <= 7:
            market_score += 15
            reasons.append(f"高开 {gap:.1f}%，市场认可利好")
        elif gap > 7:
            market_score += 8
            reasons.append(f"大幅高开 {gap:.1f}%")
            risks.append("高开过多，追高风险大")
        elif gap < 0:
            market_score -= 10
            risks.append(f"低开 {gap:.1f}%，市场未认可")
        if volume_ratio >= 5:
            market_score += 15
            reasons.append(f"量比 {volume_ratio:.1f}，明显放量")
        elif volume_ratio >= 2:
            market_score += 10
            reasons.append(f"量比 {volume_ratio:.1f}，放量")
        if not locked and price > open_:
            market_score += 5
            reasons.append("开盘后继续走高")
        elif not locked and price < open_ * 0.98:
            market_score -= 8
            risks.append("开盘后回落超过 2%")
    if info["warnings"]:
        market_score -= 25
        risks.append(f"同期有 {len(info['warnings'])} 条风险公告（如减持、处罚）")
    if 0 < mktcap < 30:
        market_score -= 5
        risks.append(f"总市值仅 {mktcap:.0f} 亿，波动大")

    total = catalyst + market_score
    # 开盘前只有利好分（满分约 60），开盘后再加盘面分，两种情况分档不同
    steps = (60, 45, 30, 15) if opened else (40, 30, 20, 12)
    stars = 5 - next((i for i, t in enumerate(steps) if total >= t), 4)
    return {
        "code": code,
        "name": quote[1],
        "score": total,
        "stars": stars,
        "catalyst_score": catalyst,
        "market_score": market_score,
        "catalysts": info["items"][:4],
        "warnings": info["warnings"][:3],
        "reasons": reasons,
        "risks": risks,
        "price": price,
        "prev_close": prev,
        "open": open_ if opened else None,
        "gap": round(gap, 2) if gap is not None else None,
        "pct": round(pct, 2) if pct is not None else None,
        "volume_ratio": volume_ratio if opened else None,
        "mktcap": mktcap,
    }


async def _compute() -> dict:
    now_sh = datetime.now(SHANGHAI)
    today = now_sh.strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "Mozilla/5.0"}) as client:
        days = await _trading_days(client)
    # 今天是否交易日：工作日且（已开盘后上证日 K 有今天，或尚未开盘）
    trading_today = now_sh.weekday() < 5 and (days[-1] == today or now_sh.hour < 10)
    phase = _phase(now_sh, trading_today)
    preview = phase in ("收盘后", "休市")
    dates, previous = _window(days, today, preview)
    notices, forecasts = await asyncio.gather(
        asyncio.to_thread(_fetch_announcements, dates), asyncio.to_thread(_fetch_forecasts, dates)
    )
    candidates = _catalysts(notices, forecasts)
    quotes: dict[str, list[str]] = {}
    if candidates:
        symbols = [market._exchange_prefix(c) + c for c in candidates]
        for f in await market.fetch_quote_fields(symbols):
            if len(f) > 49:
                quotes[f[2]] = f
    picks = [p for c, info in candidates.items() if (p := _score(c, info, quotes.get(c), phase))]
    picks.sort(key=lambda p: (p["score"], p["catalyst_score"]), reverse=True)
    return {
        "phase": phase,
        # 收盘后、休市时展示的是下一个交易日的候选：只按利好评分，盘面确认要等开盘
        "preview": preview,
        "as_of": now_sh.strftime("%Y-%m-%d %H:%M:%S"),
        "window": f"{previous} 起披露的公告" if preview else f"{previous} 收盘后至今",
        "scanned": int(len(notices) + len(forecasts)),
        "picks": picks[:20],
    }


async def _freeze(result: dict) -> None:
    """交易日 9:35 后第一次算出的名单存库，作为当天的正式入选，之后不再改。"""
    now_sh = datetime.now(SHANGHAI)
    if result["phase"] != "盘中" or (now_sh.hour, now_sh.minute) < (9, 35):
        return
    name = f"{_FREEZE_PREFIX}{now_sh:%Y-%m-%d}"
    async with SessionLocal() as db:
        if await db.get(ScreenData, name) is not None:
            return
        picks = [
            {k: p[k] for k in ("code", "name", "score", "stars", "open", "prev_close")}
            | {"kinds": sorted({c["kind"] for c in p["catalysts"]})}
            for p in result["picks"][:10]
            if p["stars"] >= 3
        ]
        db.add(ScreenData(name=name, payload={"date": f"{now_sh:%Y-%m-%d}", "picks": picks}, updated_at=now()))
        await db.commit()
        logger.info("火眼金睛 %s 定格 %d 只", name[len(_FREEZE_PREFIX):], len(picks))


@router.get("")
async def today(_: User = Depends(current_user)) -> dict:
    """今日名单。60 秒内复用上一次的计算结果。"""
    global _cache
    async with _lock:
        if _cache is None or time.monotonic() - _cache[0] > 60:
            result = await _compute()
            _cache = (time.monotonic(), result)
            try:
                await _freeze(result)
            except Exception:  # noqa: BLE001 定格失败不影响当天展示
                logger.exception("火眼金睛定格失败")
        return _cache[1]


@router.get("/history")
async def history(_: User = Depends(current_user)) -> list[dict]:
    """最近 10 个交易日定格的名单，以及每只股票从入选当天开盘到现在的涨跌。"""
    async with SessionLocal() as db:
        rows = list(
            await db.scalars(
                select(ScreenData)
                .where(ScreenData.name.like(f"{_FREEZE_PREFIX}%"))
                .order_by(ScreenData.name.desc())
                .limit(10)
            )
        )
    codes = sorted({p["code"] for r in rows for p in r.payload["picks"]})
    prices: dict[str, float] = {}
    if codes:
        for f in await market.fetch_quote_fields([market._exchange_prefix(c) + c for c in codes]):
            if len(f) > 3 and f[3]:
                prices[f[2]] = float(f[3])
    out = []
    for r in rows:
        picks = []
        for p in r.payload["picks"]:
            base = p.get("open") or p.get("prev_close")
            now_price = prices.get(p["code"])
            change = round((now_price / base - 1) * 100, 2) if base and now_price else None
            picks.append({**p, "price": now_price, "since_open": change})
        valid = [p["since_open"] for p in picks if p["since_open"] is not None]
        out.append(
            {
                "date": r.payload["date"],
                "picks": picks,
                "avg": round(sum(valid) / len(valid), 2) if valid else None,
                "win_rate": round(sum(v > 0 for v in valid) / len(valid) * 100) if valid else None,
            }
        )
    return out
