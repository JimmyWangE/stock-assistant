"""每日 AI 报告：交易日开盘前的早报（8:45 起）和收盘后的复盘（15:30 起）。

程序先取齐数据、整理成文字（facts），再交给模型按固定结构写成报告。全站共用，每天每类一份，存库后可回看。
facts 原文随报告一起存库，页面可展开核对报告里的每个数字。

服务器上可手动生成（例如验证时不想等到点）：
    python -m app.reports close           # 今天的收盘复盘，已有则跳过
    python -m app.reports morning --force # 重新生成今天的早报并覆盖
"""

import asyncio
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone

import akshare as ak
import httpx
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app import hawkeye, llm, overview, tradedays
from app.db import SessionLocal
from app.models import DailyReport, User, now
from app.security import current_user
from app.tools import policy
from app.tools.market import SHANGHAI

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["每日报告"])

KINDS = {"morning": "早报", "close": "收盘复盘"}

# 隔夜外围：腾讯报价代码 -> 显示名
_OVERSEAS = [
    ("usDJI", "道琼斯指数"),
    ("usIXIC", "纳斯达克指数"),
    ("usINX", "标普500指数"),
    ("usHXC", "纳斯达克中国金龙指数"),
    ("hkHSI", "恒生指数"),
    ("hkHSTECH", "恒生科技指数"),
]
_COMMODITIES = [("hf_GC", "纽约黄金"), ("hf_CL", "纽约原油")]

_PROMPTS = {
    "morning": """你是 A 股投研团队的市场分析员，负责在开盘前写一份早报，供团队成员快速了解今天开盘前需要知道的信息。

只能使用下面"数据"里给出的内容，不得补充任何没有给出的数字、新闻或事件；数字和正负号照抄。
"上涨/下跌"、行业排名和"最强/最弱"以数据里写明的为准，不要自己比较数字得出相反的结论。
引用新闻、政策、公告时附上数据里给出的 Markdown 链接。不得给出买入、卖出等投资建议，不得预测指数点位。

按以下结构用 Markdown 输出，总长度 800 到 1200 字，各部分标题用二级标题：
## 今日看点（3 条以内，每条一句话，概括最值得关注的事）
## 隔夜外围（美股、港股、中概股、商品与汇率，说明涨跌和可能的影响方向）
## 上一交易日 A 股回顾（指数、成交额、涨跌家数、领涨领跌行业）
## 重要消息（新闻与官方政策分开写，各挑最重要的 3 到 5 条）
## 盘前公告利好（火眼金睛候选，如有）
## 风险提示""",
    "close": """你是 A 股投研团队的市场分析员，负责在收盘后写一份当日复盘，供团队成员快速回顾今天的市场。

只能使用下面"数据"里给出的内容，不得补充任何没有给出的数字、新闻或事件；数字和正负号照抄。
"高开/低开""上涨/下跌"、行业排名和"最强/最弱"以数据里写明的为准，不要自己比较数字得出相反的结论。
引用新闻、政策时附上数据里给出的 Markdown 链接。不得给出买入、卖出等投资建议，不得预测指数点位。

按以下结构用 Markdown 输出，总长度 1000 到 1500 字，各部分标题用二级标题：
## 今日要点（3 条，每条一句话）
## 指数与成交
## 市场情绪（涨跌家数、涨跌停、涨跌分布）
## 行业板块与资金（领涨领跌、资金流入流出）
## 个股表现（涨幅榜、成交额榜里值得注意的）
## 重要消息（新闻与官方政策分开写）
## 火眼金睛今日表现（如有）
## 明日关注""",
}


def _title(day: str, kind: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.month}月{d.day}日 {KINDS[kind]}"


# ---------------------------------------------------------------- 取数


async def _overseas() -> list[str]:
    codes = [c for c, _ in _OVERSEAS + _COMMODITIES] + ["whUSDCNY"]
    async with httpx.AsyncClient(timeout=6) as client:
        resp = await client.get(f"https://qt.gtimg.cn/q={','.join(codes)}")
        resp.raise_for_status()
    body = resp.content.decode("gbk", errors="replace")
    raw = {line.split("=")[0].strip().removeprefix("v_"): line.split('"')[1] for line in body.split(";") if '"' in line}
    lines = []
    for code, name in _OVERSEAS:
        f = raw.get(code, "").split("~")
        if len(f) > 32 and f[3]:
            lines.append(f"{name} {float(f[3]):.2f}，涨跌幅 {float(f[32]):+.2f}%（行情时间 {f[30]}）")
    for code, name in _COMMODITIES:
        f = raw.get(code, "").split(",")
        if len(f) > 12 and f[0]:
            lines.append(f"{name} {float(f[0]):.2f}，涨跌幅 {float(f[1]):+.2f}%（{f[12]} {f[6]}）")
    f = raw.get("whUSDCNY", "").split("~")
    if len(f) > 13 and f[3]:
        lines.append(f"美元兑人民币 {float(f[3]):.4f}，涨跌幅 {float(f[13]):+.2f}%")
    return lines


