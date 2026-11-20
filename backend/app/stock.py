"""个股详情页与 AI 诊股。

- 详情：行情与估值（腾讯批量报价）、当日分时、最近 250 个交易日日 K、财务指标、新闻与公告。
- 诊股：基本面、估值、技术面、资金面、消息面五项，每项 0–100 分。
  打分规则全部写在本文件里、由程序计算，每一条加分减分都列出原因；模型只负责解读，不改分。
  评分只反映数据状态，不是买卖建议。
"""

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.hawkeye import _FOLLOW_UP, _NEGATIVE, _NOT_BUSINESS, _POSITIVE
from app.models import User
from app.overview import _parse_minutes
from app.security import current_user
from app.tools import market, screener
from app.tools.base import ToolError, ToolResult
from app.tools.fundamentals import get_financials
from app.tools.market import SHANGHAI, _exchange_prefix, resolve_stock
from app.tools.news import get_stock_news_items

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stock", tags=["个股"])

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_cache: dict[tuple, tuple[float, Any]] = {}
_locks: dict[tuple, asyncio.Lock] = {}


async def _cached(key: tuple, ttl: float, fn) -> Any:
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await fn()
        _cache[key] = (time.monotonic(), value)
        return value


def _f(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_quote(f: list[str]) -> dict[str, Any]:
    """腾讯批量报价的一行转成字典。字段位置见 market.fetch_quote_fields 的说明。"""
    return {
        "code": f[2],
        "name": f[1].replace(" ", ""),
        "price": _f(f[3]),
        "prev_close": _f(f[4]),
        "open": _f(f[5]),
        "volume_lots": _f(f[6]),
        "change": _f(f[31]),
        "percent": _f(f[32]),
        "high": _f(f[33]),
        "low": _f(f[34]),
        "amount_yi": (_f(f[37]) or 0) / 1e4,
        "turnover": _f(f[38]),
        "pe_ttm": _f(f[39]),
        "amplitude": _f(f[43]),
        "float_mktcap": _f(f[44]),
        "mktcap": _f(f[45]),
        "pb": _f(f[46]),
        "limit_up": _f(f[47]),
        "limit_down": _f(f[48]),
        "volume_ratio": _f(f[49]),
        "dividend_yield": _f(f[64]) if len(f) > 64 else None,
        "high_52w": _f(f[67]) if len(f) > 68 else None,
        "low_52w": _f(f[68]) if len(f) > 68 else None,
        "as_of": datetime.strptime(f[30], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
    }


def _code(text: str) -> str:
    try:
        code, _ = resolve_stock(text)
    except ToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return code


async def get_quote(code: str) -> dict[str, Any]:
    rows = await market.fetch_quote_fields([_exchange_prefix(code) + code])
    if not rows or len(rows[0]) < 50 or not rows[0][3]:
        raise ToolError(f"没有代码为 {code} 的 A 股股票")
    return parse_quote(rows[0])


async def get_day_bars(code: str, count: int = 250) -> list[list]:
    """日 K（前复权），每根 [日期, 开, 收, 低, 高, 成交量（股）]，与页面 K 线图格式一致。"""

    async def fetch() -> list[list]:
        async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as client:
            bars = await market.fetch_day_bars(client, _exchange_prefix(code) + code, count)
        return [[b[0], float(b[1]), float(b[2]), float(b[4]), float(b[3]), float(b[5]) * 100] for b in bars]

    return await _cached(("bars", code, count), 120, fetch)


def industry_of(code: str) -> str:
    fin = screener._fin
    row = fin["rows"].get(code) if fin else None
    return row.get("industry", "") if row else ""


@router.get("/search")
async def search(q: str = "", _: User = Depends(current_user)) -> list[dict[str, str]]:
    """按代码或简称搜索股票，最多 10 条。代码前缀匹配，简称包含匹配。"""
    text = market._normalize(q)
    if not text:
        return []
    by_code = market._table["by_code"]
    if text.isdigit():
        hits = [c for c in by_code if c.startswith(text)]
    else:
        hits = [c for c, n in by_code.items() if text in market._normalize(n)]
        # 完全相同、以关键词开头的排在前面
        hits.sort(key=lambda c: (market._normalize(by_code[c]) != text, not market._normalize(by_code[c]).startswith(text)))
    return [{"code": c, "name": by_code[c]} for c in hits[:10]]


@router.get("/{symbol}")
async def profile(symbol: str, _: User = Depends(current_user)) -> dict:
    """行情、估值、当日分时、日 K。同一只股票 10 秒内只取一次。"""
    code = _code(symbol)

    async def fetch() -> dict:
        prefixed = _exchange_prefix(code) + code
        async with httpx.AsyncClient(timeout=6, headers=_HEADERS) as client:
            quote_task = get_quote(code)
            minute_task = client.get(f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={prefixed}")
            bars_task = get_day_bars(code)
            quote, minute_resp, bars = await asyncio.gather(
                quote_task, minute_task, bars_task, return_exceptions=True
            )
        if isinstance(quote, BaseException):
            raise quote
        minutes, date = [], ""
        if not isinstance(minute_resp, BaseException):
            try:
                data = minute_resp.json()["data"][prefixed]["data"]
                minutes, date = _parse_minutes(data["data"]), data["date"]
            except Exception:  # noqa: BLE001 分时取不到时页面只显示日 K
                logger.warning("分时数据解析失败：%s", code)
        if isinstance(bars, BaseException):
            logger.warning("日 K 取不到：%s %r", code, bars)
            bars = []
        return {
            **quote,
            "industry": industry_of(code),
            "date": f"{date[:4]}-{date[4:6]}-{date[6:]}" if date else "",
            "minutes": minutes,
            "bars": bars,
            "source": {"name": "腾讯财经", "url": f"https://gu.qq.com/{prefixed}/gp"},
        }

    try:
        return await _cached(("profile", code), 10, fetch)
    except ToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        logger.warning("个股详情 %s 取数失败：%r", code, exc)
        raise HTTPException(status_code=502, detail="行情数据暂时取不到，请稍后重试") from exc


@router.get("/{symbol}/financials")
async def financials(symbol: str, _: User = Depends(current_user)) -> dict:
    code = _code(symbol)
    try:
        result = await get_financials(code, periods=8)
    except ToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="财务数据暂时取不到") from exc
    return result.blocks[0]


# ---------------------------------------------------------------- 公告与新闻


def _notice_url(code: str, art_code: str) -> str:
    return f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html"


async def fetch_announcements(codes: list[str], size: int = 30) -> list[dict[str, str]]:
    """东方财富公告列表，多只股票一次取，最新的在前。每条：code、name、title、date、type、url。"""
    params = {
        "sr": "-1",
        "page_size": str(size),
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "stock_list": ",".join(codes),
    }
    async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as client:
        resp = await client.get("https://np-anotice-stock.eastmoney.com/api/security/ann", params=params)
        resp.raise_for_status()
        rows = (resp.json().get("data") or {}).get("list") or []
    out = []
    for row in rows:
        stock = next((c for c in row.get("codes", []) if c.get("stock_code") in codes), None)
        if stock is None:
            continue
        title = str(row.get("title_ch") or row.get("title") or "")
        out.append(
            {
                "code": stock["stock_code"],
                "name": stock.get("short_name", ""),
                "id": row["art_code"],
                "title": title.split(":", 1)[-1],
                "date": str(row.get("notice_date", ""))[:10],
                "time": str(row.get("display_time", ""))[:16],
                "type": (row.get("columns") or [{}])[0].get("column_name", ""),
                "url": _notice_url(stock["stock_code"], row["art_code"]),
            }
        )
    return out


@router.get("/{symbol}/news")
async def stock_news(symbol: str, _: User = Depends(current_user)) -> dict:
    """公告（东方财富）与新闻（东方财富）。任一取不到时该项为空，并在 errors 里说明。"""
    code = _code(symbol)
    errors = []
    try:
        notices = await _cached(("notices", code), 300, lambda: fetch_announcements([code], 30))
    except Exception as exc:  # noqa: BLE001
        logger.warning("公告取不到：%s %r", code, exc)
        notices, errors = [], ["公告"]
    try:
        news = await get_stock_news_items(code, 20)
    except Exception as exc:  # noqa: BLE001
        logger.warning("新闻取不到：%s %r", code, exc)
        news = []
        errors.append("新闻")
    return {"announcements": notices, "news": news, "errors": errors}


# ---------------------------------------------------------------- 诊股


def _band(score: float) -> str:
    if score >= 70:
        return "强"
    if score >= 58:
        return "偏强"
    if score >= 42:
        return "中性"
    if score >= 30:
        return "偏弱"
    return "弱"


def _dimension(name: str, items: list[tuple[str, int]], note: str = "") -> dict:
    """items：（说明，分值变化）。0 分的条目是参考信息，不影响分数。"""
    score = max(0, min(100, 50 + sum(delta for _, delta in items)))
    return {
        "name": name,
        "score": score,
        "level": _band(score),
        "items": [{"text": text, "delta": delta} for text, delta in items],
        "note": note,
    }


def _missing(name: str, reason: str) -> dict:
    return {"name": name, "score": None, "level": "暂无数据", "items": [], "note": reason}


def _fundamental(code: str) -> dict:
    fin = screener._fin
    row = fin["rows"].get(code) if fin else None
    if not row:
        return _missing("基本面", "财务数据还在准备，或该股票没有披露业绩报表")
    items: list[tuple[str, int]] = []
    roe = row.get("roe_annual")
    if roe is not None and not math.isnan(roe):
        if roe >= 15:
            items.append((f"最新年报 ROE {roe:.1f}%，盈利能力强（≥15%）", 15))
        elif roe >= 8:
            items.append((f"最新年报 ROE {roe:.1f}%，盈利能力一般（8%~15%）", 5))
        elif roe >= 0:
            items.append((f"最新年报 ROE {roe:.1f}%，盈利能力偏弱（<8%）", -5))
        else:
            items.append((f"最新年报 ROE {roe:.1f}%，为负，处于亏损", -20))
    profit = row.get("profit_yoy")
    if profit is not None and not math.isnan(profit):
        word = f"增长 {profit:.1f}%" if profit >= 0 else f"下降 {abs(profit):.1f}%"
        delta = 12 if profit >= 20 else 4 if profit >= 0 else -6 if profit >= -20 else -12
        items.append((f"净利润同比{word}", delta))
    revenue = row.get("revenue_yoy")
    if revenue is not None and not math.isnan(revenue):
        word = f"增长 {revenue:.1f}%" if revenue >= 0 else f"下降 {abs(revenue):.1f}%"
        delta = 8 if revenue >= 15 else 3 if revenue >= 0 else -5
        items.append((f"营收同比{word}", delta))
    margin = row.get("gross_margin")
    if margin is not None and not math.isnan(margin):
        if margin >= 40:
            items.append((f"毛利率 {margin:.1f}%，较高（≥40%）", 5))
        elif margin < 15:
            items.append((f"毛利率 {margin:.1f}%，较低（<15%）", -3))
    debt = row.get("debt_ratio")
    financial = any(k in row.get("industry", "") for k in ("银行", "保险", "证券", "多元金融"))
    if debt is not None and not math.isnan(debt) and not financial:
        if debt > 70:
            items.append((f"资产负债率 {debt:.1f}%，偏高（>70%）", -8))
        elif debt <= 40:
            items.append((f"资产负债率 {debt:.1f}%，较低（≤40%）", 3))
    note = f"业绩数据为 {fin['period']} 报告期（东方财富业绩报表）"
    return _dimension("基本面", items, note)


async def _industry_pe(industry: str) -> tuple[float, int] | None:
    """同行业（东方财富行业分类）市盈率 TTM 中位数，只算正值；同行少于 5 家时不算。"""
    fin = screener._fin
    if not industry or not fin:
        return None
    try:
        live = await screener._get_live()
    except Exception:  # noqa: BLE001
        return None
    peers = [c for c, r in fin["rows"].items() if r.get("industry") == industry]
    values = sorted(v for v in live["pe_ttm"].reindex(peers).dropna() if v > 0)
    if len(values) < 5:
        return None
    return values[len(values) // 2], len(values)


async def _valuation(code: str, quote: dict) -> dict:
    items: list[tuple[str, int]] = []
    pe, pb, dy = quote["pe_ttm"], quote["pb"], quote["dividend_yield"]
    industry = industry_of(code)
    if pe is None or pe <= 0:
        items.append(("市盈率 TTM 为负或无效（最近四个季度合计亏损），无法用市盈率估值", -20))
    else:
        median = await _industry_pe(industry)
        if median:
            mid, n = median
            ratio = pe / mid
            diff = (ratio - 1) * 100
            where = f"低于行业中位数 {abs(diff):.0f}%" if diff < 0 else f"高于行业中位数 {diff:.0f}%"
            delta = 20 if ratio <= 0.6 else 10 if ratio <= 0.9 else 0 if ratio <= 1.2 else -10 if ratio <= 1.8 else -20
            items.append((f"市盈率 TTM {pe:.1f} 倍，{industry}行业 {n} 家的中位数 {mid:.1f} 倍，{where}", delta))
        else:
            delta = 10 if pe <= 15 else 0 if pe <= 30 else -10 if pe <= 60 else -20
            items.append((f"市盈率 TTM {pe:.1f} 倍（无同行数据，按绝对水平：≤15 偏低，>60 偏高）", delta))
    if pb is not None and pb > 0:
        if pb < 1:
            items.append((f"市净率 {pb:.2f} 倍，低于 1（股价低于每股净资产）", 8))
        elif pb > 8:
            items.append((f"市净率 {pb:.2f} 倍，偏高（>8）", -5))
        else:
            items.append((f"市净率 {pb:.2f} 倍", 0))
    if dy is not None and dy > 0:
        if dy >= 3:
            items.append((f"股息率 {dy:.2f}%，较高（≥3%）", 8))
        elif dy >= 1.5:
            items.append((f"股息率 {dy:.2f}%", 3))
    return _dimension("估值", items, "分数越高表示估值越便宜；同行比较用东方财富行业分类")


def _technical(bars: list[list]) -> dict:
    if len(bars) < 60:
        return _missing("技术面", "上市不足 60 个交易日，或日 K 暂时取不到")
    closes = [b[2] for b in bars]
    price = closes[-1]

    def ma(n: int) -> float:
        return sum(closes[-n:]) / n

    ma5, ma10, ma20, ma60 = ma(5), ma(10), ma(20), ma(60)
    items: list[tuple[str, int]] = []
    if price > ma5 > ma10 > ma20 > ma60:
        items.append(("均线多头排列（收盘价 > 5 日 > 10 日 > 20 日 > 60 日均线）", 15))
    elif price < ma5 < ma10 < ma20 < ma60:
        items.append(("均线空头排列（收盘价 < 5 日 < 10 日 < 20 日 < 60 日均线）", -15))
    items.append((f"收盘价{'站上' if price >= ma20 else '跌破'} 20 日均线（{ma20:.2f}）", 5 if price >= ma20 else -5))
    items.append((f"收盘价{'站上' if price >= ma60 else '跌破'} 60 日均线（{ma60:.2f}）", 5 if price >= ma60 else -5))

    dif = [a - b for a, b in zip(screener._ema(closes, 12), screener._ema(closes, 26))]
    dea = screener._ema(dif, 9)
    crossed_up = any(dif[i - 1] <= dea[i - 1] and dif[i] > dea[i] for i in range(len(dif) - 3, len(dif)))
    crossed_down = any(dif[i - 1] >= dea[i - 1] and dif[i] < dea[i] for i in range(len(dif) - 3, len(dif)))
    if crossed_up:
        items.append(("近 3 日 MACD 金叉", 6))
    elif crossed_down:
        items.append(("近 3 日 MACD 死叉", -6))
    elif dif[-1] > dea[-1]:
        items.append(("MACD 处于金叉状态（DIF 在 DEA 之上）", 3))
    else:
        items.append(("MACD 处于死叉状态（DIF 在 DEA 之下）", -3))

    rsi = screener._indicators(closes)["rsi14"]
    if rsi > 80:
        items.append((f"RSI14 为 {rsi:.0f}，超买（>80），短期回调风险大", -8))
    elif rsi > 70:
        items.append((f"RSI14 为 {rsi:.0f}，偏热（>70）", -3))
    elif rsi < 20:
        items.append((f"RSI14 为 {rsi:.0f}，超卖（<20）", 3))
    else:
        items.append((f"RSI14 为 {rsi:.0f}", 0))

    ret20 = (price / closes[-21] - 1) * 100 if len(closes) > 20 else None
    if ret20 is not None:
        word = f"上涨 {ret20:.1f}%" if ret20 >= 0 else f"下跌 {abs(ret20):.1f}%"
        items.append((f"近 20 个交易日{word}", 0))
    high = max(b[4] for b in bars)
    drawdown = (price / high - 1) * 100
    if drawdown > -5:
        items.append((f"距近一年最高价 {high:.2f} 不到 5%", 5))
    elif drawdown < -40:
        items.append((f"较近一年最高价 {high:.2f} 回撤 {abs(drawdown):.0f}%", -5))
    return _dimension("技术面", items, f"日 K 截至 {bars[-1][0]}（前复权）")


async def _fund_flow(code: str) -> list[tuple[str, float]]:
    """最近 5 个交易日主力净流入（元）。东方财富资金流向。"""
    secid = f"{1 if _exchange_prefix(code) == 'sh' else 0}.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {"secid": secid, "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": "5"}
    async with httpx.AsyncClient(timeout=6, headers=_HEADERS) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        lines = ((resp.json().get("data") or {}).get("klines")) or []
        flows = [(line.split(",")[0], float(line.split(",")[1])) for line in lines]
        # 日线资金流向收盘后才有当天的；盘中用实时接口补上今天的主力净流入
        try:
            live = await client.get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                params={"secids": secid, "fields": "f12,f62,f124"},
            )
            row = live.json()["data"]["diff"][0]
            day = datetime.fromtimestamp(int(row["f124"]), SHANGHAI).strftime("%Y-%m-%d")
            if row.get("f62") not in (None, "-") and (not flows or flows[-1][0] < day):
                flows = [*flows[1:], (day, float(row["f62"]))] if len(flows) >= 5 else [*flows, (day, float(row["f62"]))]
        except Exception:  # noqa: BLE001 实时部分取不到时只用日线
            pass
    return flows


async def _capital(code: str, quote: dict) -> dict:
    items: list[tuple[str, int]] = []
    note = "主力 = 超大单 + 大单（东方财富资金流向）"
    try:
        flows = await _cached(("flow", code), 60, lambda: _fund_flow(code))
    except Exception as exc:  # noqa: BLE001
        logger.warning("资金流向取不到：%s %r", code, exc)
        flows = []
    if flows:
        day, last = flows[-1]
        total = sum(v for _, v in flows)
        in_days = sum(v > 0 for _, v in flows)
        items.append(
            (f"{day} 主力{'净流入' if last >= 0 else '净流出'} {abs(last) / 1e8:.2f} 亿元", 10 if last > 0 else -10)
        )
        items.append(
            (
                f"近 {len(flows)} 个交易日主力合计{'净流入' if total >= 0 else '净流出'} {abs(total) / 1e8:.2f} 亿元"
                f"（其中 {in_days} 天净流入）",
                10 if total > 0 else -10,
            )
        )
    else:
        note = "资金流向暂时取不到，只按量价判断"
    ratio, pct, turnover = quote["volume_ratio"], quote["percent"], quote["turnover"]
    if ratio is not None and pct is not None:
        if ratio >= 2 and pct > 0:
            items.append((f"量比 {ratio:.2f}，放量上涨", 6))
        elif ratio >= 2 and pct < 0:
            items.append((f"量比 {ratio:.2f}，放量下跌", -6))
        else:
            items.append((f"量比 {ratio:.2f}", 0))
    if turnover is not None and turnover > 15:
        items.append((f"换手率 {turnover:.1f}%，交易过热（>15%）", -4))
    return _dimension("资金面", items, note)


_FORECAST_UP = ("业绩预增", re.compile(r"预增|扭亏|大幅增长"), 15)


async def _news(code: str) -> dict:
    try:
        notices = await _cached(("notices", code), 300, lambda: fetch_announcements([code], 30))
    except Exception as exc:  # noqa: BLE001
        logger.warning("公告取不到：%s %r", code, exc)
        return _missing("消息面", "公告暂时取不到")
    since = (datetime.now(SHANGHAI) - timedelta(days=30)).strftime("%Y-%m-%d")
    recent = [n for n in notices if n["date"] >= since]
    good, bad = 0, 0
    items: list[tuple[str, int]] = []
    for n in recent:
        title = n["title"]
        if _NEGATIVE.search(title):
            if bad < 3:
                items.append((f"{n['date']} 风险公告：{title[:40]}", -10))
            bad += 1
            continue
        if _FOLLOW_UP.search(title) or _NOT_BUSINESS.search(title):
            continue
        for kind, pattern, score in [*_POSITIVE, _FORECAST_UP]:
            if pattern.search(title):
                if good < 3:
                    items.append((f"{n['date']} {kind}：{title[:40]}", max(score // 2, 4)))
                good += 1
                break
    if not items:
        items.append((f"近 30 天 {len(recent)} 条公告，没有重大利好或风险类公告", 0))
    return _dimension("消息面", items, "按公告标题分类（与火眼金睛同一套规则），不含媒体新闻")


async def diagnose(symbol: str) -> dict:
    code, name = resolve_stock(symbol)

    async def build() -> dict:
        quote = await get_quote(code)
        try:
            bars = await get_day_bars(code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("日 K 取不到：%s %r", code, exc)
            bars = []
        valuation, capital, news = await asyncio.gather(
            _valuation(code, quote), _capital(code, quote), _news(code)
        )
        dims = [_fundamental(code), valuation, _technical(bars), capital, news]
        scored = [d["score"] for d in dims if d["score"] is not None]
        total = round(sum(scored) / len(scored)) if scored else None
        return {
            "type": "diagnosis",
            "code": code,
            "name": quote["name"] or name,
            "industry": industry_of(code),
            "price": quote["price"],
            "percent": quote["percent"],
            "as_of": quote["as_of"],
            "score": total,
            "level": _band(total) if total is not None else "暂无数据",
            "dimensions": dims,
            "disclaimer": "评分由固定规则根据公开数据计算，只反映数据状态，不构成投资建议。",
        }

    return await _cached(("diagnosis", code), 60, build)


@router.get("/{symbol}/diagnosis")
async def diagnosis(symbol: str, _: User = Depends(current_user)) -> dict:
    code = _code(symbol)
    try:
        return await diagnose(code)
    except ToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        logger.warning("诊股 %s 失败：%r", code, exc)
        raise HTTPException(status_code=502, detail="诊断所需数据暂时取不到，请稍后重试") from exc


async def diagnose_stock(symbol: str) -> ToolResult:
    """给模型用：五项评分及每一条加减分原因，页面同时展示评分卡。"""
    result = await diagnose(symbol)
    lines = [
        f"{result['name']}（{result['code']}）诊股评分，行情时间 {result['as_of']}，"
        f"所属行业 {result['industry'] or '未知'}。评分卡已由系统展示给用户，回答里不要再画表格。",
        f"综合 {result['score']} 分（{result['level']}），满分 100，50 分为中性。",
    ]
    for d in result["dimensions"]:
        if d["score"] is None:
            lines.append(f"【{d['name']}】暂无数据：{d['note']}")
            continue
        lines.append(f"【{d['name']}】{d['score']} 分（{d['level']}）。{d['note']}")
        for item in d["items"]:
            sign = f"加 {item['delta']} 分" if item["delta"] > 0 else f"减 {-item['delta']} 分" if item["delta"] < 0 else "不计分"
            lines.append(f"- {item['text']}（{sign}）")
    lines.append(
        "解读要求：分数和每条依据照抄，不得自行改分或补充没有给出的数据；先给综合结论，再按五项说明主要加分和减分原因，"
        "最后提示风险。不得给出买入、卖出、目标价等投资建议。"
    )
    lines.append(
        f"来源（请原样写在回答末尾）：[腾讯财经·{result['name']}行情](https://gu.qq.com/{_exchange_prefix(result['code'])}{result['code']}/gp)、"
        f"[东方财富·{result['name']}公告](https://data.eastmoney.com/notices/stock/{result['code']}.html)"
    )
    return ToolResult(text="\n".join(lines), blocks=[result])