def _news_since(since: datetime, limit: int) -> list[str]:
    df = ak.stock_news_global_em()
    df = df.copy()
    df["发布时间"] = pd.to_datetime(df["发布时间"], errors="coerce")
    df = df.dropna(subset=["发布时间"])
    df = df[df["发布时间"] >= since.replace(tzinfo=None)].sort_values("发布时间", ascending=False).head(limit)
    return [
        f"[{r['标题']}]({r['链接']})（{r['发布时间']:%m-%d %H:%M}）{str(r['摘要']).split('】', 1)[-1][:80]}"
        for _, r in df.iterrows()
    ]


async def _policies_since(day: str, limit: int) -> list[str]:
    items, _failed = await policy._fetch_all()
    return [
        f"[{i['title']}]({i['url']})（{i['date']}，{i['source']}）" for i in items if i["date"] >= day
    ][:limit]


async def _previous_trading_day(today: date) -> date:
    d = today - timedelta(days=1)
    for _ in range(15):
        if await tradedays.is_trading_day(d):
            return d
        d -= timedelta(days=1)
    return today - timedelta(days=1)


async def _section(title: str, fetch) -> str:
    """每一块数据独立取，取不到就写明"未取到"，让模型如实说明，不影响其他部分。"""
    try:
        lines = await fetch()
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告数据「%s」取不到：%r", title, exc)
        return f"### {title}\n（本项数据未取到，报告中如实说明）"
    body = "\n".join(f"- {line}" for line in lines) if isinstance(lines, list) else lines
    return f"### {title}\n{body or '（无）'}"


async def _hawkeye_lines(limit: int) -> list[str]:
    result = await hawkeye.latest()
    lines = []
    for p in result["picks"]:
        if p["stars"] < 3 or len(lines) >= limit:
            continue
        cats = "；".join(f"{c['kind']}：[{c['title'][:40]}]({c['url']})" for c in p["catalysts"][:2])
        risk = f"；风险：{'、'.join(p['risks'])}" if p["risks"] else ""
        lines.append(f"{p['name']}（{p['code']}）{p['stars']} 星，{cats}{risk}")
    return lines or ["今天没有三星及以上的候选"]


async def _hawkeye_today(day: str) -> list[str]:
    days = await hawkeye.history(None)
    today = next((d for d in days if d["date"] == day), None)
    if not today or not today["picks"]:
        return ["今天没有定格的火眼金睛名单"]
    lines = [
        f"{p['name']}（{p['code']}）{p['stars']} 星，入选依据 {'、'.join(p.get('kinds', []))}，"
        f"从开盘到收盘 {p['since_open']:+.2f}%" if p["since_open"] is not None else f"{p['name']}（{p['code']}）无收盘数据"
        for p in today["picks"]
    ]
    if today["avg"] is not None:
        lines.append(f"入选股票从开盘到收盘平均 {today['avg']:+.2f}%，上涨占比 {today['win_rate']}%")
    return lines


async def _market_lines() -> str:
    text = (await overview.get_market_overview()).text
    m = overview._board["market"]
    if m:
        text += "\n涨幅榜前八：" + "，".join(f"{r['name']}（{r['percent']:+.2f}%）" for r in m["gainers"][:8])
        text += "\n跌幅榜前五：" + "，".join(f"{r['name']}（{r['percent']:+.2f}%）" for r in m["losers"][:5])
    return text


async def collect_facts(kind: str, today: date) -> str:
    day = today.isoformat()
    if kind == "morning":
        previous = await _previous_trading_day(today)
        since = datetime.combine(previous, datetime.min.time()).replace(hour=15, tzinfo=SHANGHAI)
        parts = await asyncio.gather(
            _section("隔夜外围市场", _overseas),
            _section(f"上一交易日（{previous}）A 股收盘情况", _market_lines),
            _section("上一交易日收盘以来的财经新闻（东方财富）", lambda: asyncio.to_thread(_news_since, since, 15)),
            _section("近两日官方政策发布", lambda: _policies_since(previous.isoformat(), 8)),
            _section("火眼金睛：上一交易日收盘后发布利好公告的股票（三星及以上）", lambda: _hawkeye_lines(6)),
        )
    else:
        since = datetime.combine(today, datetime.min.time()).replace(hour=7, tzinfo=SHANGHAI)
        parts = await asyncio.gather(
            _section(f"今日（{day}）A 股收盘情况", _market_lines),
            _section("今日财经新闻（东方财富）", lambda: asyncio.to_thread(_news_since, since, 15)),
            _section("今日官方政策发布", lambda: _policies_since(day, 8)),
            _section("火眼金睛今日入选股票表现", lambda: _hawkeye_today(day)),
        )
    return f"今天是 {day}（北京时间）。\n\n" + "\n\n".join(parts)


# ---------------------------------------------------------------- 生成与存库


async def _write(kind: str, facts: str) -> str:
    messages = [
        {"role": "system", "content": _PROMPTS[kind]},
        {"role": "user", "content": f"数据：\n\n{facts}"},
    ]
    parts = [text async for k, text in llm.stream_chat(messages) if k == "text"]
    content = "".join(parts).strip()
    if len(content) < 200:
        raise RuntimeError(f"模型返回内容过短（{len(content)} 字）")
    return content


async def generate(kind: str, today: date | None = None, force: bool = False) -> DailyReport | None:
    """生成并保存某天的报告。已存在且不强制时直接返回已有的。"""
    today = today or datetime.now(SHANGHAI).date()
    day = today.isoformat()
    async with SessionLocal() as db:
        existing = await db.scalar(select(DailyReport).where(DailyReport.date == day, DailyReport.kind == kind))
        if existing and not force:
            return existing
    facts = await collect_facts(kind, today)
    content = await _write(kind, facts)
    async with SessionLocal() as db:
        row = await db.scalar(select(DailyReport).where(DailyReport.date == day, DailyReport.kind == kind))
        if row is None:
            row = DailyReport(date=day, kind=kind, content=content, facts=facts, created_at=now())
            db.add(row)
        else:
            row.content, row.facts, row.created_at = content, facts, now()
        await db.commit()
    logger.info("每日报告已生成：%s %s，%d 字", day, KINDS[kind], len(content))
    return row


def _due(kind: str, now_sh: datetime) -> bool:
    hm = (now_sh.hour, now_sh.minute)
    if kind == "morning":
        # 早报只在当天收盘前有意义；服务在盘中重启也补一份
        return (8, 45) <= hm < (15, 0)
    return hm >= (15, 30)


async def keep_reports() -> None:
    """后台任务：交易日到点生成报告。失败 10 分钟后重试，每类每天最多试 3 次。"""
    attempts: dict[tuple[str, str], int] = {}
    retry_at: dict[tuple[str, str], float] = {}
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(60)
        now_sh = datetime.now(SHANGHAI)
        day = now_sh.strftime("%Y-%m-%d")
        try:
            if not await tradedays.is_trading_day(now_sh.date()):
                continue
            for kind in KINDS:
                key = (day, kind)
                if not _due(kind, now_sh) or attempts.get(key, 0) >= 3 or loop.time() < retry_at.get(key, 0):
                    continue
                async with SessionLocal() as db:
                    exists = await db.scalar(
                        select(DailyReport.id).where(DailyReport.date == day, DailyReport.kind == kind)
                    )
                if exists:
                    continue
                attempts[key] = attempts.get(key, 0) + 1
                try:
                    await generate(kind, now_sh.date())
                except Exception:  # noqa: BLE001
                    logger.exception("每日报告生成失败：%s %s（第 %d 次）", day, KINDS[kind], attempts[key])
                    retry_at[key] = loop.time() + 600
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("每日报告检查失败")


# ---------------------------------------------------------------- 接口


def _out(row: DailyReport, full: bool) -> dict:
    data = {
        "date": row.date,
        "kind": row.kind,
        "title": _title(row.date, row.kind),
        # SQLite 读回来的时间不带时区，统一按 UTC 输出
        "created_at": (row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)).isoformat(),
    }
    if full:
        data |= {"content": row.content, "facts": row.facts}
    else:
        # 列表里只给开头一段作摘要
        body = [line for line in row.content.splitlines() if line.strip() and not line.startswith("#")]
        data["summary"] = re.sub(r"[*`_>#\[\]]|\(http[^)]*\)", "", body[0] if body else "")[:120]
    return data


@router.get("")
async def list_reports(_: User = Depends(current_user)) -> list[dict]:
    """最近 60 份报告（约一个月），最新的在前。"""
    async with SessionLocal() as db:
        rows = await db.scalars(
            # 同一天收盘复盘排在早报前面（close 按字母序在 morning 前）
            select(DailyReport).order_by(DailyReport.date.desc(), DailyReport.kind.asc()).limit(60)
        )
        return [_out(r, False) for r in rows]


@router.get("/latest")
async def latest(_: User = Depends(current_user)) -> dict:
    """首页用：最近一份报告（不论早报还是复盘）的全文。"""
    async with SessionLocal() as db:
        row = await db.scalar(select(DailyReport).order_by(DailyReport.created_at.desc()).limit(1))
    return {"report": _out(row, True) if row else None}


@router.get("/{day}/{kind}")
async def get_report(day: str, kind: str, _: User = Depends(current_user)) -> dict:
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="没有这类报告")
    async with SessionLocal() as db:
        row = await db.scalar(select(DailyReport).where(DailyReport.date == day, DailyReport.kind == kind))
    if row is None:
        raise HTTPException(status_code=404, detail="这一天没有这份报告")
    return _out(row, True)


async def _cli(kind: str, force: bool) -> None:
    from app.migrate import upgrade_database

    await asyncio.to_thread(upgrade_database)
    row = await generate(kind, force=force)
    print(f"{row.date} {KINDS[kind]}：{len(row.content)} 字\n\n{row.content}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in KINDS:
        sys.exit("用法：python -m app.reports morning|close [--force]")
    logging.basicConfig(level=logging.INFO)
    for noisy in ("httpx", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run(_cli(args[0], "--force" in args))
